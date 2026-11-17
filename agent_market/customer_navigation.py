"""Bounded, local destinations for customer sign-in continuity."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

DEFAULT = '/customer/workspaces'
_PAGE = re.compile(r'/customer/(?:workspaces|workflows|organizations|plan|support|provider-connections|provider-claims|organizations/ws_[a-f0-9]{32}/(?:flows|build|connections))')

# Pages outside /customer/ a sign-in may return to, matched exactly (11-17 AD Coin audit F-A1: the advertiser
# workspace links to sign-in, and without this the person landed on /customer/workspaces with no way back).
_EXACT = frozenset({'/ad-coin/v2'})


def destination(value):
    """Accept known read-only pages, one workspace selector and known sections."""
    if not isinstance(value, str) or len(value) > 512 or '%' in value or '\\' in value:
        return DEFAULT
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        return DEFAULT
    try:
        parsed = urlsplit(value)
    except ValueError:
        return DEFAULT
    if parsed.scheme or parsed.netloc:
        return DEFAULT
    if parsed.path in _EXACT:        # exactly this path: no query, no fragment, nothing after it
        return parsed.path if not parsed.query and not parsed.fragment and value == parsed.path else DEFAULT
    if not _PAGE.fullmatch(parsed.path):
        return DEFAULT
    query = parse_qsl(parsed.query, keep_blank_values=True)
    # Provider claims (docs/PROVIDER_SELF_CLAIM.md): the agent page's "Are you the provider?" entry returns to the
    # claim page for that one agent id after sign-in.
    claim_agent = (parsed.path == '/customer/provider-claims' and len(query) == 1 and query[0][0] == 'agent'
                   and re.fullmatch(r'[1-9][0-9]{0,11}', query[0][1]))
    if query and not claim_agent and (len(query) != 1 or query[0][0] != 'workspace'
                                      or not re.fullmatch(r'ws_[a-f0-9]{32}', query[0][1])):
        return DEFAULT
    if parsed.fragment and parsed.fragment not in ('account', 'detail', 'templates'):
        return DEFAULT
    return parsed.path + ('?' + urlencode(query) if query else '') + ('#' + parsed.fragment if parsed.fragment else '')


def sign_in_location(request):
    target = destination(request.url.path + ('?' + request.url.query if request.url.query else ''))
    return '/customer/sign-in' + ('?' + urlencode({'next': target}) if target != DEFAULT else '')
