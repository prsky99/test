"""Garbage collection settings for the serving frontend (PM 11-16 20:2x).

user_slo caught single collections of 1.4-3.4 s inside public requests (11-14 12:00 1376 ms, 11-15 15:09 2683 ms,
11-16 18:06 3397 ms, 20:09 2510 ms; 4 of 576 samples in three days, load as low as 2.65). Python's oldest
generation is collected when it has grown by a quarter, and each such collection walks every tracked object: the
report snapshot (about 20,900 listings), the explore and chat caches and the imported modules, all long lived.

Two published fixes for the same pause in large web processes, measured before and after:
- collect, then gc.freeze() once the long-lived objects exist: frozen objects move to a permanent generation that no
  later collection walks (Rippling: oldest-generation collections from over 2 s to under 0.5 s);
- a larger generation-0 threshold, so the young collections that lead up to the oldest one run less often (Close:
  700 -> 50,000, p95 80-100 ms better).
A refresh freezes again without a collection (no pause while serving): what the old snapshot held is freed by
reference counting as usual; only garbage in reference cycles would stay frozen, so the frozen count is watched and,
past FROZEN_GROWTH times the start count, one unfreeze + collect + freeze runs and is logged.
"""
import gc
import logging
import resource
import sys
import threading
import time

log = logging.getLogger(__name__)

THRESHOLD0 = 50_000          # Close's value; Python's default is 700 (generations 1 and 2 keep 10 and 10)
FROZEN_GROWTH = 2.0          # a full collection again once the frozen count doubles from the start
_lock = threading.Lock()
_start = {'frozen': None}


def configure(threshold0=THRESHOLD0):
    """Raise the generation-0 threshold (generations 1 and 2 unchanged)."""
    _, one, two = gc.get_threshold()
    gc.set_threshold(threshold0, one, two)
    return gc.get_threshold()


def rss_mb():
    """Peak resident memory of this process in MB (ru_maxrss is bytes on macOS, KB on Linux)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)


def settle(reason, collect=True):
    """Collect (when COLLECT) and freeze what is alive now; returns what it did, also logged."""
    with _lock:
        started = time.perf_counter()
        full = collect
        if not collect and _start['frozen'] and gc.get_freeze_count() >= FROZEN_GROWTH * _start['frozen']:
            gc.unfreeze()            # cycles left by replaced snapshots: one full collection, then freeze again
            full = True
        if full:
            gc.collect()
        gc.freeze()
        frozen = gc.get_freeze_count()
        if _start['frozen'] is None:
            _start['frozen'] = frozen
        done = {'reason': reason, 'collected': full, 'frozen': frozen,
                'ms': round((time.perf_counter() - started) * 1000, 1), 'rss_peak_mb': rss_mb()}
    log.info('GC settled after %(reason)s: collected=%(collected)s frozen=%(frozen)d in %(ms).1f ms, '
             'peak RSS %(rss_peak_mb).1f MB', done)
    return done
