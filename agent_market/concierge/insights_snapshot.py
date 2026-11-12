"""/api/insights served from a snapshot the jobs service writes every few minutes (PM 11-13 02:2x).

11-13 01:49 GET /api/insights answered 500: its first statement (every active resource grouped by kind, fifteen
sums) hit the 5 s statement timeout while the Mac's load was 10-13, and even a quiet first request took 5.99 s.
The public request path no longer aggregates. The jobs service computes the same result (get_front_insights,
unchanged registered statements) every REFRESH_SECONDS and writes it atomically to
<project root>/logs/service-frontend/public-pages/insights.json, where both frontend slots read it (the same
folder and pattern as task-pages.json). A failed computation keeps the last written file, so a request always
gets the last successful value. Only before the very first snapshot exists does a request fall back to the old
in-process computation.
"""
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
NAME = 'insights.json'
REFRESH_SECONDS = 300.0     # catalog statistics change slowly; the policy allows snapshot answers
RETRY_SECONDS = 60.0        # after a failed round (statement timeout under load)
CHECK_SECONDS = 5.0         # a reader looks at the file's mtime at most this often


def output_path():
    """Where the jobs service writes (AGENTCON_PROJECT_ROOT, as task_pages_job)."""
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'logs/service-frontend/public-pages' / NAME if root else None


def read_path():
    """Where a frontend slot reads (LOG_DIR/public-pages, as the task snapshot)."""
    from .growth_pages import data_dir
    folder = data_dir()
    return folder / NAME if folder else None


def valid(value):
    return isinstance(value, dict) and isinstance(value.get('kinds'), dict) and isinstance(value.get('now'), (int, float))


def write(path, value):
    if not valid(value):
        raise ValueError('The insights snapshot failed validation; nothing was written.')
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix='.insights.')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, separators=(',', ':'))
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


class Reader:
    """The snapshot file, re-read only when its mtime or size changes; the last good value survives a bad file."""

    def __init__(self, path_fn=None, monotonic=time.monotonic):
        self.path_fn, self.monotonic = path_fn or read_path, monotonic
        self.lock = threading.Lock()
        self.key, self.value, self.checked = None, None, None

    def read(self):
        now = self.monotonic()
        with self.lock:
            if self.checked is not None and now - self.checked < CHECK_SECONDS:
                return self.value
            self.checked = now
            path = self.path_fn()
            try:
                stat = path.stat() if path else None
            except OSError:
                stat = None
            key = (str(path), stat.st_mtime_ns, stat.st_size) if stat else None
            if key is None or key == self.key:
                return self.value
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                value = None
            if valid(value):
                self.key, self.value = key, value
            return self.value


_reader = Reader()


def reset():
    """Forget the value in memory (clear_front_caches); the file itself is untouched."""
    with _reader.lock:
        _reader.key, _reader.value, _reader.checked = None, None, None


def served(store):
    """The public answer: the jobs snapshot; the old computation only while no snapshot has ever been read."""
    value = _reader.read()
    if value is not None:
        return value
    from .front import get_front_insights
    return get_front_insights(store)


class InsightsRefresher:
    """One computation per due round in the jobs maintenance slot."""

    def __init__(self, front, *, out=None, clock=time.time, compute=None):
        self.front, self.clock = front, clock
        self.out = Path(out) if out else output_path()
        if compute is None:
            from .front import get_front_insights
            compute = lambda store: get_front_insights(store, fresh=True)
        self.compute = compute
        self.next_at = 0.0

    def due(self):
        return self.out is not None and self.clock() >= self.next_at

    def run(self):
        self.next_at = self.clock() + RETRY_SECONDS
        started = time.monotonic()
        try:
            value = self.compute(self.front.store)
            write(str(self.out), value)
        except Exception as exc:
            # The last written file keeps serving; only the error class and store code reach the log.
            log.warning('Insights snapshot round failed (%s %s); the previous snapshot stays; retry in %.0f s',
                        type(exc).__name__, getattr(exc, 'code', '') or '', RETRY_SECONDS)
            return False
        self.next_at = self.clock() + REFRESH_SECONDS
        log.info('Insights snapshot written in %.1f s', time.monotonic() - started)
        return True
