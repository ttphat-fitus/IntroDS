"""Statistics of the Milestone 2 parse, written as small files for the Jupyter Book:
summary.json, versions.parquet, papers.parquet, resources.parquet, runs.parquet, example.json."""

import collections
import gzip
import json
import re
from pathlib import Path

import pandas as pd

from . import config, parser
from .metrics import dir_size


def _scan_parsed(parsed_dir):
    """Element kinds after deduplication and heading titles, from parsed/*.json.gz."""
    kinds, acknowledgements = collections.Counter(), 0
    for f in parsed_dir.glob("*.json.gz"):
        payload = json.loads(gzip.decompress(f.read_bytes()))
        kinds.update(k for _, k, _ in payload["elements"])
        acknowledgements += any(
            k == "heading" and re.search(r"acknowledg", c, re.IGNORECASE)
            for _, k, c in payload["elements"]
        )
    return kinds, acknowledgements


def _example(parsed_dir, arxiv_id):
    """One paper's elements and per-version edges, for the interactive tree in the report."""
    path = parsed_dir / f"{arxiv_id.replace('.', '-')}.json.gz"
    if not path.exists():
        return None
    payload = json.loads(gzip.decompress(path.read_bytes()))
    return {
        "arxiv_id": arxiv_id,
        "elements": {e: [k, c] for e, k, c in payload["elements"]},
        "hierarchy": payload["hierarchy"],
        "bibtex": payload["bibtex"][:20],
    }


def write(conn, out_dir, example_id=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    versions = pd.read_sql_query(
        "SELECT pv.*, p.member, v.status AS crawl_status FROM parse_versions pv"
        " JOIN papers p USING (arxiv_id) JOIN versions v USING (arxiv_id, version)",
        conn,
    )
    papers = pd.read_sql_query(
        "SELECT pp.*, p.member FROM parse_papers pp JOIN papers p USING (arxiv_id)", conn
    )
    runs = pd.read_sql_query("SELECT * FROM runs WHERE command = 'parse'", conn)
    samples = pd.read_sql_query("SELECT * FROM resource_samples", conn)
    samples = samples[samples.run_id.isin(runs.run_id)]
    last_sample = samples.groupby("run_id").ts.max()
    runs = runs.assign(ended_at=runs.ended_at.fillna(runs.run_id.map(last_sample)))

    parsed_dir = parser.parsed_dir()
    kinds_after, ack = _scan_parsed(parsed_dir)
    with_tex = versions[versions.crawl_status == "ok"]
    ok = versions[versions.status == "ok"]
    papers_with_tex = papers[papers.n_versions_parsed + (papers.status == "failed") > 0]
    coverage = papers.n_versions_parsed / papers.n_versions.where(papers.n_versions > 0)
    kinds_before = {
        "heading": int(ok.n_headings.sum()),
        "sentence": int(ok.n_sentences.sum()),
        "formula": int(ok.n_formulas.sum()),
        "figure": int(ok.n_figures.sum()),
        "list": int(ok.n_lists.sum()),
        "item": int(ok.n_items.fillna(0).sum()),
        "document": len(ok),
    }
    wall = float((runs.ended_at - runs.started_at).sum())
    m2_tables = config.EXPORT_DIR / "data"
    summary = {
        "papers": len(papers),
        "papers_with_parsed_version": int((papers.n_versions_parsed > 0).sum()),
        "versions_total": len(versions),
        "versions_with_tex": len(with_tex),
        "versions_parsed": len(ok),
        "versions_failed": int((versions.status == "failed").sum()),
        "parse_success_rate": float(len(ok) / max(len(with_tex), 1)),
        "papers_full_version_coverage": int((coverage == 1).sum()),
        "mean_version_coverage": float(coverage.mean()),
        "nodes_before_dedup": int(papers.n_nodes.sum()),
        "elements_after_dedup": int(papers.n_elements.sum()),
        "kinds_before_dedup": kinds_before,
        "kinds_after_dedup": dict(kinds_after),
        "entries_before_dedup": int(papers.n_entries_raw.sum()),
        "entries_after_dedup": int(papers.n_entries.sum()),
        "versions_multi_file": int((ok.n_tex > 1).sum()),
        "versions_with_unused_tex": int((ok.n_unused > 0).sum()),
        "unused_tex_files": int(ok.n_unused.sum()),
        "bib_sources": ok.bib_sources.fillna("none").value_counts().to_dict(),
        "versions_with_appendix": int(ok.has_appendix.fillna(0).sum()),
        "papers_with_acknowledgements": int(ack),
        "max_depth_distribution": ok.max_depth.value_counts().sort_index().to_dict(),
        "time_wall_total_s": wall,
        "time_per_paper_avg_s": float(papers.duration_s.mean()),
        "time_wall_per_paper_s": wall / max(len(papers_with_tex), 1),
        "ram_peak_bytes": int(samples.rss_bytes.max()) if len(samples) else None,
        "ram_avg_bytes": float(samples.rss_bytes.mean()) if len(samples) else None,
        "output_parsed_bytes": dir_size(parsed_dir),
        "output_tables_bytes": sum(
            dir_size(m2_tables / t)
            for t in ("elements", "hierarchy", "bibtex")
            if (m2_tables / t).exists()
        ),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    versions.to_parquet(out / "versions.parquet", index=False)
    papers.to_parquet(out / "papers.parquet", index=False)
    step = max(1, len(samples) // 5000)
    samples.iloc[::step].to_parquet(out / "resources.parquet", index=False)
    runs.to_parquet(out / "runs.parquet", index=False)
    if example_id is None:  # a multi-version paper of moderate size makes a readable example
        cand = papers[(papers.n_versions_parsed >= 2) & papers.n_elements.between(150, 400)]
        example_id = cand.arxiv_id.iloc[0] if len(cand) else papers.arxiv_id.iloc[0]
    example = _example(parsed_dir, example_id)
    if example:
        (out / "example.json").write_text(json.dumps(example, ensure_ascii=False))
    return summary
