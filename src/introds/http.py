"""HTTP helpers: descriptive User-Agent, per-host rate limiting, retry with exponential backoff."""

import time

import requests

from . import config

RETRY_STATUS = {429, 500, 502, 503, 504}


def session(headers=None):
    sess = requests.Session()
    sess.headers["User-Agent"] = config.USER_AGENT
    sess.headers.update(headers or {})
    return sess


def _retry_after(resp):
    try:
        return float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


def request(sess, limiter, method, url, *, retries=5, backoff=5.0, timeout=120, log=None, **kwargs):
    """Send a request when the limiter allows it, retrying transient failures.

    Returns (response, seconds spent waiting). Every attempt, retries included, goes through
    the limiter, so the host never sees requests closer than its minimum interval. When `log` is
    a list, the status code (or exception name) of every attempt is appended to it.
    """
    waited = 0.0
    for attempt in range(retries + 1):
        waited += limiter.wait()
        try:
            resp = sess.request(method, url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if log is not None:
                log.append(type(exc).__name__)
            if attempt == retries:
                raise
            delay = backoff * 2**attempt
        else:
            if log is not None:
                log.append(resp.status_code)
            if resp.status_code not in RETRY_STATUS or attempt == retries:
                return resp, waited
            delay = _retry_after(resp) or backoff * 2**attempt
            resp.close()
        time.sleep(delay)
        waited += delay
    raise AssertionError("unreachable")
