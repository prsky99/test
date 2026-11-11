"""A larger memo for the offline tool-schema check, keyed by the schema's content hash (2026-11-11).

execution_policy._checked_validator keeps 4,096 checks, while a quarter of the live MCP listings alone
carry 16,175 distinct input schemas; Chat rebuilt hundreds of validators per answer (1.55 s of a
two-answer profile, 4.6 ms each). execution_policy.py is part of the Explore document policy hash,
so it is not edited: install() wraps the same pure check from outside. Results are exactly the
original's (validator or refusal) for the same schema text; only how many are remembered changes.
Measured 5.3 KB per validator: SIZE 16,384 is about 87 MB per process (PM limit 150 MB).
"""
import hashlib
import threading
from collections import OrderedDict, namedtuple

from . import execution_policy

SIZE = 16384
CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


class ContentCache:
    def __init__(self, check, size=SIZE):
        self.__wrapped__ = check
        self.size = size
        self._values = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def __call__(self, encoded):
        key = hashlib.sha256(encoded.encode('utf-8', 'surrogatepass')).digest() if isinstance(encoded, str) else None
        if key is None:
            return self.__wrapped__(encoded)
        with self._lock:
            found = self._values.get(key)
            if found is not None:
                self._values.move_to_end(key)
                self.hits += 1
                return found
        value = self.__wrapped__(encoded)
        with self._lock:
            self.misses += 1
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self.size:
                self._values.popitem(last=False)
        return value

    def cache_info(self):
        with self._lock:
            return CacheInfo(self.hits, self.misses, self.size, len(self._values))

    def cache_clear(self):
        with self._lock:
            self._values.clear()
            self.hits = self.misses = 0


def install():
    """Replace the module-level memo once; supported_schema looks the name up on every call."""
    current = execution_policy._checked_validator
    if isinstance(current, ContentCache):
        return current
    cache = ContentCache(getattr(current, '__wrapped__', current))
    execution_policy._checked_validator = cache
    return cache
