"""Manual labelling support for Milestone 3: pick the papers to label, build a self-contained
labelling page and check the labels that come out of it.

A label says which crawled reference (`references.ref_arxiv_id`) a BibTeX entry of the same paper
corresponds to, or none. One JSON object per line:
    {"arxiv_id", "citation_key", "groundtruth_arxiv_id" (null = no reference), "method", "labeler"}
"""

import collections
import json
import random
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import publish

MIN_ENTRIES = 20  # labeled entries required per manually labeled paper (spec)
PAGE = Path(__file__).with_name("label.html")


def _read(src, table, ids=None):
    filters = [("arxiv_id", "in", ids)] if ids is not None else None
    files = sorted((Path(src) / "data" / table).glob("*.parquet"))
    return pa.concat_tables([pq.read_table(f, filters=filters) for f in files])


def eligible(src, member, min_refs=5, max_refs=150):
    """Papers of the member with enough BibTeX entries and a manageable candidate list."""
    entries = collections.Counter(_read(src, "bibtex")["arxiv_id"].to_pylist())
    refs = collections.Counter(_read(src, "references")["arxiv_id"].to_pylist())
    return sorted(
        a
        for a, n in entries.items()
        if n >= MIN_ENTRIES and min_refs <= refs[a] <= max_refs and publish.in_span(a, member)
    )


def prepare(src, member, out, papers=10, per_paper=25, seed=15):
    """Pick `papers` papers, sample `per_paper` entries of each, write tasks.json + label.html.
    The first picked paper goes to the test set, the second to validation, the rest to training."""
    pool = eligible(src, member)
    if len(pool) < papers:
        raise SystemExit(f"Only {len(pool)} eligible papers for {member}, need {papers}")
    rng = random.Random(f"{seed}-{member}")
    chosen = rng.sample(pool, papers)
    meta = {r["arxiv_id"]: r for r in _read(src, "papers", chosen).to_pylist()}
    entries, refs = collections.defaultdict(list), collections.defaultdict(dict)
    for row in _read(src, "bibtex", chosen).to_pylist():
        entries[row["arxiv_id"]].append(row)
    for row in _read(src, "references", chosen).to_pylist():
        refs[row["arxiv_id"]][row["ref_arxiv_id"]] = row
    tasks = {"member": member, "seed": seed, "min_entries": MIN_ENTRIES, "papers": []}
    for i, arxiv_id in enumerate(chosen):
        rows = sorted(entries[arxiv_id], key=lambda r: r["citation_key"])
        sample = sorted(
            rng.sample(rows, min(per_paper, len(rows))), key=lambda r: r["citation_key"]
        )
        tasks["papers"].append(
            {
                "arxiv_id": arxiv_id,
                "title": meta[arxiv_id]["title"],
                "partition": "test" if i == 0 else "valid" if i == 1 else "train",
                "entries": [
                    {k: r[k] for k in ("citation_key", "entry_type", "title", "authors", "year")}
                    | {k: r[k] for k in ("journal", "doi", "url")}
                    for r in sample
                ],
                "refs": [
                    {
                        k: r[k]
                        for k in ("ref_arxiv_id", "ref_title", "ref_authors", "ref_submission_date")
                    }
                    for _, r in sorted(refs[arxiv_id].items())
                ],
            }
        )
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False))
    payload = json.dumps(tasks, ensure_ascii=False).replace("</", "<\\/")
    (out / "label.html").write_text(PAGE.read_text().replace("__DATA__", payload))
    return tasks, len(pool)


def check(labels_path, tasks_path):
    """Validate a labels file against tasks.json; returns (problems, summary)."""
    tasks = json.loads(Path(tasks_path).read_text())
    papers = {p["arxiv_id"]: p for p in tasks["papers"]}
    seen, per_paper, problems, none = set(), collections.Counter(), [], 0
    for n, line in enumerate(Path(labels_path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        paper = papers.get(row.get("arxiv_id"))
        if paper is None:
            problems.append(f"line {n}: {row.get('arxiv_id')} is not one of the assigned papers")
            continue
        key = (row["arxiv_id"], row.get("citation_key"))
        if row.get("citation_key") not in {e["citation_key"] for e in paper["entries"]}:
            problems.append(f"line {n}: unknown entry {key}")
        if key in seen:
            problems.append(f"line {n}: duplicate label for {key}")
        seen.add(key)
        truth = row.get("groundtruth_arxiv_id")
        if truth is not None and truth not in {r["ref_arxiv_id"] for r in paper["refs"]}:
            problems.append(f"line {n}: {truth} is not a candidate reference of {row['arxiv_id']}")
        none += truth is None
        per_paper[row["arxiv_id"]] += 1
    for arxiv_id in papers:
        if per_paper[arxiv_id] < tasks["min_entries"]:
            problems.append(
                f"{arxiv_id}: {per_paper[arxiv_id]} labels, need {tasks['min_entries']}"
            )
    summary = {
        "member": tasks["member"],
        "papers": len(papers),
        "labels": len(seen),
        "no_match_share": round(none / max(len(seen), 1), 3),
        "per_paper": dict(per_paper),
    }
    return problems, summary
