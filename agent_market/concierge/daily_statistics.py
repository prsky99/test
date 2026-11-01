"""Bounded daily public catalog snapshots, independent of live UI refreshes."""
import copy
from datetime import datetime, timezone
import json
import threading
import time
from zoneinfo import ZoneInfo

KEY = 'public_catalog_daily_v1'
ZONE = ZoneInfo('Asia/Seoul')
COUNTS = ('cataloged', 'reachable', 'with_status_check', 'a2a', 'mcp', 'x402')
_slots = threading.BoundedSemaphore(2)


def valid(value, now=None):
    """Accept only the documented public aggregate shape, never stored extras."""
    if not isinstance(value, dict) or set(value) != {'day', 'captured_at', 'modified_at', *COUNTS}:
        return False
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10**12 for k in COUNTS):
        return False
    if sum(value[k] for k in ('a2a', 'mcp', 'x402')) != value['cataloged']:
        return False
    if max(value['reachable'], value['with_status_check']) > value['cataloged']:
        return False
    try:
        captured = datetime.fromisoformat(value['captured_at'])
        modified = datetime.fromisoformat(value['modified_at'])
        current = now or datetime.now(timezone.utc)
        return (captured.utcoffset() is not None and modified.utcoffset() is not None
                and captured.isoformat() == value['captured_at']
                and modified.isoformat() == value['modified_at']
                and modified <= captured <= current
                and captured.astimezone(ZONE).date().isoformat() == value['day'])
    except (TypeError, ValueError):
        return False


def description(value):
    return (f"Discover {value['cataloged']:,} AI agents: {value['reachable']:,} reachable; "
            f"{value['with_status_check']:,} with recorded status checks. "
            f"Daily snapshot: {value['day']} KST. A2A first, then MCP; x402 by explicit choice.")


class DailyStatistics:
    def __init__(self, store, *, clock=None, collect=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.collect = collect
        self.lock = threading.Lock()
        self.value = None
        self.job = None
        self.retry_at = 0.

    def peek(self):
        with self.lock:
            return copy.deepcopy(self.value) if valid(self.value, self.clock()) else None

    def read(self, seconds=.15):
        """Never put catalog aggregation on the request's critical path."""
        now = self.clock()
        with self.lock:
            if valid(self.value, now) and self.value['day'] == now.astimezone(ZONE).date().isoformat():
                return copy.deepcopy(self.value)
            if self.job is None and time.monotonic() >= self.retry_at and _slots.acquire(blocking=False):
                done = threading.Event()
                self.job = done
                def build():
                    try:
                        self._refresh()
                    except Exception:
                        # Keep the original snapshot date; never turn errors into zeros.
                        with self.lock:
                            self.retry_at = time.monotonic()+60
                    finally:
                        with self.lock:
                            self.job = None
                        done.set()
                        _slots.release()
                try:
                    threading.Thread(target=build, name='daily-public-statistics', daemon=True).start()
                except Exception:
                    self.job = None
                    self.retry_at = time.monotonic()+60
                    _slots.release()
            done = self.job
        if done is not None:
            done.wait(max(0., min(float(seconds), .25)))
        return self.peek()

    def _refresh(self):
        from .request_store import interactive_store
        now = self.clock()
        day = now.astimezone(ZONE).date().isoformat()
        with interactive_store(self.store, readonly=True) as reader:
            try:
                previous = reader.get_meta(KEY)
            except (ValueError, TypeError):
                previous = None
        if valid(previous, now):
            with self.lock:
                self.value = previous
            if previous['day'] == day:
                return
        from .pearl_view import catalog_status
        data = (self.collect or catalog_status)(self.store)
        # Record the observation time, not the later end of the aggregate query.
        captured = datetime.fromisoformat(data['captured_at_utc']).astimezone(timezone.utc)
        value = {k: data[k] for k in COUNTS[:3]}
        value.update({row['kind']: row['n'] for row in data['by_protocol']})
        value.update(day=captured.astimezone(ZONE).date().isoformat(),
                     captured_at=captured.isoformat(), modified_at=captured.isoformat())
        if valid(previous, now) and all(value[k] == previous[k] for k in COUNTS):
            value['modified_at'] = previous['modified_at']
        if not valid(value, self.clock()):
            raise ValueError('Invalid public statistics snapshot.')
        # Recheck under the store's write transaction: concurrent service slots
        # share the winning snapshot, with no new table or unbounded history.
        with interactive_store(self.store) as writer:
            with writer.tx() as db:
                row = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
                try:
                    winner = json.loads(row['value']) if row else None
                except (ValueError, TypeError):
                    winner = None
                if valid(winner, self.clock()) and winner['day'] >= value['day']:
                    value = winner
                else:
                    db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (KEY, json.dumps(value)))
        with self.lock:
            self.value = value
