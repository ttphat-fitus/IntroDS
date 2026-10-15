import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    command     TEXT NOT NULL,          -- discover | fetch-src | fetch-refs
    member      TEXT,
    host        TEXT,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    config_json TEXT
);

-- One row per ID in the assigned ranges, including IDs that do not exist
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id           TEXT PRIMARY KEY,
    member             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | not_found | failed
    title              TEXT,
    authors_json       TEXT,            -- JSON list[str]
    submission_date    TEXT,            -- ISO, date of v1
    revised_dates_json TEXT,            -- JSON list[str], dates of v2..vn
    venue              TEXT,            -- arXiv journal-ref or S2 venue
    n_versions         INTEGER,
    discovered_at      REAL
);

-- One row per version, including versions without TeX (status = no_tex)
CREATE TABLE IF NOT EXISTS versions (
    arxiv_id      TEXT NOT NULL REFERENCES papers(arxiv_id),
    version       INTEGER NOT NULL,
    version_date  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | no_tex | failed
    source_format TEXT,                 -- tar | gzip_tex | pdf | other
    http_status   INTEGER,
    bytes_raw     INTEGER,              -- downloaded size (before figure removal)
    bytes_kept    INTEGER,              -- total size of kept .tex + .bib
    n_tex         INTEGER,
    n_bib         INTEGER,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    fetched_at    REAL,
    PRIMARY KEY (arxiv_id, version)
);

-- Kept files; rel_path preserves the directory layout so M2 can resolve \\input
CREATE TABLE IF NOT EXISTS files (
    arxiv_id TEXT NOT NULL,
    version  INTEGER NOT NULL,
    rel_path TEXT NOT NULL,
    kind     TEXT NOT NULL,             -- tex | bib
    bytes    INTEGER NOT NULL,
    sha256   TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, version, rel_path)
);

CREATE TABLE IF NOT EXISTS s2_papers (
    arxiv_id     TEXT PRIMARY KEY REFERENCES papers(arxiv_id),
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | ok | not_found | failed
    s2_id        TEXT,
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

-- Performance measurements (see metrics.py)
CREATE TABLE IF NOT EXISTS timings (
    run_id     TEXT NOT NULL,
    stage      TEXT NOT NULL,           -- discover | src | refs
    arxiv_id   TEXT,
    version    INTEGER,
    started_at REAL NOT NULL,
    duration_s REAL NOT NULL,
    wait_s     REAL NOT NULL DEFAULT 0, -- rate-limit wait included in duration_s
    ok         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_samples (
    run_id     TEXT NOT NULL,
    ts         REAL NOT NULL,
    rss_bytes  INTEGER NOT NULL,        -- main process + child processes
    disk_bytes INTEGER NOT NULL         -- size of the data directory
);

CREATE INDEX IF NOT EXISTS idx_versions_status ON versions(status);
CREATE INDEX IF NOT EXISTS idx_s2_status ON s2_papers(status);
CREATE INDEX IF NOT EXISTS idx_timings_run ON timings(run_id, stage);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute(
        "PRAGMA journal_mode=WAL"
    )  # allow concurrent readers/writers across threads/processes
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
