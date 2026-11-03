"""SQLite holds crawl state (for resuming) and metadata; .tex/.bib files live on disk."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    command     TEXT NOT NULL,          -- discover | fetch-src | fetch-refs | crawl
    member      TEXT,
    host        TEXT,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    config_json TEXT
);

-- One row per ID in the assigned ranges, including IDs that do not exist
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id        TEXT PRIMARY KEY,
    member          TEXT NOT NULL,
    status          TEXT NOT NULL,      -- ok | not_found
    title           TEXT,
    authors_json    TEXT,               -- JSON list[str]
    submission_date TEXT,               -- ISO 8601, date of v1
    journal_ref     TEXT,               -- arXiv journal-ref, preferred venue
    categories      TEXT,               -- space-separated arXiv categories
    n_versions      INTEGER,
    discovered_at   REAL
);

-- One row per version, including versions without TeX (status = no_tex)
CREATE TABLE IF NOT EXISTS versions (
    arxiv_id       TEXT NOT NULL REFERENCES papers(arxiv_id),
    version        INTEGER NOT NULL,
    version_date   TEXT,                -- ISO 8601
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | no_tex | missing | failed
    source_format  TEXT,                -- tar | gzip | plain | pdf | other
    http_status    INTEGER,
    bytes_download INTEGER,             -- bytes received (compressed archive)
    bytes_unpacked INTEGER,             -- all files in the archive (before figure removal)
    bytes_kept     INTEGER,             -- kept files only (after figure removal)
    n_files        INTEGER,             -- regular files in the archive
    n_tex          INTEGER,
    n_bib          INTEGER,
    n_bbl          INTEGER,             -- counted even when .bbl files are not kept
    attempts       INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    fetched_at     REAL,
    origin         TEXT,                -- export | s3
    PRIMARY KEY (arxiv_id, version)
);

-- Kept files; rel_path preserves the directory layout so M2 can resolve \\input
CREATE TABLE IF NOT EXISTS files (
    arxiv_id TEXT NOT NULL,
    version  INTEGER NOT NULL,
    rel_path TEXT NOT NULL,
    kind     TEXT NOT NULL,             -- tex | bib | bbl
    bytes    INTEGER NOT NULL,
    sha256   TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, version, rel_path)
);

CREATE TABLE IF NOT EXISTS s2_papers (
    arxiv_id     TEXT PRIMARY KEY REFERENCES papers(arxiv_id),
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | ok | not_found | failed
    s2_id        TEXT,
    venue        TEXT,
    n_refs_total INTEGER,
    n_refs_arxiv INTEGER,
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    fetched_at   REAL
);

-- Keep EVERY crawled reference; the final references table only takes rows with ref_arxiv_id
CREATE TABLE IF NOT EXISTS s2_references (
    arxiv_id             TEXT NOT NULL,
    ref_idx              INTEGER NOT NULL,
    ref_s2_id            TEXT,
    ref_arxiv_id         TEXT,
    ref_title            TEXT,
    ref_authors_json     TEXT,
    ref_year             INTEGER,
    ref_publication_date TEXT,
    external_ids_json    TEXT,
    PRIMARY KEY (arxiv_id, ref_idx)
);

-- Files fetched after the main crawl, e.g. .bbl bibliographies for versions without a .bib
CREATE TABLE IF NOT EXISTS extra_fetch (
    arxiv_id   TEXT NOT NULL,
    version    INTEGER NOT NULL,
    kind       TEXT NOT NULL,           -- bbl
    status     TEXT NOT NULL,           -- ok | none (archive has no such file) | missing | failed
    n_files    INTEGER,
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    fetched_at REAL,
    PRIMARY KEY (arxiv_id, version, kind)
);

-- Milestone 2 parsing results (see parser.py); elements / hierarchy / bibtex live in parsed/*.json.gz
CREATE TABLE IF NOT EXISTS parse_papers (
    arxiv_id          TEXT PRIMARY KEY,
    status            TEXT NOT NULL,      -- ok | empty (no version has TeX) | failed
    n_versions        INTEGER,
    n_versions_parsed INTEGER,
    n_nodes           INTEGER,            -- tree nodes over all versions, before deduplication
    n_elements        INTEGER,            -- distinct elements after deduplication
    n_entries_raw     INTEGER,            -- bibliography entries over all versions
    n_entries         INTEGER,            -- unified entries after deduplication
    bytes_out         INTEGER,
    duration_s        REAL,
    parsed_at         REAL
);

CREATE TABLE IF NOT EXISTS parse_versions (
    arxiv_id    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    status      TEXT NOT NULL,            -- ok | empty | failed
    error       TEXT,
    root_file   TEXT,
    n_tex       INTEGER,                  -- .tex files in the archive
    n_used      INTEGER,                  -- .tex files on the compilation path
    n_unused    INTEGER,
    n_nodes     INTEGER,
    n_headings  INTEGER,
    n_sentences INTEGER,
    n_formulas  INTEGER,
    n_figures   INTEGER,
    n_lists     INTEGER,
    n_items     INTEGER,
    max_depth   INTEGER,
    bib_sources TEXT,                     -- bib, bibitem, bbl (comma separated)
    n_entries   INTEGER,
    has_appendix INTEGER,
    PRIMARY KEY (arxiv_id, version)
);

-- Performance measurements (see metrics.py)
CREATE TABLE IF NOT EXISTS timings (
    run_id     TEXT NOT NULL,
    stage      TEXT NOT NULL,           -- discover | src | refs
    arxiv_id   TEXT,                    -- NULL for batched stages
    version    INTEGER,
    n_items    INTEGER NOT NULL DEFAULT 1,  -- IDs covered by a batched stage
    started_at REAL NOT NULL,
    duration_s REAL NOT NULL,
    wait_s     REAL NOT NULL DEFAULT 0, -- rate-limit wait included in duration_s
    ok         INTEGER NOT NULL,
    http_log   TEXT                     -- status of every HTTP attempt, e.g. '429,429,200'
);

CREATE TABLE IF NOT EXISTS resource_samples (
    run_id     TEXT NOT NULL,
    ts         REAL NOT NULL,
    rss_bytes  INTEGER NOT NULL,        -- main process + child processes
    disk_bytes INTEGER NOT NULL         -- size of the data directory
);

CREATE INDEX IF NOT EXISTS idx_papers_member ON papers(member, status);
CREATE INDEX IF NOT EXISTS idx_versions_status ON versions(status);
CREATE INDEX IF NOT EXISTS idx_s2_status ON s2_papers(status);
CREATE INDEX IF NOT EXISTS idx_timings_run ON timings(run_id, stage);
"""

TABLES = [
    "runs",
    "papers",
    "versions",
    "files",
    "s2_papers",
    "s2_references",
    "extra_fetch",
    "timings",
    "resource_samples",
]


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent readers/writers across threads
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# Columns added after the first crawls; older databases get them on connect
MIGRATIONS = {
    "timings": {"http_log": "TEXT"},
    "versions": {"origin": "TEXT"},
    "parse_versions": {"has_appendix": "INTEGER", "n_items": "INTEGER"},
}


def _columns(conn, table, schema="main"):
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _migrate(conn):
    for table, columns in MIGRATIONS.items():
        existing = _columns(conn, table)
        for name, kind in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    conn.commit()


def merge(conn, other_path):
    """Copy every row of another member's database into this one (existing keys are kept)."""
    conn.execute("ATTACH DATABASE ? AS other", (str(other_path),))
    try:
        for table in TABLES:
            # Only shared columns: the other database may predate a migration
            other_cols = set(_columns(conn, table, "other"))
            if not other_cols:  # table created after the other database was made
                continue
            cols = ", ".join(c for c in _columns(conn, table) if c in other_cols)
            conn.execute(f"INSERT OR IGNORE INTO {table} ({cols}) SELECT {cols} FROM other.{table}")
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE other")
