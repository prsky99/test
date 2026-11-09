"""Store only coarse network and client information in security and audit records (2026-11-10).

User decision: keep personal data out even of security logs. An address is reduced to its IPv4 /24
or IPv6 /48 network, and a User-Agent to a client family. Live blocking and rate limits still use the
exact request address in memory and in security_ip_rules; only what is written to the event and audit
tables is reduced. Records are kept for RETENTION_DAYS.
"""
import ipaddress
import re

RETENTION_DAYS = 90
_BROWSERS = (('Edg/', 'Edge'), ('Firefox/', 'Firefox'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari'))
_SCRIPT = re.compile(r'^\s*([A-Za-z][A-Za-z0-9_.-]{0,30})')


def coarse_ip(value):
    """'203.0.113.0/24' or '2001:db8:1::/48' for an address; None for anything else."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > 64:
        return None
    try:
        address = ipaddress.ip_address(text.split('%', 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f'{address}/{prefix}', strict=False))


def ua_family(value):
    """A client family of at most 40 characters ('Chrome', 'curl', 'ClaudeBot', 'other'); None when empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    from .concierge.traffic import BOT, BOTS, HEADLESS, INTERNAL_UA, SCRIPT, VERIFIER, BROWSER
    bot = BOT.search(text)
    if bot:
        return next(name for name in BOTS if name.lower() == bot.group(0).lower())
    if INTERNAL_UA.search(text):
        return 'internal'
    if VERIFIER.search(text):
        return 'verifier'
    if HEADLESS.search(text):
        return 'headless'
    if BROWSER.search(text):
        return next((name for token, name in _BROWSERS if token.lower() in text.lower()), 'browser')
    if SCRIPT.search(text):
        return _SCRIPT.match(text).group(1).split('/')[0].lower()[:40]
    return 'other'
