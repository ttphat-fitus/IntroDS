"""Reference metadata from the Semantic Scholar Graph API (batch endpoint, BATCH papers per call)."""

import json
import time

from . import config, http
from .ratelimit import RateLimiter

BATCH = 100
REF_FIELDS = ("paperId", "title", "authors", "year", "publicationDate", "externalIds")
FIELDS = "title,venue,externalIds," + ",".join(f"references.{f}" for f in REF_FIELDS)


def _save_paper(conn, arxiv_id, paper):
    now = time.time()
    if paper is None:  # not indexed yet (new uploads can lag 1-7 days)
        conn.execute(
            "UPDATE s2_papers SET status = 'not_found', attempts = attempts + 1, fetched_at = ?"
            " WHERE arxiv_id = ?",
            (now, arxiv_id),
        )
        return
    refs = paper.get("references") or []
    conn.execute("DELETE FROM s2_references WHERE arxiv_id = ?", (arxiv_id,))
    rows = []
    for idx, ref in enumerate(refs):
        ext = ref.get("externalIds") or {}
        rows.append(
            (
                arxiv_id,
                idx,
                ref.get("paperId"),
                ext.get("ArXiv"),
                ref.get("title"),
                json.dumps([a.get("name") for a in ref.get("authors") or []], ensure_ascii=False),
                ref.get("year"),
                ref.get("publicationDate"),
                json.dumps(ext),
            )
        )
    conn.executemany("INSERT INTO s2_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute(
        "UPDATE s2_papers SET status = 'ok', s2_id = ?, venue = ?, n_refs_total = ?,"
        " n_refs_arxiv = ?, attempts = attempts + 1, error = NULL, fetched_at = ?"
        " WHERE arxiv_id = ?",
        (
            paper.get("paperId"),
            paper.get("venue") or None,
            len(rows),
            sum(r[3] is not None for r in rows),
            now,
            arxiv_id,
        ),
    )


def pending(conn, member, retry_not_found=False):
    conn.execute(
        "INSERT OR IGNORE INTO s2_papers (arxiv_id)"
        " SELECT arxiv_id FROM papers WHERE member = ? AND status = 'ok'",
        (member,),
    )
    conn.commit()
    statuses = "('pending', 'failed', 'not_found')" if retry_not_found else "('pending', 'failed')"
    return [
        r["arxiv_id"]
        for r in conn.execute(
            "SELECT s.arxiv_id FROM s2_papers s JOIN papers p USING (arxiv_id)"
            f" WHERE p.member = ? AND s.status IN {statuses} AND s.attempts < ?"
            " ORDER BY s.arxiv_id",
            (member, config.MAX_ATTEMPTS + (2 if retry_not_found else 0)),
        )
    ]


def run(conn, rm, member, retry_not_found=False, stop=None):
    headers = {"x-api-key": config.S2_API_KEY} if config.S2_API_KEY else {}
    sess = http.session(headers)
    limiter = RateLimiter(config.S2_DELAY)
    while todo := pending(conn, member, retry_not_found):
        _run_pass(conn, rm, sess, limiter, todo, stop)
        if stop is not None and stop.is_set():
            return


def _run_pass(conn, rm, sess, limiter, todo, stop):
    for start in range(0, len(todo), BATCH):
        if stop is not None and stop.is_set():
            break
        batch = todo[start : start + BATCH]
        with rm.stage("refs", n_items=len(batch)) as stage:
            resp, waited = http.request(
                sess,
                limiter,
                "POST",
                config.S2_BATCH_URL,
                params={"fields": FIELDS},
                json={"ids": [f"arXiv:{a}" for a in batch]},
                log=stage.http,
            )
            stage.wait_s += waited
            stage.ok = resp.status_code == 200
            if stage.ok:
                for arxiv_id, paper in zip(batch, resp.json()):
                    _save_paper(conn, arxiv_id, paper)
            else:
                conn.executemany(
                    "UPDATE s2_papers SET status = 'failed', attempts = attempts + 1, error = ?"
                    " WHERE arxiv_id = ?",
                    [(f"HTTP {resp.status_code}: {resp.text[:200]}", a) for a in batch],
                )
            conn.commit()
