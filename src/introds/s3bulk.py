"""Bulk source download from arXiv's requester-pays S3 bucket (s3://arxiv/src/).

Each monthly tar (~500 MB) holds one gzipped source per paper, named <yymm>/<id>.gz, as it was
when the tar was packed; the file carries no version number. The version is inferred as the
latest version whose submission date is not after the member's modification time. Every other
version (older ones, or revisions after packing) stays pending for export.arxiv.org.

Requires AWS credentials (environment variables or ~/.aws); the requester pays the transfer.
With AWS_ROLE_ARN set, those credentials are only used to assume that (read-only) role.
"""

import os
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import boto3

from . import sources

BUCKET = "arxiv"
MANIFEST = "src/arXiv_src_manifest.xml"
REGION = "us-east-1"


def _client():
    """S3 client; assumes AWS_ROLE_ARN when set (role sessions last 1 h, so call it per tar)."""
    role = os.getenv("AWS_ROLE_ARN")
    if not role:
        return boto3.client("s3", region_name=REGION)
    creds = boto3.client("sts").assume_role(RoleArn=role, RoleSessionName="introds-s3bulk")
    c = creds["Credentials"]
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
    )


def manifest(s3):
    body = s3.get_object(Bucket=BUCKET, Key=MANIFEST, RequestPayer="requester")["Body"].read()
    return [{c.tag: c.text for c in f} for f in ET.fromstring(body).iter("file")]


def _number(arxiv_id):
    return int(arxiv_id.split(".")[1])


def plan(entries, ids):
    """Tars holding at least one of the given (discovered) arXiv IDs."""
    by_month = {}
    for arxiv_id in ids:
        by_month.setdefault(arxiv_id.split(".")[0], []).append(_number(arxiv_id))
    tars = []
    for e in entries:
        numbers = by_month.get(e["yymm"])
        if not numbers:  # also skips pre-2007 tars, whose IDs (hep-th9901001) have no dot
            continue
        lo, hi = _number(e["first_item"]), _number(e["last_item"])
        if any(lo <= n <= hi for n in numbers):
            tars.append(e)
    return tars


def _version_dates(conn, member):
    """{arxiv_id: [(version, epoch seconds)]} for papers of the member, oldest first."""
    rows = conn.execute(
        "SELECT v.arxiv_id, v.version, v.version_date, v.status FROM versions v"
        " JOIN papers p USING (arxiv_id) WHERE p.member = ? ORDER BY v.arxiv_id, v.version",
        (member,),
    )
    out = {}
    for r in rows:
        when = datetime.fromisoformat(r["version_date"]).timestamp() if r["version_date"] else None
        out.setdefault(r["arxiv_id"], []).append((r["version"], when, r["status"]))
    return out


def _match_version(versions, mtime):
    """Latest version submitted before the file was written into the bulk archive."""
    candidates = [v for v, when, _ in versions if when is not None and when <= mtime]
    return max(candidates) if candidates else None


def _process_tar(conn, s3, entry, wanted, keep, stage):
    """Stream one tar from S3 and extract the wanted papers. Returns versions filled."""
    filled = 0
    obj = s3.get_object(Bucket=BUCKET, Key=entry["filename"], RequestPayer="requester")
    stage.http.append(obj["ResponseMetadata"]["HTTPStatusCode"])
    with tarfile.open(fileobj=obj["Body"], mode="r|") as tar:  # sequential: no seeking
        for m in tar:
            if not m.isfile():
                continue
            arxiv_id = m.name.rsplit("/", 1)[-1].removesuffix(".gz").removesuffix(".pdf")
            versions = wanted.get(arxiv_id)
            if not versions:
                continue
            version = _match_version(versions, m.mtime)
            status = next((s for v, _, s in versions if v == version), None)
            if version is None or status not in ("pending", "failed"):
                continue
            data = tar.extractfile(m).read()
            with tempfile.SpooledTemporaryFile(max_size=sources.SPOOL_MAX) as spool:
                spool.write(data)
                result = sources.extract(spool, len(data), arxiv_id, version, keep)
            result |= {"origin": "s3", "error": None}
            sources._save(conn, arxiv_id, version, result)
            filled += 1
    return filled


def verify(conn, sample=20, keep_bbl=False):
    """Re-download sample S3-filled versions from export.arxiv.org and compare kept files.

    Confirms that the inferred version is right: same relative paths and SHA-256 per file.
    """
    keep = {".tex", ".bib"} | ({".bbl"} if keep_bbl else set())
    rows = conn.execute(
        "SELECT arxiv_id, version FROM versions WHERE origin = 's3' ORDER BY RANDOM() LIMIT ?",
        (sample,),
    ).fetchall()
    sess, limiter = sources.http.session(), sources.RateLimiter(sources.config.ARXIV_DELAY)
    results = []
    for r in rows:
        stage = type("Stage", (), {"wait_s": 0.0, "http": []})()
        url = f"{sources.config.ARXIV_SRC_URL}/{r['arxiv_id']}v{r['version']}"
        with tempfile.SpooledTemporaryFile(max_size=sources.SPOOL_MAX) as spool:
            status, _, _ = sources._download(sess, limiter, url, stage, spool)
            if status != 200:
                results.append((r["arxiv_id"], r["version"], f"HTTP {status}"))
                continue
            spool.seek(0)
            _, members, _, _, _ = sources._classify(spool, keep)
        remote = {rel: sources.hashlib.sha256(data).hexdigest() for rel, data in members}
        local = dict(
            conn.execute(
                "SELECT rel_path, sha256 FROM files WHERE arxiv_id = ? AND version = ?",
                (r["arxiv_id"], r["version"]),
            ).fetchall()
        )
        results.append((r["arxiv_id"], r["version"], "match" if remote == local else "MISMATCH"))
    return results


def run(conn, rm, member, keep_bbl=False, stop=None):
    keep = {".tex", ".bib"} | ({".bbl"} if keep_bbl else set())
    s3 = _client()
    with rm.stage("s3", n_items=1) as stage:
        entries = manifest(s3)
    wanted = _version_dates(conn, member)
    tars = plan(entries, wanted)
    print(f"[s3] {len(tars)} tars, {sum(int(t['size']) for t in tars) / 1e9:.1f} GB", flush=True)
    for entry in tars:
        if stop is not None and stop.is_set():
            return
        with rm.stage("s3", n_items=int(entry["num_items"])) as stage:
            started = time.time()
            filled = _process_tar(conn, _client(), entry, wanted, keep, stage)
        took = time.time() - started
        print(f"[s3] {entry['filename']}: {filled} versions in {took:.0f}s", flush=True)
        wanted = _version_dates(conn, member)
