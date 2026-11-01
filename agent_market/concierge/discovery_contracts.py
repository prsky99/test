"""Bounded immutable contract reuse, never cached authority or search results."""
from collections import OrderedDict
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import json
import secrets
import threading
import time

_request = ContextVar('discovery_contract_reads', default=None)


@contextmanager
def isolated_contract_reads():
    """A parallel reader owns its memo; never share mutable request entries between threads."""
    token = _request.set({'items': OrderedDict(), 'bytes': 0})
    try:
        yield
    finally:
        _request.reset(token)
MAX_ENTRIES = 768
MAX_BYTES = 32 * 1024 * 1024
MAX_ITEM_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
_schemas = OrderedDict()
_schema_lock = threading.Lock()
MAX_SCHEMAS = 32768  # 32-byte digest + bool each; the catalog has more distinct tool schemas than 2048


class FactCache:
    """Process-local public declarations, bounded by actual retained bytes."""
    def __init__(self, maximum=1536, maximum_bytes=64 * 1024 * 1024):
        self.maximum, self.maximum_bytes = maximum, maximum_bytes
        self.values, self.bytes, self.lock = OrderedDict(), 0, threading.Lock()

    def get(self, key):
        with self.lock:
            found = self.values.pop(key, None)
            if found is not None:
                self.values[key] = found
                return found[0]
        return None

    def has_payloads(self):
        with self.lock:
            return any(type(key) is tuple and key and key[0] == 'payload' for key in self.values)

    def put(self, key, value, size):
        if type(size) is not int or size < 0:
            raise ValueError('Invalid retained fact size.')
        if size > min(self.maximum_bytes, 4 * 1024 * 1024):
            return
        with self.lock:
            previous = self.values.pop(key, None)
            if previous is not None:
                self.bytes -= previous[1]
            self.values[key] = (value, size)
            self.bytes += size
            while len(self.values) > self.maximum or self.bytes > self.maximum_bytes:
                _, (_, old_size) = self.values.popitem(last=False)
                self.bytes -= old_size


_facts = FactCache()
# json.dumps of these values, which most listing fields hold.
_PLAIN_JSON = {None: b'null', True: b'true', False: b'false'}


class TaskFacts:
    """Short-lived pure task-fit facts; keys are process-keyed opaque digests."""
    # Keys cover every resource field, so a changed listing never reuses a fact; one
    # search examines over a thousand listings, and repeated searches reuse the facts.
    def __init__(self, maximum=32768, lifetime=600, clock=time.monotonic):
        self.maximum, self.lifetime, self.clock = maximum, lifetime, clock
        self.values, self.lock = OrderedDict(), threading.Lock()
        self.key = secrets.token_bytes(32)

    def fingerprint(self, query, resource, terms, core):
        from ..explore_documents import cache_view
        resource = cache_view(resource)
        # Include every current resource field, not a claimed revision alone.
        fields = [('query', query), ('terms', terms), ('core', core), *sorted(resource.items())]
        # One HMAC over the joined frames equals the per-frame updates; a search hashes
        # about a thousand listings of ~100 fields, so the frames are built in one pass.
        parts = []
        for name, value in fields:
            kind = type(value).__name__.encode()
            encoded = (value.encode('utf-8', 'surrogatepass') if type(value) is str else
                       _PLAIN_JSON[value] if value is None or type(value) is bool else
                       str(value).encode() if type(value) is int else
                       json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=True).encode())
            label = str(name).encode('utf-8', 'surrogatepass')
            parts += (len(kind).to_bytes(8, 'big'), kind, len(label).to_bytes(8, 'big'), label,
                      len(encoded).to_bytes(8, 'big'), encoded)
        return hmac.new(self.key, b''.join(parts), hashlib.sha256).digest()

    def get(self, key):
        with self.lock:
            found = self.values.pop(key, None)
            if found is not None and found[0] > self.clock():
                self.values[key] = found
                return found[1]
        return None

    def put(self, key, value):
        with self.lock:
            self.values.pop(key, None)
            self.values[key] = (self.clock() + self.lifetime, value)
            while len(self.values) > self.maximum:
                self.values.popitem(last=False)


_tasks = TaskFacts()


def task_facts(function):
    """Memoize metadata relevance only; callers still check live authorization."""
    @wraps(function)
    def call(query, resource, *, terms=None, core=None):
        if not active() or not isinstance(resource, dict):
            return function(query, resource, terms=terms, core=core)
        try:
            key = _tasks.fingerprint(query, resource, terms, core)
        except (TypeError, ValueError, RecursionError):
            return function(query, resource, terms=terms, core=core)
        found = _tasks.get(key)
        if found is not None:
            return found
        value = function(query, resource, terms=terms, core=core)
        if type(value) is bool:
            _tasks.put(key, value)
        return value
    return call


def active():
    return _request.get() is not None


def payload_key(hashes):
    if (type(hashes) is not tuple or len(hashes) != 2
            or any(v is not None and (type(v) is not str or len(v) != 64
                   or any(c not in '0123456789abcdef' for c in v)) for v in hashes)):
        raise ValueError('Invalid contract observation digest.')
    return ('payload', *hashes)


def payload(hashes):
    return _facts.get(payload_key(hashes)) if active() else None


def payloads_available():
    return active() and _facts.has_payloads()


def remember_payload(hashes, value):
    _remember_payload(value, hashes)


def remember_observed_payload(value):
    """A complete row just read from the DB supplies its own exact source key."""
    _remember_payload(value, None)


def _remember_payload(value, expected):
    if not active() or type(value) is not tuple or len(value) != 2:
        return
    encoded = tuple(v.encode('utf-8') if type(v) is str else None for v in value)
    actual = tuple(hashlib.sha256(v).hexdigest() if v is not None else None for v in encoded)
    if (expected is not None and actual != expected
            or any(v is not None and type(v) is not str for v in value)):
        raise ValueError('Contract observation changed within the read snapshot.')
    _facts.put(payload_key(actual), value, sum(len(v) for v in encoded if v is not None))


def contract_reads(function):
    """Share deterministic parsing within one request and discard it on exit."""
    @wraps(function)
    def call(*args, **kwargs):
        if _request.get() is not None:
            return function(*args, **kwargs)
        token = _request.set({'items': OrderedDict(), 'bytes': 0})
        try:
            return function(*args, **kwargs)
        finally:
            _request.reset(token)
    return call


def tools(resource, build):
    memo = _request.get()
    if memo is None:
        return build(resource)
    # Bind the cache key and its parser to the same immutable observation.
    resource = dict(resource)
    source = tuple(resource.get(name) for name in ('usage_tools', 'usage_full_tools', 'usage_full_hash'))
    # Mutable observations and large declarations retain the original path.
    if any(value is not None and type(value) is not str for value in source):
        return build(resource)
    if sum(len(value or '') for value in source) > MAX_SOURCE_BYTES:
        return build(resource)
    # Length-frame exact source bytes without JSON-escaping large JSON strings.
    digest = hashlib.sha256()
    for value in source:
        if value is None:
            digest.update(b'n')
        else:
            data = value.encode('utf-8', 'surrogatepass')
            digest.update(b's' + len(data).to_bytes(8, 'big'))
            digest.update(data)
    key = digest.digest()
    found = memo['items'].pop(key, None)
    if found is not None:
        memo['items'][key] = found
        # Never expose cached mutable dictionaries to an admission caller.
        return json.loads(found)
    found = _facts.get(('tools', key))
    if found is not None:
        return json.loads(found)
    value = build(resource)
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    except (ValueError, TypeError, RecursionError):
        return value
    size = len(encoded)
    if size <= MAX_ITEM_BYTES:
        _facts.put(('tools', key), encoded, size)
        memo['items'][key] = encoded
        memo['bytes'] += size
        while len(memo['items']) > MAX_ENTRIES or memo['bytes'] > MAX_BYTES:
            _, old = memo['items'].popitem(last=False)
            memo['bytes'] -= len(old)
    return value


def schema_supported(encoded, validate):
    """Memoize only a deterministic schema support fact by its actual content."""
    key = hashlib.sha256(encoded.encode()).digest()
    with _schema_lock:
        if key in _schemas:
            value = _schemas.pop(key)
            _schemas[key] = value
            return value
    # Import locally to preserve the execution-policy module's import order.
    from .execution_policy import ExecutionDenied
    try:
        validate()
        value = True
    except ExecutionDenied:
        value = False
    with _schema_lock:
        _schemas[key] = value
        _schemas.move_to_end(key)
        while len(_schemas) > MAX_SCHEMAS:
            _schemas.popitem(last=False)
    return value
