"""Is a website up? One GET from our host, redirects followed one hop at a time (site.reachability.v1, PM 11-16
website-trust v2).

Every hop goes through ``net.get(any_site=True)``: https only, port 443, no credentials, the public-address check before
each request (so a redirect to a private address is refused), the per-host spacing and, inside a test run, the shared
ledger. Redirects are never followed by the HTTP client itself. The body is not kept: only the status, the final
address, the number of hops and the time taken are reported.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

from .limits import SourceBusy
from .net import SourceError, get

MAX_HOPS = 5
REDIRECTS = (301, 302, 303, 307, 308)


def reach(url: str, *, limiters: dict, http=None, seconds: float = 3.0, clock=time.monotonic) -> dict:
    """{"reachable", "status", "final_url", "https", "redirects", "elapsed_ms", "note"}.

    reachable is True for a final 2xx or 3xx-free answer below 400. A refusal on our side (spacing, a busy host) is
    raised as SourceBusy, never reported as "down"; a source that does not answer in time or refuses the connection is
    reported as unreachable with the reason."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("an https URL is required")
    started, hops, current = clock(), 0, url
    while True:
        left = seconds - (clock() - started)
        if left <= 0.2:
            return _out(False, None, current, hops, started, clock, "no answer in the time allowed")
        try:
            response = get(current, limiters=limiters, http=http, seconds=left, limit=2 * 1024 * 1024,
                           accept="text/html, */*", ok=tuple(range(200, 600)), any_site=True)
        except SourceBusy as exc:
            # net.get raises the site's own 429/503 as SourceBusy("Source answered HTTP 503; resting."): that is an
            # answer about the site. Anything else (our spacing, a busy host slot, the ledger) is our side: re-raised.
            answered = str(exc).startswith("Source answered HTTP ")
            if not answered:
                raise
            code = int(str(exc).split("HTTP ", 1)[1][:3])
            return _out(False, code, current, hops, started, clock, f"HTTP {code}")
        except SourceError as exc:
            return _out(False, getattr(exc, "status", None), current, hops, started, clock, str(exc)[:120])
        status = response.status_code
        if status in REDIRECTS and hops < MAX_HOPS:
            target = urljoin(current, response.headers.get("location") or "")
            if urlsplit(target).scheme != "https":
                return _out(False, status, target, hops + 1, started, clock, "redirects to a non-https address")
            current, hops = target, hops + 1
            continue
        if status in REDIRECTS:
            return _out(False, status, current, hops, started, clock, f"more than {MAX_HOPS} redirects")
        return _out(status < 400, status, current, hops, started, clock, None if status < 400 else f"HTTP {status}")


def _out(ok, status, final_url, hops, started, clock, note):
    return {"reachable": bool(ok), "status": status, "final_url": final_url,
            "https": urlsplit(final_url).scheme == "https", "redirects": hops,
            "elapsed_ms": int(round((clock() - started) * 1000)), "note": note}
