"""Incremental backups so a crawl survives the loss of the Colab VM.

Each backup writes a consistent SQLite snapshot plus a tar shard holding the version folders
fetched since the previous backup. restore() replays snapshot and shards into a data directory.
"""

import json
import sqlite3
import tarfile
import time
from pathlib import Path

from . import config, ranges
from .sources import version_dir


def backup(db_path, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    state_path = dest / "state.json"
    since = json.loads(state_path.read_text())["until"] if state_path.exists() else 0.0
    until = time.time()

    src = sqlite3.connect(db_path, timeout=60)
    try:
        rows = src.execute(
            "SELECT arxiv_id, version FROM versions WHERE fetched_at > ? AND fetched_at <= ?",
            (since, until),
        ).fetchall()
        if rows:
            shard = dest / f"raw-{int(until)}.tar"
            with tarfile.open(shard.with_suffix(".tmp"), "w") as tar:
                for arxiv_id, version in rows:
                    path = version_dir(arxiv_id, version)
                    if path.exists():
                        tar.add(path, arcname=f"{ranges.folder_name(arxiv_id)}/v{version}")
            shard.with_suffix(".tmp").rename(shard)
        snapshot = dest / "crawl.sqlite.tmp"
        with sqlite3.connect(snapshot) as snap:
            src.backup(snap)
        snapshot.rename(dest / "crawl.sqlite")
    finally:
        src.close()
    state_path.write_text(json.dumps({"until": until}))
    return len(rows)


def restore(src_dir, data_dir=None):
    """Rebuild a data directory from a backup directory (shards are applied oldest first)."""
    src_dir = Path(src_dir)
    data_dir = Path(data_dir or config.DATA_DIR)
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for shard in sorted(src_dir.glob("raw-*.tar")):
        with tarfile.open(shard) as tar:
            tar.extractall(raw_dir, filter="data")
    db_path = data_dir / "crawl.sqlite"
    db_path.write_bytes((src_dir / "crawl.sqlite").read_bytes())

    # The snapshot can be newer than the last shard: refetch versions whose files are missing
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT arxiv_id, version FROM versions WHERE status = 'ok'").fetchall()
        missing = [
            (a, v) for a, v in rows if not (raw_dir / ranges.folder_name(a) / f"v{v}").is_dir()
        ]
        conn.executemany(
            "UPDATE versions SET status = 'pending' WHERE arxiv_id = ? AND version = ?", missing
        )
    return len(missing)
