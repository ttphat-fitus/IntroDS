"""Milestone 2 pipeline: parse every version of every paper, deduplicate, and store the results.

Per paper:
1. each version with TeX: find the root, gather \\input / \\include, normalize math, clean up,
   build the hierarchy, and collect its bibliography (.bib, \\bibitem, .bbl);
2. reference deduplication across versions: entries sharing a DOI, a normalized title or a key
   are one reference; the key of the latest version wins, fields are unioned (latest first) and
   every \\cite{} is renamed to the chosen key;
3. element deduplication across versions: identical (kind, cleaned content) share one element_id
   (`<yymm-nnnnn>#<prefix><n>`); each version keeps its own root and its own parent edges.

Results go to RAW_DIR/../parsed/<paper>.json.gz plus per-version / per-paper rows in SQLite, so
the run is resumable; `export` turns them into the elements / hierarchy / bibtex tables.
"""

import gzip
import json
import multiprocessing as mp
import re
import time
from pathlib import Path

from . import bibliography as bib
from . import config, latex, ranges, structure
from .sources import version_dir

PARSED_DIR_NAME = "parsed"
PREFIX = {
    "document": "root",
    "heading": "h",
    "list": "l",
    "item": "i",
    "sentence": "s",
    "formula": "e",
    "figure": "f",
}


def parsed_dir():
    return config.DATA_DIR / PARSED_DIR_NAME


# ---------------------------------------------------------------- one version


def _bib_files(vdir, names, all_files):
    found = []
    for name in names:
        for cand in (name, Path(name).name):
            if cand in all_files:
                found.append(cand)
                break
        else:  # \bibliography{refs} while the file sits in a sub-folder
            base = Path(name).name
            found += [f for f in all_files if Path(f).name == base]
    return found


def parse_version(arxiv_id, version):
    vdir = version_dir(arxiv_id, version)
    files = {p.relative_to(vdir).as_posix(): p for p in vdir.rglob("*") if p.is_file()}
    tex = {
        r: latex.strip_comments(latex.read_text(p))
        for r, p in files.items()
        if r.lower().endswith(".tex")
    }
    bbl = {r: latex.read_text(p) for r, p in files.items() if r.lower().endswith(".bbl")}
    if not tex:
        return {"status": "no_tex"}, None, [], set()

    root = latex.find_root(vdir, tex)
    full, used = latex.gather({**tex, **bbl}, root)
    title = bib.clean_value(latex.command_arg(full, "title")) or arxiv_id
    _, body = latex.split_document(full)

    # Bibliography: .bib (cited entries) -> \bibitem in the TeX -> .bbl to fill a missing .bib
    keys = bib.cited_keys(full)
    entries, sources = [], []
    for name in _bib_files(vdir, bib.bib_resources(full), files):
        keep = bib.parse_bib(latex.read_text(files[name]), None if "*" in keys else keys)
        entries += [bib.from_bib_fields(k, f) for k, f in keep.items()]
        sources.append("bib")
    if "\\bibitem" in full:
        entries += bib.parse_bibitems(full, "bibitem")
        sources.append("bibitem")
    if not entries and bbl:
        for text in bbl.values():
            new = (
                bib.parse_biblatex_bbl(text)
                if "\\entry{" in text
                else bib.parse_bibitems(text, "bbl")
            )
            entries += new
        sources.append("bbl")
    seen, unique = set(), []
    for e in entries:  # a key defined twice in one version: keep the first
        if e["key"] not in seen:
            seen.add(e["key"])
            unique.append(e)

    # Hierarchy: normalize math, drop formatting and the bibliography, then build the tree
    body = latex.normalize_math(body)
    body = re.sub(
        r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", " ", body, flags=re.DOTALL
    )
    body = re.sub(
        r"\\(?:bibliography|printbibliography|addbibresource)\b(\[[^\]]*\])?(\{[^}]*\})?", " ", body
    )
    body = latex.cleanup(body)
    nodes = structure.build(body, f"{title} (v{version})")

    tex_files = [r for r in tex]
    info = {
        "status": "ok",
        "root_file": root,
        "n_tex": len(tex_files),
        "n_used": sum(1 for r in used if r.lower().endswith(".tex")),
        "n_unused": len(set(tex_files) - set(used)),
        "bib_sources": ",".join(sorted(set(sources))) or None,
        "n_entries": len(unique),
        "has_appendix": int(bool(re.search(r"\\appendix\b|\\begin\{appendices\}", body))),
    }
    return info, nodes, unique, keys


# ---------------------------------------------------------------- deduplication


def _norm_title(title):
    t = re.sub(r"[^a-z0-9]", "", (title or "").lower())
    return t if len(t) >= 12 else None


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def dedup_references(per_version):
    """per_version: {version: [entry, ...]} -> (unified entries, {version: {old_key: new_key}})."""
    uf = _UnionFind()
    items = [(v, i, e) for v, es in per_version.items() for i, e in enumerate(es)]
    for v, i, e in items:
        node = ("entry", v, i)
        uf.union(node, ("key", e["key"]))
        if e["doi"]:
            uf.union(node, ("doi", e["doi"].lower()))
        if (t := _norm_title(e["title"])) is not None:
            uf.union(node, ("title", t))
    clusters = {}
    for v, i, e in items:
        clusters.setdefault(uf.find(("entry", v, i)), []).append((v, e))
    unified, rename = [], {v: {} for v in per_version}
    for members in clusters.values():
        members.sort(key=lambda m: m[0], reverse=True)  # latest version first
        canonical = members[0][1]["key"]
        merged = {"key": canonical}
        for field in ("entry_type", "title", "authors", "year", "doi", "journal", "url"):
            merged[field] = next((e[field] for _, e in members if e[field]), None)
        merged["authors"] = merged["authors"] or []
        unified.append(merged)
        for v, e in members:
            rename[v][e["key"]] = canonical
    return unified, rename


_CITE_KEYS = re.compile(r"(\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{)([^}]*)(\})")


def rename_cites(text, mapping):
    if not mapping or "cite" not in text:
        return text

    def repl(m):
        keys = [mapping.get(k.strip(), k.strip()) for k in m.group(2).split(",")]
        return m.group(1) + ",".join(dict.fromkeys(keys)) + m.group(3)

    return _CITE_KEYS.sub(repl, text)


# ---------------------------------------------------------------- one paper


def parse_paper(task):
    """Worker entry point: task = (arxiv_id, [(version, crawl_status), ...])."""
    arxiv_id, versions = task
    t0 = time.perf_counter()
    infos, trees, entries = {}, {}, {}
    for version, crawl_status in versions:
        if crawl_status != "ok":
            infos[version] = {"status": "empty"}  # no TeX source: recorded, no elements
            continue
        try:
            info, nodes, refs, _ = parse_version(arxiv_id, version)
        except Exception as exc:  # noqa: BLE001 - a broken version must not stop the paper
            info, nodes, refs = (
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]},
                None,
                [],
            )
        infos[version] = info
        if nodes:
            trees[version], entries[version] = nodes, refs

    unified, rename = dedup_references(entries)
    folder = ranges.folder_name(arxiv_id)
    ids, counters, elements, edges = {}, {}, [], []
    n_nodes = 0
    for version in sorted(trees):
        nodes, local = trees[version], []
        n_nodes += len(nodes)
        for kind, content, parent in nodes:
            content = rename_cites(content, rename.get(version))
            key = (kind, content if kind != "document" else f"{content}#{version}")
            eid = ids.get(key)
            if eid is None:
                prefix = PREFIX[kind]
                counters[prefix] = counters.get(prefix, 0) + 1
                eid = ids[key] = f"{folder}#{prefix}{counters[prefix]}"
                elements.append((eid, kind, content))
            local.append(eid)
        seen = set()
        depth = [0] * len(nodes)
        for idx, (kind, _, parent) in enumerate(nodes):
            pid = local[idx] if parent is None else local[parent]
            depth[idx] = 0 if parent is None else depth[parent] + 1
            edge = (version, local[idx], pid)
            if edge not in seen:
                seen.add(edge)
                edges.append(edge)
        kinds = [n[0] for n in nodes]
        infos[version].update(
            n_nodes=len(nodes),
            n_headings=kinds.count("heading"),
            n_sentences=kinds.count("sentence"),
            n_formulas=kinds.count("formula"),
            n_figures=kinds.count("figure"),
            n_lists=kinds.count("list"),
            n_items=kinds.count("item"),
            max_depth=max(depth),
        )

    out = parsed_dir() / f"{folder}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "arxiv_id": arxiv_id,
        "elements": elements,
        "hierarchy": edges,
        "bibtex": unified,
    }
    out.write_bytes(
        gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), compresslevel=6)
    )
    n_parsed = sum(1 for i in infos.values() if i["status"] == "ok")
    paper = {
        "status": "ok"
        if n_parsed
        else ("empty" if all(i["status"] == "empty" for i in infos.values()) else "failed"),
        "n_versions": len(versions),
        "n_versions_parsed": n_parsed,
        "n_nodes": n_nodes,
        "n_elements": len(elements),
        "n_entries_raw": sum(len(e) for e in entries.values()),
        "n_entries": len(unified),
        "bytes_out": out.stat().st_size,
        "duration_s": time.perf_counter() - t0,
    }
    return arxiv_id, paper, infos


# ---------------------------------------------------------------- run


def tasks(conn, member=None, force=False):
    member_filter, params = ("AND p.member = ?", (member,)) if member else ("", ())
    done = (
        ""
        if force
        else "AND p.arxiv_id NOT IN (SELECT arxiv_id FROM parse_papers WHERE status != 'failed')"
    )
    rows = conn.execute(
        "SELECT p.arxiv_id, v.version, v.status FROM papers p JOIN versions v USING (arxiv_id)"
        f" WHERE p.status = 'ok' {member_filter} {done} ORDER BY p.arxiv_id, v.version",
        params,
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["arxiv_id"], []).append((r["version"], r["status"]))
    return list(out.items())


def _save(conn, arxiv_id, paper, infos):
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO parse_papers (arxiv_id, status, n_versions, n_versions_parsed,"
        " n_nodes, n_elements, n_entries_raw, n_entries, bytes_out, duration_s, parsed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            arxiv_id,
            paper["status"],
            paper["n_versions"],
            paper["n_versions_parsed"],
            paper["n_nodes"],
            paper["n_elements"],
            paper["n_entries_raw"],
            paper["n_entries"],
            paper["bytes_out"],
            paper["duration_s"],
            now,
        ),
    )
    cols = (
        "status",
        "error",
        "root_file",
        "n_tex",
        "n_used",
        "n_unused",
        "n_nodes",
        "n_headings",
        "n_sentences",
        "n_formulas",
        "n_figures",
        "n_lists",
        "n_items",
        "max_depth",
        "bib_sources",
        "n_entries",
        "has_appendix",
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO parse_versions (arxiv_id, version, {', '.join(cols)})"
        f" VALUES (?, ?, {', '.join('?' * len(cols))})",
        [(arxiv_id, v, *(info.get(c) for c in cols)) for v, info in infos.items()],
    )


def run(conn, rm, member=None, workers=None, force=False, limit=None):
    todo = tasks(conn, member, force)[:limit]
    workers = workers or mp.cpu_count()
    print(f"[parse] {len(todo)} papers, {workers} workers", flush=True)
    started, n = time.time(), 0
    with mp.get_context("fork").Pool(workers) as pool:
        for arxiv_id, paper, infos in pool.imap_unordered(parse_paper, todo, chunksize=4):
            _save(conn, arxiv_id, paper, infos)
            rm.record("parse", arxiv_id, paper["duration_s"], paper["status"] != "failed")
            n += 1
            if n % 500 == 0:
                conn.commit()
                rate = n / (time.time() - started)
                print(f"[parse] {n}/{len(todo)} papers ({rate:.1f}/s)", flush=True)
    conn.commit()
