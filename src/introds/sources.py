"""Download each version's source from export.arxiv.org and keep only .tex/.bib (optionally .bbl).

Figures are removed by extraction: the archive is spooled in memory (on disk past SPOOL_MAX),
only the wanted members are written under RAW_DIR, and the archive itself is never stored.
"""

import gzip
import hashlib
import posixpath
import shutil
import tarfile
import tempfile
import time
import zlib

import requests

from . import config, http, ranges
from .ratelimit import RateLimiter

SPOOL_MAX = 64 * 2**20
STREAM_RETRIES = 8  # each retry resumes where the previous one stopped
TEX_MARKERS = (b"\\documentclass", b"\\documentstyle", b"\\begin{document}", b"\\section")
KINDS = {".tex": "tex", ".bib": "bib", ".bbl": "bbl"}


def version_dir(arxiv_id, version):
    return config.RAW_DIR / ranges.folder_name(arxiv_id) / f"v{version}"


def _safe_rel(name):
    """Normalise an archive member path; reject absolute paths and parent traversal."""
    rel = posixpath.normpath(name.replace("\\", "/")).lstrip("/")
    if rel in ("", ".") or rel == ".." or rel.startswith("../"):
        return None
    return rel


def _looks_like_tex(data):
    head = data[:200_000]
    return any(marker in head for marker in TEX_MARKERS)


def _from_tar(spool, keep):
    members, unpacked, n_bbl = [], 0, 0
    with tarfile.open(fileobj=spool, mode="r:*") as tar:
        n_files = 0
        for m in tar:
            if not m.isfile():
                continue
            n_files += 1
            unpacked += m.size
            rel = _safe_rel(m.name)
            ext = posixpath.splitext(rel or "")[1].lower()
            n_bbl += ext == ".bbl"
            if rel and ext in keep:
                members.append((rel, tar.extractfile(m).read()))
    return members, unpacked, n_files, n_bbl


def _classify(spool, keep):
    """Return (source_format, kept members, bytes_unpacked, n_files, n_bbl)."""
    head = spool.read(512)
    spool.seek(0)
    if head.startswith(b"%PDF"):
        return "pdf", [], None, 1, 0
    try:
        members, unpacked, n_files, n_bbl = _from_tar(spool, keep)
        return "tar", members, unpacked, n_files, n_bbl
    except tarfile.TarError:
        spool.seek(0)
    if head[:2] == b"\x1f\x8b":  # a single gzipped file, usually one .tex
        try:
            data = gzip.decompress(spool.read())
        except (OSError, EOFError, zlib.error):
            return "other", [], None, 1, 0
        fmt = "gzip"
    else:
        data, fmt = spool.read(), "plain"
    if data.startswith(b"%PDF"):
        return "pdf", [], len(data), 1, 0
    if _looks_like_tex(data):
        return fmt, [("main.tex", data)], len(data), 1, 0
    return "other", [], len(data), 1, 0


def _write(arxiv_id, version, members):
    dest = version_dir(arxiv_id, version)
    if dest.exists():  # leftovers of an interrupted attempt
        shutil.rmtree(dest)
    rows = []
    for rel, data in members:
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        kind = KINDS[posixpath.splitext(rel)[1].lower()]
        rows.append((arxiv_id, version, rel, kind, len(data), hashlib.sha256(data).hexdigest()))
    return rows


def _download(sess, limiter, url, stage, spool):
    """Stream url into spool. When the connection drops mid-body, continue with an HTTP Range
    request from the last byte received (export.arxiv.org cuts long transfers of big archives)."""
    size = 0
    for attempt in range(STREAM_RETRIES):
        headers = {"Range": f"bytes={size}-"} if size else {}
        resp, waited = http.request(
            sess, limiter, "GET", url, stream=True, headers=headers, log=stage.http
        )
        stage.wait_s += waited
        with resp:
            if resp.status_code not in (200, 206):
                return resp.status_code, resp.reason, 0
            if resp.status_code == 200:  # full body: start over
                spool.seek(0)
                spool.truncate()
                size = 0
            try:
                for chunk in resp.iter_content(1 << 16):
                    spool.write(chunk)
                    size += len(chunk)
                return 200, None, size
            except (requests.exceptions.ChunkedEncodingError, requests.ConnectionError) as exc:
                stage.http.append(f"{type(exc).__name__}@{size}")
                if attempt == STREAM_RETRIES - 1:
                    raise
    raise AssertionError("unreachable")


def fetch_version(sess, limiter, arxiv_id, version, keep, stage):
    """Download and extract one version; returns the column values for the versions table."""
    url = f"{config.ARXIV_SRC_URL}/{arxiv_id}v{version}"
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX) as spool:
        status, reason, size = _download(sess, limiter, url, stage, spool)
        if status == 404:  # arXiv does not serve this version: keep an empty record, no retry
            return {"status": "missing", "http_status": status, "error": reason}
        if status != 200:
            return {"status": "failed", "http_status": status, "error": reason}
        return extract(spool, size, arxiv_id, version, keep) | {"http_status": 200}


def extract(spool, size, arxiv_id, version, keep):
    """Keep the wanted files of one downloaded source (archive bytes in spool)."""
    spool.seek(0)
    fmt, members, unpacked, n_files, n_bbl = _classify(spool, keep)
    files = _write(arxiv_id, version, members)
    n_tex = sum(f[3] == "tex" for f in files)
    return {
        "status": "ok" if n_tex else "no_tex",
        "source_format": fmt,
        "bytes_download": size,
        "bytes_unpacked": unpacked if unpacked is not None else size,
        "bytes_kept": sum(f[4] for f in files),
        "n_files": n_files,
        "n_tex": n_tex,
        "n_bib": sum(f[3] == "bib" for f in files),
        "n_bbl": n_bbl,
        "error": None,
        "_files": files,
    }


def _save(conn, arxiv_id, version, result):
    files = result.pop("_files", [])
    result.setdefault("origin", "export")
    conn.execute("DELETE FROM files WHERE arxiv_id = ? AND version = ?", (arxiv_id, version))
    conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", files)
    cols = ", ".join(f"{k} = ?" for k in result)
    conn.execute(
        f"UPDATE versions SET {cols}, attempts = attempts + 1, fetched_at = ?"
        " WHERE arxiv_id = ? AND version = ?",
        (*result.values(), time.time(), arxiv_id, version),
    )
    conn.commit()


def pending(conn, member):
    return conn.execute(
        "SELECT v.arxiv_id, v.version FROM versions v JOIN papers p USING (arxiv_id)"
        " WHERE p.member = ? AND v.status IN ('pending', 'failed') AND v.attempts < ?"
        " ORDER BY v.arxiv_id, v.version",
        (member, config.MAX_ATTEMPTS),
    ).fetchall()


def run(conn, rm, member, keep_bbl=False, stop=None):
    keep = {".tex", ".bib"} | ({".bbl"} if keep_bbl else set())
    sess = http.session()
    limiter = RateLimiter(config.ARXIV_DELAY)
    # Each pass bumps attempts, so failed versions are retried until MAX_ATTEMPTS is reached
    while todo := pending(conn, member):
        for row in todo:
            if stop is not None and stop.is_set():
                return
            arxiv_id, version = row["arxiv_id"], row["version"]
            with rm.stage("src", arxiv_id, version) as stage:
                try:
                    result = fetch_version(sess, limiter, arxiv_id, version, keep, stage)
                except Exception as exc:  # noqa: BLE001 - one bad archive must not stop the crawl
                    result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
                stage.ok = result["status"] != "failed"
            _save(conn, arxiv_id, version, result)
