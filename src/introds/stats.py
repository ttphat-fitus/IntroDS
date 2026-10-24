"""Corpus statistics and performance numbers for the Milestone 1 report.

Writes small files that the Jupyter Book reads at build time:
summary.json, papers.parquet (one row per paper), resources.parquet, runs.parquet.
"""

import json
from pathlib import Path

import pandas as pd

from . import config
from .metrics import dir_size

CRAWL_COMMANDS = ("discover", "fetch-src", "fetch-refs", "crawl")


def _per_paper(conn, member_filter, params):
    papers = pd.read_sql_query(
        "SELECT p.arxiv_id, p.member, p.n_versions, p.categories,"
        " SUM(v.status IN ('ok', 'no_tex', 'missing')) AS versions_fetched,"
        " SUM(v.status = 'ok') AS versions_with_tex,"
        " SUM(v.status = 'failed') AS versions_failed,"
        " SUM(v.bytes_download) AS bytes_download,"
        " SUM(v.bytes_unpacked) AS bytes_before,"
        " SUM(v.bytes_kept) AS bytes_after,"
        " SUM(v.n_bbl > 0) AS versions_with_bbl,"
        " SUM(v.origin = 's3') AS versions_s3,"
        " s.status AS s2_status, s.n_refs_total, s.n_refs_arxiv"
        " FROM papers p JOIN versions v USING (arxiv_id)"
        " LEFT JOIN s2_papers s USING (arxiv_id)"
        f" WHERE p.status = 'ok' {member_filter}"
        " GROUP BY p.arxiv_id",
        conn,
        params=params,
    )
    papers["success"] = papers["versions_fetched"] == papers["n_versions"]

    # Time per paper: its own source downloads + its share of each batched stage
    timings = pd.read_sql_query("SELECT * FROM timings", conn)
    src = timings[timings.stage == "src"].groupby("arxiv_id")["duration_s"].sum()
    batched = timings[timings.stage.isin(["discover", "refs"])]
    share = {
        stage: (g.duration_s.sum() / max(g.n_items.sum(), 1))
        for stage, g in batched.groupby("stage")
    }
    # S3 tars hold other papers too, so their time is shared per version actually filled
    s3_time = timings[timings.stage == "s3"].duration_s.sum()
    share["s3_per_version"] = s3_time / max(papers.versions_s3.fillna(0).sum(), 1)
    papers["time_src_s"] = papers["arxiv_id"].map(src).fillna(0.0)
    papers["time_total_s"] = (
        papers["time_src_s"]
        + papers.versions_s3.fillna(0) * share["s3_per_version"]
        + share.get("discover", 0.0)
        + share.get("refs", 0.0)
    )
    return papers, timings, share


def compute(conn, member=None):
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # so the .sqlite file size is the real size
    member_filter, params = ("AND p.member = ?", (member,)) if member else ("", ())
    assigned = conn.execute(
        f"SELECT COUNT(*) FROM papers p WHERE 1 = 1 {member_filter}", params
    ).fetchone()[0]
    papers, timings, share = _per_paper(conn, member_filter, params)
    versions = pd.read_sql_query(
        "SELECT v.* FROM versions v JOIN papers p USING (arxiv_id)"
        f" WHERE p.status = 'ok' {member_filter}",
        conn,
        params=params,
    )
    runs = pd.read_sql_query("SELECT * FROM runs", conn)
    runs = runs[runs.command.isin(CRAWL_COMMANDS)]
    samples = pd.read_sql_query("SELECT * FROM resource_samples", conn)
    samples = samples[samples.run_id.isin(runs.run_id)]
    # A run killed with its VM never records ended_at: use its last resource sample instead
    last_sample = samples.groupby("run_id").ts.max()
    runs = runs.assign(ended_at=runs.ended_at.fillna(runs.run_id.map(last_sample)))

    ok = papers[papers.success]
    s2_ok = papers[papers.s2_status == "ok"]
    summary = {
        "member": member or "all",
        "ids_assigned": int(assigned),
        "papers_found": len(papers),
        "papers_success": len(ok),
        "paper_success_rate": float(len(ok) / max(len(papers), 1)),
        "versions_total": len(versions),
        "versions_by_status": versions.status.value_counts().to_dict(),
        "versions_by_format": versions.source_format.value_counts().to_dict(),
        "versions_by_origin": versions.origin.fillna("export").value_counts().to_dict(),
        "versions_with_bbl": int((versions.n_bbl > 0).sum()),
        "avg_versions_per_paper": float(papers.n_versions.mean()),
        "avg_paper_bytes_download": float(ok.bytes_download.mean()),
        "avg_paper_bytes_before_figure_removal": float(ok.bytes_before.mean()),
        "avg_paper_bytes_after_figure_removal": float(ok.bytes_after.mean()),
        "avg_references_per_paper": float(s2_ok.n_refs_total.mean()),
        "avg_arxiv_references_per_paper": float(s2_ok.n_refs_arxiv.mean()),
        "reference_metadata_success_rate": float(len(s2_ok) / max(len(papers), 1)),
        "time_discovery_total_s": float(timings[timings.stage == "discover"].duration_s.sum()),
        "time_src_total_s": float(timings[timings.stage == "src"].duration_s.sum()),
        "time_refs_total_s": float(timings[timings.stage == "refs"].duration_s.sum()),
        "time_s3_total_s": float(timings[timings.stage == "s3"].duration_s.sum()),
        "time_rate_limit_wait_s": float(timings.wait_s.sum()),
        "time_per_paper_avg_s": float(papers.time_total_s.mean()),
        "time_wall_total_s": float((runs.ended_at - runs.started_at).sum()),
        "ram_peak_bytes": int(samples.rss_bytes.max()) if len(samples) else None,
        "ram_avg_bytes": float(samples.rss_bytes.mean()) if len(samples) else None,
        "disk_max_bytes": int(samples.disk_bytes.max()) if len(samples) else None,
        "output_raw_bytes": dir_size(config.RAW_DIR),
        "output_db_bytes": config.DB_PATH.stat().st_size,
        "batch_share_s": share,
    }
    return summary, papers, samples, runs


def write(conn, out_dir, member=None, max_samples=5000):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary, papers, samples, runs = compute(conn, member)
    step = max(1, len(samples) // max_samples)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    papers.to_parquet(out / "papers.parquet", index=False)
    samples.iloc[::step].to_parquet(out / "resources.parquet", index=False)
    runs.to_parquet(out / "runs.parquet", index=False)
    return summary
