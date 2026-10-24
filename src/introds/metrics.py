"""Measure time and resources of a run and store them in SQLite for the report to aggregate.

Usage:
    with RunMetrics(conn, "fetch-src", member="m1", data_dir=DATA_DIR) as rm:
        for arxiv_id, version in todo:
            with rm.stage("src", arxiv_id, version) as t:
                t.wait_s += limiter.wait()
                download(...)
"""

import json
import os
import platform
import resource
import socket
import threading
import time
import uuid
from contextlib import contextmanager

import psutil


def dir_size(path):
    """Total size of files under a directory (equivalent to du -sb)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except FileNotFoundError:
                pass
    return total


class _Stage:
    def __init__(self):
        self.wait_s = 0.0
        self.ok = True
        self.http = []  # status code of every HTTP attempt (see http.request)


class RunMetrics:
    def __init__(
        self,
        conn,
        command,
        member=None,
        data_dir=None,
        sample_every=2.0,
        disk_every=60.0,
        config=None,
    ):
        self.conn = conn
        self.command = command
        self.member = member
        self.data_dir = data_dir
        self.sample_every = sample_every
        self.disk_every = disk_every  # walking the tree is expensive, so sample it less often
        self.config = config or {}
        self.run_id = f"{command}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending = []  # timings rows waiting for the next sample
        self._proc = psutil.Process()

    def __enter__(self):
        self.started_at = time.time()
        self._t0 = time.perf_counter()
        self.conn.execute(
            "INSERT INTO runs (run_id, command, member, host, started_at, config_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                self.command,
                self.member,
                f"{socket.gethostname()} ({platform.platform()})",
                self.started_at,
                json.dumps(self.config, default=str),
            ),
        )
        self.conn.commit()
        self._sampler = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._sampler.join()
        self._sample(force_disk=True)
        with self._lock:
            self.conn.execute(
                "UPDATE runs SET ended_at = ? WHERE run_id = ?",
                (time.time(), self.run_id),
            )
            self.conn.commit()
        return False

    @contextmanager
    def stage(self, stage, arxiv_id=None, version=None, n_items=1):
        """Time one unit of work; ok = False on exception or when the caller sets t.ok = False."""
        t = _Stage()
        started_at = time.time()
        t0 = time.perf_counter()
        try:
            yield t
        except BaseException:
            t.ok = False
            raise
        finally:
            row = (
                self.run_id,
                stage,
                arxiv_id,
                version,
                n_items,
                started_at,
                time.perf_counter() - t0,
                t.wait_s,
                int(t.ok),
                ",".join(map(str, t.http)) or None,
            )
            with self._lock:
                self._pending.append(row)

    def _rss(self):
        # Include child processes (if multiprocessing is used) to get whole-system RAM
        total = self._proc.memory_info().rss
        for child in self._proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return total

    def _sample(self, force_disk=False):
        now = time.time()
        if self.data_dir and (force_disk or now - getattr(self, "_disk_at", 0) >= self.disk_every):
            self._disk = dir_size(self.data_dir)
            self._disk_at = now
        with self._lock:
            rows, self._pending = self._pending, []
        # One short transaction per sample: workers never wait on metrics for long
        self.conn.executemany(
            "INSERT INTO timings (run_id, stage, arxiv_id, version, n_items, started_at,"
            " duration_s, wait_s, ok, http_log) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.execute(
            "INSERT INTO resource_samples (run_id, ts, rss_bytes, disk_bytes) VALUES (?, ?, ?, ?)",
            (self.run_id, now, self._rss(), getattr(self, "_disk", 0)),
        )
        self.conn.commit()

    def _sample_loop(self):
        while not self._stop.wait(self.sample_every):
            self._sample()

    def peak_rss_os(self):
        """Kernel-reported peak RSS (KB on Linux, bytes on macOS), to cross-check the sampled values."""
        own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return own, children
