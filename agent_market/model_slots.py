"""One budget for the generation server's parallel slots, shared by every service process (11-11).

The Mac mini model server now runs 4 requests at a time instead of 16 and queues the rest: with
120-token answers, 4 at once took 2.2-3.2 s, 8 at once 4.2-5.3 s for the second four (PM, 11-11).
Each process used to bound itself (frontend concurrency 8 "the server batches 16"), so together
the processes could queue far more than 4 and push the request path past its 2-second budget.

Slots are numbered 0..TOTAL-1. Where the services run (AGENTCON_PROJECT_ROOT set by service_host),
each slot is an exclusive flock on gateway-data/model-slots/slot-N.lock, so the budget holds
across processes and a crashed process releases its slots. Elsewhere (tests, scripts) the slots
are this process's own.

- "request" (bounded Chat rewrites and summaries on the 2-second path) may take any free slot and
  waits at most what its caller allows, usually nothing: a busy model means the rules answer.
- "long" (RAG answers, workspace plans, evaluation scripts, keep-alive) may only use the last
  LONG_DAY slots in the day and LONG_NIGHT slots 02:00-06:59, so batches never fill the server.

Settings, in gateway-data/local-model-slots.env (its own file: retained releases never read it):
WORKSPACE_MODEL_SLOTS (total, default 4) and WORKSPACE_MODEL_LONG_SLOTS (day share, default 1).
"""
import contextvars
from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path
import threading
import time

import httpx

log = logging.getLogger('agent_market.model_slots')

TOTAL, LONG_DAY, LONG_NIGHT = 4, 1, 2
NIGHT_HOURS = range(2, 7)
LONG_WAIT = 10.0  # seconds a long call waits for its share before failing like a busy server
POLL = 0.05

_held = contextvars.ContextVar('agentcon_model_slot_held', default=False)
_guard = threading.Lock()
_thread_locks: dict[int, threading.Lock] = {}
_files: dict[int, int] = {}
stats = {'request_taken': 0, 'request_busy': 0, 'long_taken': 0, 'long_busy': 0, 'long_wait_ms': 0}


def _number(name, default, low, high):
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return min(high, max(low, value))


def total():
    return _number('WORKSPACE_MODEL_SLOTS', TOTAL, 1, 64)


def long_share(now=None):
    count = total()
    hour = time.localtime(now).tm_hour
    if hour in NIGHT_HOURS:
        return min(count, max(_number('WORKSPACE_MODEL_LONG_SLOTS', LONG_DAY, 1, count), LONG_NIGHT))
    return _number('WORKSPACE_MODEL_LONG_SLOTS', LONG_DAY, 1, count)


def slot_dir():
    explicit = os.environ.get('WORKSPACE_MODEL_SLOT_DIR')
    if explicit:
        return Path(explicit)
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'gateway-data' / 'model-slots' if root else None


def _candidates(kind):
    count = total()
    if kind == 'request':
        return list(range(count))
    return list(range(count - long_share(), count))


def _try(index):
    with _guard:
        lock = _thread_locks.setdefault(index, threading.Lock())
    if not lock.acquire(blocking=False):
        return False
    folder = slot_dir()
    if folder is None:
        return True
    try:
        with _guard:
            descriptor = _files.get(index)
            if descriptor is None:
                folder.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(folder / ('slot-%d.lock' % index), os.O_RDWR | os.O_CREAT, 0o600)
                _files[index] = descriptor
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        lock.release()
        return False


def acquire(kind='long', wait=0.0):
    """A slot index, or None when every slot this kind may use stays busy for `wait` seconds."""
    deadline = time.monotonic() + max(0.0, wait or 0.0)
    began = time.monotonic()
    while True:
        for index in _candidates(kind):
            if _try(index):
                stats[kind + '_taken'] += 1
                if kind == 'long':
                    stats['long_wait_ms'] += int((time.monotonic() - began) * 1000)
                return index
        if time.monotonic() >= deadline:
            stats[kind + '_busy'] += 1
            return None
        time.sleep(POLL)


def release(index):
    descriptor = _files.get(index)
    if descriptor is not None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
    _thread_locks[index].release()


def held():
    return _held.get()


def mark():
    """Note that this context already holds a slot; pass the result to unmark() when done."""
    return _held.set(True)


def unmark(token):
    _held.reset(token)


@contextmanager
def holding(index):
    """Mark this context as holding `index`, so nested generation calls do not take a second slot."""
    token = _held.set(True)
    try:
        yield index
    finally:
        _held.reset(token)
        release(index)


@contextmanager
def slot(kind='long', wait=None):
    """Hold one slot for a generation call; a busy budget fails like a busy server (httpx error)."""
    if _held.get():
        yield None
        return
    index = acquire(kind, LONG_WAIT if wait is None else wait)
    if index is None:
        raise httpx.PoolTimeout('Local model slots are busy.')
    with holding(index):
        yield index


def status():
    return {'total': total(), 'long_share': long_share(), 'shared': slot_dir() is not None, **stats}
