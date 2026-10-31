"""Fetch additional files for versions that are already crawled, without touching their TeX.

Used for `.bbl` bibliographies: many submissions ship the compiled `.bbl` instead of the `.bib`,
so versions that have a `.bbl` in their archive but no `.bib` are downloaded again and only their
`.bbl` files are added next to the existing `.tex` / `.bib` files.
"""

import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

from . import config, http, sources
from .ratelimit import RateLimiter


def pending_bbl(conn, member=None):
    member_filter, params = ("AND p.member = ?", (member,)) if member else ("", ())
    return conn.execute(
        "SELECT v.arxiv_id, v.version FROM versions v JOIN papers p USING (arxiv_id)"
        " LEFT JOIN extra_fetch e ON e.arxiv_id = v.arxiv_id AND e.version = v.version"
        "  AND e.kind = 'bbl'"
        " WHERE v.status = 'ok' AND v.n_bbl > 0 AND v.n_bib = 0"
        f" {member_filter}"
        " AND (e.status IS NULL OR (e.status = 'failed' AND e.attempts < ?))"
        " ORDER BY v.arxiv_id, v.version",
        (*params, config.MAX_ATTEMPTS),
    ).fetchall()


def _fetch_bbl(sess, limiter, arxiv_id, version, stage):
    url = f"{config.ARXIV_SRC_URL}/{arxiv_id}v{version}"
    with tempfile.SpooledTemporaryFile(max_size=sources.SPOOL_MAX) as spool:
        status, reason, _ = sources._download(sess, limiter, url, stage, spool)
        if status == 404:
            return "missing", [], reason
        if status != 200:
            return "failed", [], f"HTTP {status} {reason}"
        spool.seek(0)
        _, members, _, _, _ = sources._classify(spool, {".bbl"})
    files = sources._write(arxiv_id, version, members, clear=False)
    return ("ok" if files else "none"), files, None


def snapshot(conn, dest, since):
    """Write the .bbl files fetched after `since` as a tar shard, plus a database snapshot."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = conn.execute(
        "SELECT f.arxiv_id, f.version, f.rel_path FROM files f JOIN extra_fetch e"
        " ON e.arxiv_id = f.arxiv_id AND e.version = f.version AND e.kind = 'bbl'"
        " WHERE f.kind = 'bbl' AND e.fetched_at > ? AND e.fetched_at <= ?",
        (since, now),
    ).fetchall()
    if rows:
        shard = dest / f"bbl-{int(now)}.tar"
        with tarfile.open(shard.with_suffix(".tmp"), "w") as tar:
            for arxiv_id, version, rel in rows:
                path = sources.version_dir(arxiv_id, version) / rel
                arcname = path.relative_to(config.RAW_DIR).as_posix()
                tar.add(path, arcname=arcname)
        shard.with_suffix(".tmp").rename(shard)
    with sqlite3.connect(dest / "crawl.sqlite.tmp") as snap:
        conn.backup(snap)
    (dest / "crawl.sqlite.tmp").rename(dest / "crawl.sqlite")
    return now


def run_bbl(conn, rm, member=None, stop=None, backup_dir=None, backup_every=300):
    sess = http.session()
    limiter = RateLimiter(config.ARXIV_DELAY)
    since, done = 0.0, 0
    while todo := pending_bbl(conn, member):
        for row in todo:
            if stop is not None and stop.is_set():
                return
            arxiv_id, version = row["arxiv_id"], row["version"]
            with rm.stage("bbl", arxiv_id, version) as stage:
                try:
                    status, files, error = _fetch_bbl(sess, limiter, arxiv_id, version, stage)
                except Exception as exc:  # noqa: BLE001 - one bad archive must not stop the run
                    status, files, error = "failed", [], f"{type(exc).__name__}: {exc}"[:500]
                stage.ok = status != "failed"
            conn.executemany("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)", files)
            conn.execute(
                "INSERT INTO extra_fetch (arxiv_id, version, kind, status, n_files, attempts,"
                " error, fetched_at) VALUES (?, ?, 'bbl', ?, ?, 1, ?, ?)"
                " ON CONFLICT (arxiv_id, version, kind) DO UPDATE SET status = excluded.status,"
                " n_files = excluded.n_files, attempts = attempts + 1, error = excluded.error,"
                " fetched_at = excluded.fetched_at",
                (arxiv_id, version, status, len(files), error, time.time()),
            )
            conn.commit()
            done += 1
            if backup_dir and done % backup_every == 0:
                since = snapshot(conn, backup_dir, since)
    if backup_dir:
        snapshot(conn, backup_dir, since)
