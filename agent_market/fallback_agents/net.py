"""One outbound GET to an allowed public source host.

- Fixed host allowlist (public sources only), HTTPS only, no credentials, no redirects.
- Private and internal addresses are refused twice: a bounded DNS preflight
  (``validate_public_url``, the ``check_public_url`` rule) and the public-only
  connection backend of ``bounded_client``.
- Per-host pacing and 429 rest from ``limits``; no hidden retry.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from urllib.parse import urlsplit

from ..concierge.http_security import bounded_client, outbound_operation, validate_public_url
from .catalog import USER_AGENT
from .limits import SourceBusy

ALLOWED_HOSTS = frozenset({"services.nvd.nist.gov", "nvd.nist.gov", "cveawg.mitre.org", "www.cisa.gov",
                           "api.first.org", "api.github.com", "registry.npmjs.org", "pypi.org",
                           "api.deps.dev", "api.gleif.org", "www.sec.gov", "data.sec.gov",
                           "en.wikipedia.org", "export.arxiv.org", "api.worldbank.org",
                           "api.met.no", "api.scorecard.dev",
                           "www.ecb.europa.eu", "earthquake.usgs.gov", "davidmegginson.github.io",
                           "en.wiktionary.org", "data.iana.org"})


# Test runs we start ourselves (answer sets, gate rounds, report runs) count every outside call in the shared
# per-domain daily ledger (agent_market.provider_budget, deploy/PROVIDER_BUDGET.md). Live necklace calls do not.
_BUDGET_SYSTEM = contextvars.ContextVar("fallback_budget_system", default=None)


@contextmanager
def budget(system: str | None):
    """Within this block every outside call reserves one call of SYSTEM first and records its status after."""
    token = _BUDGET_SYSTEM.set(system)
    try:
        yield
    finally:
        _BUDGET_SYSTEM.reset(token)


class SourceError(RuntimeError):
    """The source failed; the message never carries raw upstream content."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


SITE_HOST = __import__("re").compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def site_host(host: str | None) -> bool:
    """A public DNS name for the website-readiness agent: no IP literals, no single labels, no local names."""
    host = (host or "").lower()
    return bool(SITE_HOST.fullmatch(host)) and not host.endswith((".local", ".localhost", ".internal", ".lan",
                                                                    ".home", ".corp", ".test", ".invalid"))


def get(url: str, *, limiters: dict, http=None, params=None, seconds: float, limit: int,
        accept: str = "application/json", preflight: bool = True, headers: dict | None = None, ok=(200,),
        any_site: bool = False):
    """Return the httpx response for an ``ok`` status (200; 304 for conditional requests); raise SourceBusy
    or SourceError otherwise. ``headers`` may only add conditional request headers."""
    extra = {k: v for k, v in (headers or {}).items() if k in ("If-Modified-Since", "If-None-Match")}
    parsed = urlsplit(url)
    allowed = site_host(parsed.hostname) if any_site else parsed.hostname in ALLOWED_HOSTS
    if (parsed.scheme != "https" or not allowed or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise SourceError("Source not allowed.")
    if any_site and parsed.hostname not in limiters:
        from .limits import HostLimiter
        if len(limiters) > 512:  # bound the per-site table; old sites start fresh
            for key in [k for k in limiters if k not in ALLOWED_HOSTS][:256]:
                limiters.pop(key, None)
        ref = next(iter(limiters.values()), None)  # same clock as the fixed hosts (tests use a fake one)
        limiters[parsed.hostname] = HostLimiter(0.3, 30, 60.0, *((ref.clock, ref.sleep) if ref else ()))
    limiter = limiters[parsed.hostname]
    headers = {"User-Agent": USER_AGENT, "Accept": accept, **extra}
    if parsed.hostname == "api.github.com":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    system = _BUDGET_SYSTEM.get()
    if system:
        from ..provider_budget import reserve
        allowed, why = reserve(url, system)
        if not allowed:
            raise SourceBusy(f"Shared test budget refused the call ({why}).")
    with outbound_operation(seconds) as op_budget:
        with limiter.slot(op_budget.remaining()):
            if preflight and http is None:
                try:
                    validate_public_url(url)
                except Exception as exc:  # DiscoveryError and DNS failures alike
                    raise SourceError("Source address is not a public destination.") from exc
            client = bounded_client(http, timeout=min(seconds, op_budget.remaining()), limit=limit, headers=headers)
            try:
                try:
                    response = client.request("GET", url, params=params, headers=headers,
                                              timeout=min(seconds, op_budget.remaining()))
                except Exception as exc:
                    raise SourceError("Source did not answer in time.") from exc
                limiter.observed(response.status_code, response.headers)
                if system:
                    from ..provider_budget import note
                    note(url, system, response.status_code)
            finally:
                client.close()
    if response.status_code in (429, 503):
        raise SourceBusy(f"Source answered HTTP {response.status_code}; resting.")
    if response.status_code not in ok:
        raise SourceError(f"Source answered HTTP {response.status_code}.", response.status_code)
    return response
