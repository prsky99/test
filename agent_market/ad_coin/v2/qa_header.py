"""X-Agentcon-QA: our own measurement requests, never counted as ad views or clicks (PM 11-15 R39).

Until gateway-data/qa-header.key exists any non-empty value counts, as before (other teams' tools send free text).
Once the operator creates the key file, only a signed value counts: "v1.<unix minute>.<hex HMAC-SHA256 of
'v1.<minute>' with the key>", accepted within two minutes either side. sign() makes one for our own tools. A value
that fails is treated as a normal request (counted, no region override), so a forged header gains nothing.
"""
import hashlib
import hmac
import time

KEY_FILE = "gateway-data/qa-header.key"
WINDOW_MINUTES = 2
_cache = {"at": 0.0, "key": None}


def _key():
    now = time.monotonic()
    if now - _cache["at"] > 60:                       # read at most once a minute; no file means legacy mode
        from .paid_bookings import data_path
        try:
            with open(data_path(KEY_FILE), "rb") as handle:
                _cache["key"] = handle.read().strip() or None
        except OSError:
            _cache["key"] = None
        _cache["at"] = now
    return _cache["key"]


def sign(key=None, now=None):
    key = key if key is not None else _key()
    minute = int((time.time() if now is None else now) // 60)
    payload = "v1.%d" % minute
    return payload + "." + hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def is_qa(value, *, key=None, now=None):
    """True for a request from our own measurement tools."""
    if not isinstance(value, str) or not value.strip():
        return False
    key = key if key is not None else _key()
    if key is None:
        return True                                   # legacy: before the key file exists
    parts = value.strip().split(".")
    if len(parts) != 3 or parts[0] != "v1" or not parts[1].isdigit():
        return False
    minute = int(parts[1])
    current = int((time.time() if now is None else now) // 60)
    if abs(current - minute) > WINDOW_MINUTES:
        return False
    expected = hmac.new(key, ("v1.%d" % minute).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts[2])


def reset_cache():
    _cache.update(at=0.0, key=None)


if __name__ == "__main__":
    # for our own tools: X-Agentcon-QA: $(python -m agent_market.ad_coin.v2.qa_header)
    print(sign() if _key() else "legacy-no-key")
