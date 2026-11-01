"""Bounded, local destinations for customer sign-in continuity."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

DEFAULT = '/customer/workspaces'
_PAGE = re.compile(r'/customer/(?:workspaces|workflows|organizations|plan|support|provider-connections|organizations/ws_[a-f0-9]{32}/(?:flows|build|connections))')


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
    if parsed.scheme or parsed.netloc or not _PAGE.fullmatch(parsed.path):
        return DEFAULT
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if query and (len(query) != 1 or query[0][0] != 'workspace'
                  or not re.fullmatch(r'ws_[a-f0-9]{32}', query[0][1])):
        return DEFAULT
    if parsed.fragment and parsed.fragment not in ('account', 'detail', 'templates'):
        return DEFAULT
    return parsed.path + ('?' + urlencode(query) if query else '') + ('#' + parsed.fragment if parsed.fragment else '')


def sign_in_location(request):
    target = destination(request.url.path + ('?' + request.url.query if request.url.query else ''))
    return '/customer/sign-in' + ('?' + urlencode({'next': target}) if target != DEFAULT else '')
