"""Verify search and AI crawlers by their operators' published IP lists (2026-11-10).

Our limiter jailed ClaudeBot (11-08~10: 20 rate-limit 429s, 16 blocked 403s, 4 auto-jails on /agent/<id>,
/agents/best, /agents/compare). A crawler counts as verified only when its User-Agent names it AND the
client address is in the list its operator publishes; a copied User-Agent alone changes nothing.

Lists are fetched in the background at most once a day and cached in a file, so the request path only
does in-memory lookups. A list that cannot be fetched keeps the previous one; with no list at all,
nothing is verified (the old rules apply).
"""
import ipaddress
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
REFRESH_SECONDS = 86400
CACHE_LIMIT = 4096
MULTIPLIER = 10   # read and Explore limits for a verified crawler

# Published lists: (url, crawler names the list covers). Fixed public HTTPS URLs only.
SOURCES = {
    'anthropic': ('https://claude.com/crawling/bots.json', ('ClaudeBot', 'Claude-SearchBot', 'Claude-User')),
    'openai-gptbot': ('https://openai.com/gptbot.json', ('GPTBot',)),
    'openai-searchbot': ('https://openai.com/searchbot.json', ('OAI-SearchBot',)),
    'openai-chatgpt-user': ('https://openai.com/chatgpt-user.json', ('ChatGPT-User',)),
    'perplexity': ('https://www.perplexity.ai/perplexitybot.json', ('PerplexityBot',)),
    'google-googlebot': ('https://developers.google.com/static/search/apis/ipranges/googlebot.json', ('Googlebot',)),
    'google-common': ('https://developers.google.com/static/crawling/ipranges/common-crawlers.json', ('Googlebot', 'GoogleOther')),
    'bing': ('https://www.bing.com/toolbox/bingbot.json', ('bingbot',)),
    'apple': ('https://search.developer.apple.com/applebot.json', ('Applebot',)),
}
NAMES = tuple(dict.fromkeys(name for _, names in SOURCES.values() for name in names))
# Longest first so 'Claude-SearchBot' is not read as a shorter name.
_CLAIM = re.compile('|'.join(re.escape(n) for n in sorted(NAMES, key=len, reverse=True)), re.I)
_CANONICAL = {n.lower(): n for n in NAMES}


def claimed(user_agent):
    """The crawler a User-Agent names, or None."""
    if not user_agent:
        return None
    match = _CLAIM.search(str(user_agent)[:512])
    return _CANONICAL[match.group(0).lower()] if match else None


def parse(document):
    """Networks from a published list ({"prefixes": [{"ipv4Prefix"|"ipv6Prefix": ...}]})."""
    networks = []
    for item in (document or {}).get('prefixes', ()):
        for key in ('ipv4Prefix', 'ipv6Prefix'):
            value = item.get(key) if isinstance(item, dict) else None
            if value:
                try:
                    networks.append(ipaddress.ip_network(value, strict=False))
                except ValueError:
                    continue
    return networks


def default_cache():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'logs/service-frontend/crawler-ip-ranges.json' if root else None


class Verifier:
    def __init__(self, cache=None, fetch=None, clock=time.time, background=True):
        self.cache_path = Path(cache) if cache else default_cache()
        self.fetch = fetch or _fetch
        self.clock, self.background = clock, background
        self._lock = threading.Lock()
        self._ranges, self._loaded_at, self._refreshing = {}, 0.0, False
        self._seen = {}
        self._load_file()

    def _load_file(self):
        try:
            data = json.loads(self.cache_path.read_text())
            self._ranges = {name: parse({'prefixes': items}) for name, items in data['ranges'].items()}
            self._loaded_at = float(data['fetched_at'])
        except Exception:
            pass

    def refresh(self):
        """Fetch every list; a failed list keeps its previous networks."""
        raw = {}
        for source, (url, names) in SOURCES.items():
            try:
                document = self.fetch(url)
                if parse(document):
                    raw[source] = document.get('prefixes', [])
            except Exception as error:
                log.warning('Crawler IP list %s unavailable: %s', source, type(error).__name__)
        with self._lock:
            ranges = {name: list(nets) for name, nets in self._ranges.items()}
            items_by_name = {}
            for source, (url, names) in SOURCES.items():
                if source in raw:
                    for name in names:
                        items_by_name.setdefault(name, []).extend(raw[source])
            for name, items in items_by_name.items():
                ranges[name] = parse({'prefixes': items})
            self._ranges, self._loaded_at, self._seen = ranges, self.clock(), {}
            self._refreshing = False
        if self.cache_path and items_by_name:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                serial = {name: [{'ipv6Prefix' if n.version == 6 else 'ipv4Prefix': str(n)} for n in nets]
                          for name, nets in ranges.items()}
                partial = self.cache_path.with_suffix('.tmp')
                partial.write_text(json.dumps({'fetched_at': self._loaded_at, 'ranges': serial}))
                partial.replace(self.cache_path)
            except OSError:
                pass

    def _maybe_refresh(self):
        with self._lock:
            if self._refreshing or self.clock() - self._loaded_at < REFRESH_SECONDS:
                return
            self._refreshing = True
        if self.background:
            threading.Thread(target=self.refresh, name='crawler-ip-ranges', daemon=True).start()
        else:
            self.refresh()

    def verified(self, ip, user_agent):
        """The crawler name when the User-Agent names it and the address is in its published list."""
        name = claimed(user_agent)
        if not name or not ip:
            return None
        self._maybe_refresh()
        key = (name, ip)
        with self._lock:
            if key in self._seen:
                return name if self._seen[key] else None
            networks = self._ranges.get(name, ())
        try:
            address = ipaddress.ip_address(str(ip).split('%', 1)[0])
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            ok = any(address.version == n.version and address in n for n in networks)
        except ValueError:
            ok = False
        with self._lock:
            if len(self._seen) >= CACHE_LIMIT:
                self._seen.clear()
            self._seen[key] = ok
        return name if ok else None


def _fetch(url):
    import httpx
    with httpx.Client(timeout=10.0, follow_redirects=True, headers={'User-Agent': 'AgentConcierge-crawler-verify/1.0'}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


_VERIFIER = None
_VERIFIER_LOCK = threading.Lock()


def verifier():
    global _VERIFIER
    with _VERIFIER_LOCK:
        if _VERIFIER is None:
            _VERIFIER = Verifier()
        return _VERIFIER


def verified(ip, user_agent):
    return verifier().verified(ip, user_agent) if claimed(user_agent) else None
