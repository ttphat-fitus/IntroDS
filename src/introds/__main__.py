"""CLI: python -m introds <command>. Every command can resume after an interruption (driven by status columns in SQLite)."""

import argparse

from . import config, db, ranges


def cmd_init_db(args):
    conn = db.connect(config.DB_PATH)
    print(f"Schema created at {config.DB_PATH}")
    conn.close()


def cmd_spans(args):
    for span in ranges.spans(args.member):
        last = f"{span.last:05d}" if span.last is not None else "end of month"
        print(f"{span.member}  {span.yymm}  {span.first:05d} -> {last}")


def todo(args):
    raise SystemExit(f"Command '{args.command}' is not implemented yet")


def main():
    parser = argparse.ArgumentParser(prog="introds")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the SQLite schema").set_defaults(
        func=cmd_init_db
    )

    p = sub.add_parser("spans", help="print the assigned ID spans")
    p.add_argument("--member")
    p.set_defaults(func=cmd_spans)

    for name, help_ in [
        ("discover", "list versions + metadata (OAI-PMH arXivRaw)"),
        ("fetch-src", "download each version's source, keep only .tex/.bib"),
        ("fetch-refs", "fetch references from Semantic Scholar"),
        ("stats", "export small summary files to the book repo"),
        ("export", "export Parquet tables following the spec schemas"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--member")
        p.set_defaults(func=todo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
