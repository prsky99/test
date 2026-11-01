"""Server-owned consent, registration fields and public endpoint validation."""
import ipaddress
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpcore
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..broker.categories import CATEGORIES
from .http_security import _resolve_addresses

TERMS_VERSION = '2026.1'
PRIVACY_VERSION = '2026.1'
CONSENT_WINDOW = 600
NETWORKS = ('base', 'ethereum', 'solana')
NETWORK_ALIASES = {'base': 'base', 'eip155:8453': 'base', 'ethereum': 'ethereum',
    'mainnet': 'ethereum', 'eip155:1': 'ethereum', 'solana': 'solana',
    'solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp': 'solana'}


class PublicRequestError(HTTPException):
    def __init__(self, field, message, *, allowed=None, status=400, code='INVALID_INPUT', headers=None):
        super().__init__(status, message, headers=headers)
        self.field, self.allowed, self.code = field, allowed, code


async def public_error_response(request, error):
    from http import HTTPStatus
    body = {'type':'about:blank','title':HTTPStatus(error.status_code).phrase,'status':error.status_code,
            'detail': error.detail, 'field': error.field, 'error_code': error.code}
    if error.allowed is not None:
        body['allowed_values'] = list(error.allowed)
    headers = {'Cache-Control': 'no-store', **(error.headers or {})}
    if error.status_code == 429 and 'RateLimit-Policy' in headers:
        headers['RateLimit'] = headers['RateLimit-Policy'].split(';',1)[0]+';r=0;t='+headers.get('Retry-After','60')
    return JSONResponse(body, status_code=error.status_code, headers=headers, media_type='application/problem+json')


def contains_controls(value, *, multiline=False):
    return any((unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp'))
        and not (multiline and c in '\t\r\n') for c in value)


def text_field(value, field, minimum, maximum, *, multiline=False, status=400):
    if type(value) is not str or contains_controls(value, multiline=multiline):
        raise PublicRequestError(field, 'Use text without control characters for ' + field + '.', status=status)
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise PublicRequestError(field, field + ' must contain ' + str(minimum) + ' to ' + str(maximum) + ' characters.', status=status)
    return value


def legal_consent(data, *, now=None):
    now = time.time() if now is None else now
    value = data.get('legal_consent')
    if type(value) is not dict or value.get('agreed') is not True:
        raise PublicRequestError('legal_consent', 'Affirmative agreement to the current Terms and Privacy Policy is required.', code='CONSENT_REQUIRED')
    if value.get('tos_version') != TERMS_VERSION or value.get('privacy_version') != PRIVACY_VERSION:
        raise PublicRequestError('legal_consent', 'Review the current Terms and Privacy Policy before submitting.', code='CONSENT_VERSION_MISMATCH')
    claimed = value.get('agreed_at')
    try:
        if type(claimed) is not str or len(claimed)>48:
            raise ValueError()
        stamp = datetime.fromisoformat(claimed.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        seconds = stamp.timestamp()
        if not math.isfinite(seconds) or abs(now-seconds)>CONSENT_WINDOW:
            raise ValueError()
    except (ValueError, OverflowError, OSError):
        raise PublicRequestError('legal_consent', 'Refresh the agreement and submit again; its timestamp must be within ten minutes of receipt.', code='CONSENT_EXPIRED') from None
    gpc = value.get('gpc_active', False)
    if type(gpc) is not bool:
        raise PublicRequestError('legal_consent', 'The privacy signal must be a boolean.')
    return {'agreed': True, 'tos_version': TERMS_VERSION, 'privacy_version': PRIVACY_VERSION,
        'claimed_agreed_at': stamp.astimezone(timezone.utc).isoformat(),
        'received_at': now, 'gpc_active': gpc, 'scope': 'public_agent_registration'}


def network(value):
    if type(value) is not str or value not in NETWORK_ALIASES:
        raise PublicRequestError('networks', 'Choose a supported network.', allowed=NETWORKS)
    return NETWORK_ALIASES[value]


def wallet(value, networks):
    if value is None or value == '':
        return None
    if type(value) is not str or contains_controls(value):
        raise PublicRequestError('pay_to', 'Provide a valid recipient address for the selected network.')
    value = value.strip()
    if not networks or ('solana' in networks and len(set(networks))>1):
        raise PublicRequestError('pay_to', 'Choose networks that use the same recipient address format.')
    if 'solana' not in networks:
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', value) or int(value[2:], 16)==0:
            raise PublicRequestError('pay_to', 'Use a nonzero 20-byte EVM recipient address.')
        return value.lower()
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    if not 32 <= len(value) <= 44 or any(c not in alphabet for c in value):
        raise PublicRequestError('pay_to', 'Use a valid Solana recipient address.')
    number = 0
    for c in value:
        number = number*58 + alphabet.index(c)
    size = (number.bit_length()+7)//8 + len(value)-len(value.lstrip('1'))
    if size != 32 or not number:
        raise PublicRequestError('pay_to', 'Use a valid nonzero Solana recipient address.')
    return value


def fields(data):
    allowed = {'kind','url','name','description','category','networks','price_usdc','pay_to','method','details','legal_consent'}
    if type(data) is not dict or set(data)-allowed:
        raise PublicRequestError('request', 'Use only the supported registration fields.', allowed=sorted(allowed))
    kind = data.get('kind')
    if kind not in ('mcp', 'a2a', 'x402'):
        raise PublicRequestError('kind', 'Choose a supported protocol.', allowed=('a2a','mcp','x402'))
    category = data.get('category')
    if type(category) is not str or category not in CATEGORIES:
        raise PublicRequestError('category', 'Choose a category from the current list.', allowed=sorted(CATEGORIES))
    name = text_field(data.get('name'), 'name', 2, 100)
    description = text_field(data.get('description'), 'description', 5, 2000, multiline=True)
    raw_networks = data.get('networks', ['base'] if kind=='x402' else [])
    if type(raw_networks) is not list or len(raw_networks)>3:
        raise PublicRequestError('networks', 'Use a list of supported networks.', allowed=NETWORKS)
    networks = list(dict.fromkeys(network(v) for v in raw_networks))
    if kind=='x402' and not networks:
        raise PublicRequestError('networks', 'Choose a supported network.', allowed=NETWORKS)
    price = data.get('price_usdc', 0)
    if type(price) is not int or not 0 <= price <= 2**53-1:
        raise PublicRequestError('price_usdc', 'Use a non-negative integer amount in micro-USDC.')
    pay_to = wallet(data.get('pay_to'), networks)
    method = data.get('method', 'GET' if kind=='x402' else 'POST')
    if method not in ('GET','POST') or kind!='x402' and method!='POST':
        raise PublicRequestError('method', 'Choose a supported request method.', allowed=('GET','POST') if kind=='x402' else ('POST',))
    if 'details' in data and type(data['details']) is not dict:
        raise PublicRequestError('details', 'Endpoint metadata must be an object.')
    return {**data, 'name':name,'description':description,'networks':networks,'price_usdc':price,'pay_to':pay_to,'method':method}


def public_endpoint(value, *, public_origin='https://agentconcierge.biz'):
    value = text_field(value, 'url', 1, 1000)
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise PublicRequestError('url', 'Do not include a username or password in the endpoint URL.', code='URL_CREDENTIALS')
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.fragment or '\\' in value:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme=='https' else 80)
        host = parsed.hostname.rstrip('.').encode('idna').decode().lower()
        own = (urlsplit(public_origin).hostname or 'agentconcierge.biz').rstrip('.').lower()
        if host in ('agentconcierge.biz', own) or host.endswith('.agentconcierge.biz') or host.endswith('.'+own):
            raise PublicRequestError('url', 'This service and its gateways cannot be registered as external agents.', code='SELF_ENDPOINT')
    except (ValueError, UnicodeError):
        raise PublicRequestError('url', 'Use a valid public HTTP or HTTPS endpoint URL.', code='INVALID_URL') from None
    try:
        addresses = _resolve_addresses(host, port, 3)
    except httpcore.TimeoutException:
        raise PublicRequestError('url', 'The hostname lookup timed out. Check the address and try again.', code='DNS_TIMEOUT') from None
    except (httpcore.NetworkError, OSError):
        raise PublicRequestError('url', 'The hostname could not be resolved. Check the endpoint address.', code='DNS_FAILED') from None
    try:
        if not addresses or any(not ipaddress.ip_address(a.split('%')[0]).is_global for a in addresses):
            raise ValueError()
    except ValueError:
        raise PublicRequestError('url', 'Private or internal network destinations are not allowed.', code='PRIVATE_DESTINATION') from None
    return value
