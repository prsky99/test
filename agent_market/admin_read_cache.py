"""Per-router bounded aggregate cache; authentication always runs before lookup."""
import copy
import json
import threading
import time


class AdminReadCache:
    def __init__(self, ttl=5, stale=30, maximum_bytes=4 * 1024 * 1024, clock=time.monotonic):
        self.ttl, self.stale, self.maximum_bytes, self.clock = ttl, stale, maximum_bytes, clock
        self.condition = threading.Condition()
        self.value, self.at, self.busy, self.epoch = None, 0, False, 0

    def invalidate(self):
        with self.condition:
            self.epoch += 1
            self.value = None

    def _load(self, loader, epoch, background=False):
        try:
            value = loader()
            bounded = len(json.dumps(value, default=str).encode()) <= self.maximum_bytes
            with self.condition:
                if epoch == self.epoch and bounded:
                    self.value, self.at = copy.deepcopy(value), self.clock()
            return value
        except Exception:
            if not background:
                raise
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()

    def get(self, loader, *, force=False):
        with self.condition:
            waited = False
            if not force and self.value is not None:
                age = max(0, self.clock() - self.at)
                if age <= self.stale:
                    stale = age > self.ttl
                    if stale and not self.busy:
                        self.busy = True
                        threading.Thread(target=self._load, args=(loader, self.epoch, True), daemon=True,
                                         name='admin-overview-refresh').start()
                    value = copy.deepcopy(self.value)
                    value['_cache'] = {'status': 'stale' if stale else 'hit', 'age_seconds': round(age, 1)}
                    return value
            deadline = time.monotonic() + 20
            while self.busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('admin_aggregate_refresh_busy')
                self.condition.wait(remaining)
                waited = True
            if waited and self.value is not None and self.clock() - self.at <= self.ttl:
                value = copy.deepcopy(self.value)
                value['_cache'] = {'status': 'hit', 'age_seconds': round(max(0, self.clock() - self.at), 1)}
                return value
            self.busy = True
            epoch = self.epoch
        value = copy.deepcopy(self._load(loader, epoch))
        value['_cache'] = {'status': 'refresh' if force else 'miss', 'age_seconds': 0}
        return value
