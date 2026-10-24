"""Entry discovery: resolve assigned IDs to their versions and metadata through the arXiv API.

Pass 1 queries unversioned IDs in batches; each result's short ID ends with the latest version
(e.g. 2601.08157v3), which gives the version count, the v1 date (published) and the latest
date (updated). Pass 2 queries versioned IDs (2601.08157v2) for the dates of middle versions.
"""

import json
import time

import arxiv

from . import config, ranges

BATCH = 100


def _client():
    return arxiv.Client(page_size=BATCH, delay_seconds=config.ARXIV_DELAY, num_retries=5)


def _fetch(client, ids):
    return list(client.results(arxiv.Search(id_list=ids, max_results=len(ids))))


def _split_version(short_id):
    base, _, version = short_id.rpartition("v")
    return base, int(version)


def _known(conn, ids):
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT arxiv_id, status FROM papers WHERE arxiv_id IN ({marks})", ids)
    return {r["arxiv_id"]: r["status"] for r in rows}


def _save_batch(conn, member, ids, results):
    now = time.time()
    found = set()
    for r in results:
        arxiv_id, n_versions = _split_version(r.get_short_id())
        found.add(arxiv_id)
        conn.execute(
            "INSERT OR REPLACE INTO papers (arxiv_id, member, status, title, authors_json,"
            " submission_date, journal_ref, categories, n_versions, discovered_at)"
            " VALUES (?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?)",
            (
                arxiv_id,
                member,
                " ".join(r.title.split()),
                json.dumps([a.name for a in r.authors], ensure_ascii=False),
                r.published.isoformat(),
                r.journal_ref,
                " ".join(r.categories),
                n_versions,
                now,
            ),
        )
        for version in range(1, n_versions + 1):
            conn.execute(
                "INSERT OR IGNORE INTO versions (arxiv_id, version) VALUES (?, ?)",
                (arxiv_id, version),
            )
        conn.execute(
            "UPDATE versions SET version_date = ? WHERE arxiv_id = ? AND version = 1",
            (r.published.isoformat(), arxiv_id),
        )
        conn.execute(
            "UPDATE versions SET version_date = ? WHERE arxiv_id = ? AND version = ?",
            (r.updated.isoformat(), arxiv_id, n_versions),
        )
    for arxiv_id in ids:
        if arxiv_id not in found:
            conn.execute(
                "INSERT OR REPLACE INTO papers (arxiv_id, member, status, discovered_at)"
                " VALUES (?, ?, 'not_found', ?)",
                (arxiv_id, member, now),
            )
    conn.commit()
    return len(found)


def _discover_span(conn, rm, client, span, limit):
    """Walk one span in batches. An open-ended span stops at the first batch with no paper."""
    number, done = span.first, 0
    while span.last is None or number <= span.last:
        high = number + BATCH - 1 if span.last is None else min(number + BATCH - 1, span.last)
        if limit is not None:
            high = min(high, number + (limit - done) - 1)
        ids = [ranges.arxiv_id(span.yymm, n) for n in range(number, high + 1)]
        known = _known(conn, ids)
        todo = [i for i in ids if i not in known]
        if todo:
            with rm.stage("discover", n_items=len(todo)):
                _save_batch(conn, span.member, todo, _fetch(client, todo))
            known = _known(conn, ids)
        done += len(ids)
        if span.last is None and all(s == "not_found" for s in known.values()):
            break
        if limit is not None and done >= limit:
            break
        number = high + 1
    return done


def _middle_version_dates(conn, rm, client, member):
    rows = conn.execute(
        "SELECT v.arxiv_id, v.version FROM versions v JOIN papers p USING (arxiv_id)"
        " WHERE p.member = ? AND v.version_date IS NULL",
        (member,),
    ).fetchall()
    wanted = [f"{r['arxiv_id']}v{r['version']}" for r in rows]
    for start in range(0, len(wanted), BATCH):
        batch = wanted[start : start + BATCH]
        with rm.stage("discover", n_items=len(batch)):
            results = _fetch(client, batch)
        for r in results:
            arxiv_id, version = _split_version(r.get_short_id())
            conn.execute(
                "UPDATE versions SET version_date = ? WHERE arxiv_id = ? AND version = ?",
                (r.updated.isoformat(), arxiv_id, version),
            )
        conn.commit()


def run(conn, rm, member, limit=None):
    """Discover every assigned ID of a member (resumable). limit caps IDs per span, for tests."""
    client = _client()
    for span in ranges.spans(member):
        _discover_span(conn, rm, client, span, limit)
    _middle_version_dates(conn, rm, client, member)
