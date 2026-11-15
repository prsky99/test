"""Short-lived memory of the vector provenance check for request paths (PM 11-16 06:4x).

Every ANN call in a recommendation or an Explore search checked the provenance of its up to 100 nearest ids with
one statement (current_ids: generation, job, source and vector hashes, 38 ms on average at 06:32-06:34) - about 3.7
such checks a request. A listing's vectors change far less often than that, and the response time policy accepts
snapshot answers, so each (descriptor, id) verdict is kept for TTL seconds, at most MAX_ENTRIES in the process
(least recently used leave first). Only discovery uses this; publishing, rehearsals and every other caller still
call index.current_ids directly and always read the database.

What may lag by up to TTL seconds: a vector published again or a listing retired since the verdict. Quarantine does
not lag on this path: the ANN statement itself keeps only rows whose eval_security is neither quarantine nor
review, read live with every query, and no front process learns of a quarantine any other way, so there is nothing
here to invalidate early. A publish in this process forgets that listing's verdicts at once (forget()).
No new SQL: a miss calls the index's own current_ids.
"""
from collections import OrderedDict
import threading
import time

# Off until the copy measurement before and after (PM 11-16 06:5x): the day bundle carries this module, and with
# ENABLED false every call goes straight to index.current_ids, exactly as before. No agentcon.env key (11-14).
ENABLED = False
TTL = 120.0
MAX_ENTRIES = 20000

_lock = threading.Lock()
_verdicts = OrderedDict()   # (database, descriptor digest, resource id) -> (stored at, current?)


def _database(index):
    """(host, port, dbname) of the PostgreSQL session behind INDEX, read from the connection without SQL, or None
    (SQLite and anything else are not remembered: their tests reuse ids across short-lived files)."""
    try:
        info = index.store._connection.info
        return (str(info.host), str(info.port), str(info.dbname))
    except AttributeError:
        return None


def current_ids(index, ids, descriptor, *, now=None):
    """The subset of IDS whose vectors are current, as index.current_ids answers, from memory where fresh."""
    if not ENABLED:
        return index.current_ids(ids, descriptor)
    from .concierge.retrieval_metrics import add
    began = time.perf_counter()
    at = time.monotonic() if now is None else now
    digest = getattr(descriptor, 'digest', None)
    database = _database(index)
    if database is None or not isinstance(digest, str) or type(ids) not in (list, tuple, set):
        return index.current_ids(ids, descriptor)
    digest = (database, digest)
    current, missing = set(), []
    with _lock:
        for rid in ids:
            seen = _verdicts.get((digest, rid))
            if seen is not None and at - seen[0] < TTL:
                _verdicts.move_to_end((digest, rid))
                if seen[1]:
                    current.add(rid)
            else:
                missing.append(rid)
    if not missing:
        add('provenance_hit', (time.perf_counter() - began) * 1000)
        return current
    found = index.current_ids(missing, descriptor)
    with _lock:
        for rid in missing:
            _verdicts[(digest, rid)] = (at, rid in found)
            _verdicts.move_to_end((digest, rid))
        while len(_verdicts) > MAX_ENTRIES:
            _verdicts.popitem(last=False)
    add('provenance_miss', (time.perf_counter() - began) * 1000)
    return current | (set(found) & set(missing))


def forget(resource_id):
    """Drop every verdict about one listing (its vector was published again in this process)."""
    with _lock:
        for key in [key for key in _verdicts if key[1] == resource_id]:
            del _verdicts[key]


def clear():
    with _lock:
        _verdicts.clear()
