"""Rest a provider host after HTTP 429: honor Retry-After, then call it again (11-14, PM 04:5x).

11-13 05:42 the provider of 42798 answered 429 (its front's rate limit, an HTML page) and every path we have
called it again at once: the Edge handshake, the Origin gateway fallback (server/discover, then initialize),
and the health check (server/discover, then initialize). Each of those paths now notes a 429 here and, until
the wait is over, does not contact that host: the caller gets a "rate limited, retry later" answer instead.

The book is per process (frontend, collector); nothing is written to the database. The wait is the provider's
Retry-After (seconds or an HTTP date), or DEFAULT_S without one, kept between MIN_S and MAX_S.
"""
import email.utils
import threading
import time
from urllib.parse import urlsplit

DEFAULT_S, MIN_S, MAX_S = 300, 30, 3600
_LIMIT = 4096   # hosts kept at once; expired entries are dropped first


def retry_after(headers, now=None, default=DEFAULT_S):
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP-date), bounded to [MIN_S, MAX_S]."""
    value = headers.get('retry-after') if headers is not None else None
    seconds = None
    if isinstance(value, str) and value.strip():
        value = value.strip()
        if value.isdigit():
            seconds = int(value)
        else:
            try:
                seconds = email.utils.parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
            except (TypeError, ValueError, IndexError, OverflowError):
                seconds = None
    if seconds is None:
        seconds = default
    return int(min(MAX_S, max(MIN_S, seconds)))


def host_of(url):
    try:
        return (urlsplit(url or '').hostname or '').lower()
    except ValueError:
        return ''


class RateLimited(ValueError):
    """The provider answered HTTP 429; seconds is the wait noted in the book."""

    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(f'provider rate limited (HTTP 429), retry after {seconds} s')


class RestBook:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._until = {}
        self._lock = threading.Lock()

    def rest(self, url, seconds):
        host = host_of(url)
        if not host:
            return
        with self._lock:
            now = self.clock()
            until = now + max(0, seconds)
            if until > self._until.get(host, 0):
                self._until[host] = until
            if len(self._until) > _LIMIT:
                for name in [h for h, u in self._until.items() if u <= now]:
                    del self._until[name]
                while len(self._until) > _LIMIT:
                    del self._until[min(self._until, key=self._until.get)]

    def remaining(self, url):
        """Whole seconds this host still rests (0 when it may be called)."""
        host = host_of(url)
        with self._lock:
            until = self._until.get(host)
            if until is None:
                return 0
            left = until - self.clock()
            if left <= 0:
                del self._until[host]
                return 0
            return int(left) + (left > int(left))

    def note(self, url, response):
        """Rest the host when the response is HTTP 429; returns the seconds noted (0 otherwise)."""
        if getattr(response, 'status_code', None) != 429:
            return 0
        seconds = retry_after(getattr(response, 'headers', None))
        self.rest(url, seconds)
        return seconds

    def clear(self):
        with self._lock:
            self._until.clear()


BOOK = RestBook()
