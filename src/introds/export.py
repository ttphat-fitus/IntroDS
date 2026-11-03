"""Export the Milestone 1 tables (papers, references) and the per-paper metadata files.

Parquet goes to EXPORT_DIR/data/<table>/<table>-NNNNN-of-NNNNN.parquet (Hugging Face layout).
Each paper folder under RAW_DIR also gets metadata.json and references.json, following the
data organisation suggested by the spec.
"""

import gzip
import json
import math

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config, ranges

ROWS_PER_SHARD = 100_000
NON_VENUES = {"", "arxiv.org", "arxiv"}

SCHEMAS = {
    "papers": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            ("title", pa.string()),
            ("authors", pa.list_(pa.string())),
            ("submission_date", pa.string()),
            ("revised_dates", pa.list_(pa.string())),
            ("venue", pa.string()),
        ]
    ),
    "references": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("ref_arxiv_id", pa.string(), nullable=False),
            ("ref_title", pa.string()),
            ("ref_authors", pa.list_(pa.string())),
            ("ref_submission_date", pa.string()),
            ("ref_s2_id", pa.string()),
        ]
    ),
}


_DICT = pa.dictionary(pa.int32(), pa.string())
SCHEMAS_M2 = {
    "elements": pa.schema(
        [
            pa.field("element_id", pa.string(), nullable=False),
            pa.field("arxiv_id", pa.string(), nullable=False),
            ("kind", _DICT),
            ("content", pa.string()),
        ]
    ),
    "hierarchy": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            ("version", pa.int32()),
            pa.field("element_id", pa.string(), nullable=False),
            pa.field("parent_id", pa.string(), nullable=False),
        ]
    ),
    "bibtex": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("citation_key", pa.string(), nullable=False),
            ("entry_type", _DICT),
            ("title", pa.string()),
            ("authors", pa.list_(pa.string())),
            ("year", pa.int32()),
            ("doi", pa.string()),
            ("journal", pa.string()),
            ("url", pa.string()),
        ]
    ),
}
M2_ROWS_PER_SHARD = {"elements": 500_000, "hierarchy": 1_000_000, "bibtex": 200_000}


def _venue(journal_ref, s2_venue):
    if journal_ref:
        return journal_ref
    if s2_venue and s2_venue.strip().lower() not in NON_VENUES:
        return s2_venue
    return None


def papers_frame(conn):
    papers = pd.read_sql_query(
        "SELECT p.arxiv_id, p.title, p.authors_json, p.submission_date, p.journal_ref,"
        " s.venue AS s2_venue FROM papers p LEFT JOIN s2_papers s USING (arxiv_id)"
        " WHERE p.status = 'ok' ORDER BY p.arxiv_id",
        conn,
    )
    revised = (
        pd.read_sql_query(
            "SELECT arxiv_id, version, version_date FROM versions WHERE version > 1"
            " ORDER BY arxiv_id, version",
            conn,
        )
        .groupby("arxiv_id")["version_date"]
        .agg(lambda s: [d for d in s if d])
    )
    return pd.DataFrame(
        {
            "arxiv_id": papers.arxiv_id,
            "title": papers.title,
            "authors": papers.authors_json.map(json.loads),
            "submission_date": papers.submission_date,
            "revised_dates": papers.arxiv_id.map(revised).map(
                lambda x: x if isinstance(x, list) else []
            ),
            "venue": [_venue(j, s) for j, s in zip(papers.journal_ref, papers.s2_venue)],
        }
    )


def references_frame(conn):
    refs = pd.read_sql_query(
        "SELECT arxiv_id, ref_arxiv_id, ref_title, ref_authors_json, ref_publication_date,"
        " ref_year, ref_s2_id FROM s2_references r"
        " WHERE ref_arxiv_id IS NOT NULL"
        " AND arxiv_id IN (SELECT arxiv_id FROM papers WHERE status = 'ok')"
        " ORDER BY arxiv_id, ref_idx",
        conn,
    ).drop_duplicates(["arxiv_id", "ref_arxiv_id"])
    date = refs.ref_publication_date.where(
        refs.ref_publication_date.notna(),
        refs.ref_year.map(lambda y: None if pd.isna(y) else str(int(y))),
    )
    return pd.DataFrame(
        {
            "arxiv_id": refs.arxiv_id,
            "ref_arxiv_id": refs.ref_arxiv_id,
            "ref_title": refs.ref_title,
            "ref_authors": refs.ref_authors_json.map(json.loads),
            "ref_submission_date": date,
            "ref_s2_id": refs.ref_s2_id,
        }
    )


def write_table(name, frame, out_dir):
    table_dir = out_dir / "data" / name
    table_dir.mkdir(parents=True, exist_ok=True)
    for old in table_dir.glob("*.parquet"):
        old.unlink()
    shards = max(1, math.ceil(len(frame) / ROWS_PER_SHARD))
    for i in range(shards):
        part = frame.iloc[i * ROWS_PER_SHARD : (i + 1) * ROWS_PER_SHARD]
        table = pa.Table.from_pandas(part, schema=SCHEMAS[name], preserve_index=False)
        pq.write_table(table, table_dir / f"{name}-{i:05d}-of-{shards:05d}.parquet")
    return shards


def write_paper_files(conn, papers):
    """metadata.json (paper + versions) and references.json (all S2 references) per paper."""
    versions = pd.read_sql_query(
        "SELECT arxiv_id, version, version_date, status, source_format FROM versions", conn
    )
    by_paper = {k: g.drop(columns="arxiv_id") for k, g in versions.groupby("arxiv_id")}
    for paper in papers.to_dict("records"):
        folder = config.RAW_DIR / ranges.folder_name(paper["arxiv_id"])
        folder.mkdir(parents=True, exist_ok=True)
        paper = {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in paper.items()}
        meta = dict(paper, versions=by_paper[paper["arxiv_id"]].to_dict("records"))
        (folder / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        refs = conn.execute(
            "SELECT ref_s2_id, ref_arxiv_id, ref_title, ref_authors_json, ref_year,"
            " ref_publication_date, external_ids_json FROM s2_references"
            " WHERE arxiv_id = ? ORDER BY ref_idx",
            (paper["arxiv_id"],),
        )
        out = [
            {
                "title": r["ref_title"],
                "authors": json.loads(r["ref_authors_json"]),
                "submission_date": r["ref_publication_date"] or r["ref_year"],
                "arxiv_id": r["ref_arxiv_id"],
                "s2_id": r["ref_s2_id"],
                "external_ids": json.loads(r["external_ids_json"]),
            }
            for r in refs
        ]
        (folder / "references.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


def _m2_rows(payload):
    aid = payload["arxiv_id"]
    yield (
        "elements",
        [
            {"element_id": e, "arxiv_id": aid, "kind": k, "content": c}
            for e, k, c in payload["elements"]
        ],
    )
    yield (
        "hierarchy",
        [
            {"arxiv_id": aid, "version": v, "element_id": e, "parent_id": p}
            for v, e, p in payload["hierarchy"]
        ],
    )
    yield (
        "bibtex",
        [
            {
                "arxiv_id": aid,
                "citation_key": b["key"],
                "entry_type": b["entry_type"],
                "title": b["title"],
                "authors": b["authors"],
                "year": b["year"],
                "doi": b["doi"],
                "journal": b["journal"],
                "url": b["url"],
            }
            for b in payload["bibtex"]
        ],
    )


def run_parsed(parsed_dir, out_dir=None):
    """Milestone 2 tables from parsed/*.json.gz, streamed into Parquet shards."""
    out_dir = out_dir or config.EXPORT_DIR
    buffers, shards, counts = {t: [] for t in SCHEMAS_M2}, {t: [] for t in SCHEMAS_M2}, {}
    dirs = {}
    for name in SCHEMAS_M2:
        dirs[name] = out_dir / "data" / name
        dirs[name].mkdir(parents=True, exist_ok=True)
        for old in dirs[name].glob("*.parquet"):
            old.unlink()

    def flush(name):
        rows = buffers[name]
        if not rows:
            return
        path = dirs[name] / f"part-{len(shards[name]):05d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS_M2[name]), path)
        shards[name].append(path)
        counts[name] = counts.get(name, 0) + len(rows)
        buffers[name] = []

    for f in sorted(parsed_dir.glob("*.json.gz")):
        payload = json.loads(gzip.decompress(f.read_bytes()))
        for name, rows in _m2_rows(payload):
            buffers[name].extend(rows)
            if len(buffers[name]) >= M2_ROWS_PER_SHARD[name]:
                flush(name)
    result = {}
    for name in SCHEMAS_M2:
        flush(name)
        total = len(shards[name])
        for i, path in enumerate(shards[name]):  # final names: <table>-00000-of-00007.parquet
            path.rename(dirs[name] / f"{name}-{i:05d}-of-{total:05d}.parquet")
        result[name] = (counts.get(name, 0), total)
    return result


def run(conn, out_dir=None):
    out_dir = out_dir or config.EXPORT_DIR
    papers = papers_frame(conn)
    references = references_frame(conn)
    write_paper_files(conn, papers)
    return {
        "papers": (len(papers), write_table("papers", papers, out_dir)),
        "references": (len(references), write_table("references", references, out_dir)),
    }
