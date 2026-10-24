"""CLI: python -m introds <command>. Every command can resume after an interruption."""

import argparse
import json
import threading
import time
from pathlib import Path

from . import backup, config, db, discover, export, ranges, refs, s3bulk, sources, stats
from .metrics import RunMetrics

MEMBERS = [a[0] for a in ranges.ASSIGNMENTS]


def _run_config(args):
    keys = ("member", "keep_bbl", "limit", "retry_not_found", "backup_dir", "s3")
    return {k: getattr(args, k, None) for k in keys} | {"s2_api_key": bool(config.S2_API_KEY)}


def _metrics(args):
    # A dedicated connection: metrics writes never share a transaction with crawl writes
    return RunMetrics(
        db.connect(config.DB_PATH),
        args.command,
        member=args.member,
        data_dir=config.DATA_DIR,
        config=_run_config(args),
    )


def cmd_init_db(args):
    db.connect(config.DB_PATH).close()
    print(f"Schema created at {config.DB_PATH}")


def cmd_spans(args):
    for span in ranges.spans(args.member):
        last = f"{span.last:05d}" if span.last is not None else "end of month"
        print(f"{span.member}  {span.yymm}  {span.first:05d} -> {last}")


def cmd_discover(args):
    conn = db.connect(config.DB_PATH)
    with _metrics(args) as rm:
        discover.run(conn, rm, args.member, limit=args.limit)
    _print_progress(conn, args.member)


def cmd_fetch_src(args):
    conn = db.connect(config.DB_PATH)
    with _metrics(args) as rm:
        sources.run(conn, rm, args.member, keep_bbl=args.keep_bbl)
    _print_progress(conn, args.member)


def cmd_fetch_s3(args):
    conn = db.connect(config.DB_PATH)
    with _metrics(args) as rm:
        s3bulk.run(conn, rm, args.member, keep_bbl=args.keep_bbl)
    _print_progress(conn, args.member)


def cmd_verify_s3(args):
    conn = db.connect(config.DB_PATH)
    results = s3bulk.verify(conn, args.sample, keep_bbl=args.keep_bbl)
    for arxiv_id, version, outcome in results:
        print(f"{arxiv_id}v{version}: {outcome}")
    print(f"{sum(o == 'match' for *_, o in results)}/{len(results)} match")


def cmd_fetch_refs(args):
    conn = db.connect(config.DB_PATH)
    with _metrics(args) as rm:
        refs.run(conn, rm, args.member, retry_not_found=args.retry_not_found)
    _print_progress(conn, args.member)


def _worker(name, target, errors, *args, **kwargs):
    """Run one crawl stage on its own SQLite connection; remember any crash for the main thread."""
    try:
        target(db.connect(config.DB_PATH), *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - re-raised by the main thread
        errors[name] = exc


def _sources(conn, rm, args, stop):
    """S3 bulk first (when enabled), then export.arxiv.org for every version still pending."""
    if args.s3:
        s3bulk.run(conn, rm, args.member, keep_bbl=args.keep_bbl, stop=stop)
    sources.run(conn, rm, args.member, args.keep_bbl, stop)


def _backup_loop(stop, dest, every):
    while not stop.wait(every):
        n = backup.backup(config.DB_PATH, dest)
        print(f"[backup] {time.strftime('%H:%M:%S')} +{n} versions -> {dest}", flush=True)


def cmd_crawl(args):
    """discover, then download sources (arXiv) and references (Semantic Scholar) concurrently."""
    conn = db.connect(config.DB_PATH)
    stop, errors = threading.Event(), {}
    with _metrics(args) as rm:
        discover.run(conn, rm, args.member, limit=args.limit)
        _print_progress(conn, args.member)
        workers = [
            threading.Thread(
                target=_worker,
                args=(
                    "src",
                    lambda c: _sources(c, rm, args, stop),
                    errors,
                ),
            ),
            threading.Thread(
                target=_worker,
                args=(
                    "refs",
                    lambda c: refs.run(c, rm, args.member, args.retry_not_found, stop),
                    errors,
                ),
            ),
        ]
        if args.backup_dir:
            workers.append(
                threading.Thread(
                    target=_backup_loop,
                    args=(stop, args.backup_dir, args.backup_every * 60),
                    daemon=True,
                )
            )
        for w in workers:
            w.start()
        try:
            while alive := [w for w in workers[:2] if w.is_alive()]:
                alive[0].join(timeout=args.progress_every * 60)
                _print_progress(conn, args.member)
        except KeyboardInterrupt:
            print("Stopping after the current item...", flush=True)
        stop.set()
        for w in workers[:2]:
            w.join()
    if args.backup_dir:
        backup.backup(config.DB_PATH, args.backup_dir)
    _print_progress(conn, args.member)
    if errors:
        raise SystemExit(f"Crawl stage failed: {errors}")


def cmd_stats(args):
    conn = db.connect(config.DB_PATH)
    summary = stats.write(conn, args.out, member=args.member)
    print(json.dumps(summary, indent=2, default=str))


def cmd_export(args):
    conn = db.connect(config.DB_PATH)
    for table, (rows, shards) in export.run(conn, args.out).items():
        print(f"{table}: {rows} rows in {shards} shard(s)")


def cmd_backup(args):
    print(f"{backup.backup(config.DB_PATH, args.dest)} versions added to {args.dest}")


def cmd_restore(args):
    missing = backup.restore(args.src)
    print(f"Restored {args.src} into {config.DATA_DIR} ({missing} versions reset to pending)")


def cmd_merge(args):
    conn = db.connect(config.DB_PATH)
    for path in args.sources:
        db.merge(conn, path)
        print(f"Merged {path}")


def _print_progress(conn, member):
    q = "SELECT t.status, COUNT(*) FROM {} t JOIN papers p USING (arxiv_id) WHERE p.member = ? GROUP BY 1"
    versions = dict(conn.execute(q.format("versions"), (member,)).fetchall())
    s2 = dict(conn.execute(q.format("s2_papers"), (member,)).fetchall())
    print(f"[{time.strftime('%H:%M:%S')}] versions {versions} | s2 {s2}", flush=True)


def main():
    parser = argparse.ArgumentParser(prog="introds")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_, member=False):
        p = sub.add_parser(name, help=help_)
        if member:
            p.add_argument("--member", required=True, choices=MEMBERS)
        p.set_defaults(func=func)
        return p

    add("init-db", cmd_init_db, "create the SQLite schema")
    p = add("spans", cmd_spans, "print the assigned ID spans")
    p.add_argument("--member", choices=MEMBERS)

    p = add("discover", cmd_discover, "resolve versions + metadata via the arXiv API", True)
    p.add_argument("--limit", type=int, help="max IDs per span (for tests)")
    p = add("fetch-src", cmd_fetch_src, "download sources, keep only .tex/.bib", True)
    p.add_argument("--keep-bbl", action="store_true", help="also keep .bbl files")
    p = add("fetch-s3", cmd_fetch_s3, "fill latest versions from the S3 bulk archive", True)
    p.add_argument("--keep-bbl", action="store_true", help="also keep .bbl files")
    p = add("verify-s3", cmd_verify_s3, "compare S3-filled versions with export.arxiv.org")
    p.add_argument("--sample", type=int, default=20)
    p.add_argument("--keep-bbl", action="store_true")
    p = add("fetch-refs", cmd_fetch_refs, "fetch references from Semantic Scholar", True)
    p.add_argument("--retry-not-found", action="store_true")

    p = add("crawl", cmd_crawl, "discover + fetch-src + fetch-refs (concurrently)", True)
    p.add_argument("--limit", type=int, help="max IDs per span (for tests)")
    p.add_argument("--keep-bbl", action="store_true", help="also keep .bbl files")
    p.add_argument("--retry-not-found", action="store_true")
    p.add_argument("--s3", action="store_true", help="fill latest versions from S3 bulk first")
    p.add_argument("--backup-dir", type=Path, help="write incremental backups here")
    p.add_argument("--backup-every", type=float, default=20, help="minutes between backups")
    p.add_argument("--progress-every", type=float, default=5, help="minutes between reports")

    p = add("stats", cmd_stats, "write report statistics for the Jupyter Book")
    p.add_argument("--member", choices=MEMBERS)
    p.add_argument("--out", type=Path, default=config.DATA_DIR / "stats")
    p = add("export", cmd_export, "write Parquet tables + per-paper metadata files")
    p.add_argument("--out", type=Path, default=config.EXPORT_DIR)
    p = add("backup", cmd_backup, "write an incremental backup")
    p.add_argument("dest", type=Path)
    p = add("restore", cmd_restore, "rebuild the data directory from a backup")
    p.add_argument("src", type=Path)
    p = add("merge", cmd_merge, "merge other members' databases into this one")
    p.add_argument("sources", type=Path, nargs="+")

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
