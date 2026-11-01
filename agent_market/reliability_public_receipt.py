"""Separately mounted, opt-in publication of fixed metadata receipts.

No application imports or mounts this factory automatically. A trusted caller
must supply bounded local callbacks that read current projection disclosure,
authority and revocation on every call. Returning a projection is not approval:
the disclosure callback must explicitly approve its exact hash and audience.
Signing and offline verification remain in reliability_portable_receipt.
"""
import base64
from dataclasses import dataclass
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .reliability_portable_receipt import (
    PortableReceiptIssuer, ReceiptInvalid, SigningConfig, _canonical, _clock,
    _projection)

PROFILE = 'public-portable-metadata-receipt-v1'
HEADERS = {
    'Cache-Control': 'no-store, max-age=0',
    'Pragma': 'no-cache',
    'X-Robots-Tag': 'noindex, nofollow, noarchive',
    'Content-Security-Policy': "default-src 'none'; script-src 'none'; frame-ancestors 'none'; sandbox",
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
}


@dataclass(frozen=True, repr=False)
class DisclosureApproval:
    """Current explicit approval of this exact public disclosure, not quality."""
    public_ref: str
    audience: str
    projection_sha256: str
    expires_at: int
    authority_revision: int
    disclosure_revision: int
    revocation_revision: int
    authorized: bool


@dataclass(frozen=True, repr=False)
class KeyPublicationApproval:
    """Current permission to publish a selected public key and its revocation."""
    issuer: str
    key_id: str
    public_key_sha256: str
    expires_at: int
    revision: int
    revoked: bool


def _future(value, now):
    return type(value) is int and now < value <= now + 300


def _revision(value):
    return type(value) is int and 0 < value < 2**53


def _host(value):
    if type(value) is not str or not 1 <= len(value) <= 260:
        raise ReceiptInvalid('Configure explicit trusted hosts.')
    try:
        parsed = urlsplit('https://' + value)
        if (not parsed.hostname or parsed.netloc != value or value != value.lower()
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,251}', parsed.hostname)):
            raise ValueError()
        parsed.port
    except ValueError:
        raise ReceiptInvalid('Configure explicit trusted hosts.') from None
    return value


class _ReadLimit:
    """Bounded peer buckets; forwarding headers never select a bucket."""
    def __init__(self, limit):
        self.limit, self.lock, self.buckets = limit, threading.Lock(), {}

    def allow(self, peer):
        minute = int(time.monotonic() // 60)
        with self.lock:
            self.buckets = {key: value for key, value in self.buckets.items() if value[0] == minute}
            value = self.buckets.get(peer)
            if value is None:
                if len(self.buckets) >= 1024:
                    return False
                value = (minute, 0)
            self.buckets[peer] = (minute, value[1] + 1)
            return value[1] < self.limit


def create_trust_app(config=None, *, projection_source=None, disclosure_authorizer=None,
                     key_status_source=None, allowed_hosts=(), requests_per_minute=60,
                     clock=time.time):
    """Build a separate ASGI app without publishing or generating any key.

    ``projection_source(public_ref)`` must check current disclosure, authority
    and revocation and return only the existing fixed projection, or deny.
    ``disclosure_authorizer(public_ref, audience, projection_sha256)`` must read
    current authority and return an exact DisclosureApproval. A boolean, legacy
    consent flag or retained approval is insufficient.
    ``key_status_source(issuer, key_id, public_key_sha256)`` must read current
    publication permission and revocation and return KeyPublicationApproval.
    Callbacks are trusted, bounded local reads. They are called again before a
    receipt response; a changed projection, revision or approval fails closed.
    This source factory confers no deployment, independent quality or SLA claim.
    """
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    enabled = config is not None
    if enabled:
        if (type(config) is not SigningConfig
                or not all(callable(item) for item in (projection_source, disclosure_authorizer, key_status_source, clock))
                or type(allowed_hosts) is not tuple or not 1 <= len(allowed_hosts) <= 10
                or any(type(item) is not str for item in allowed_hosts)
                or len(set(allowed_hosts)) != len(allowed_hosts)
                or type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 600):
            raise ReceiptInvalid('Configure explicit current publication authority.')
        hosts = frozenset(_host(value) for value in allowed_hosts)
    else:
        hosts = frozenset()
    limiter = _ReadLimit(requests_per_minute if enabled else 1)

    def unavailable():
        return JSONResponse({'detail': 'Not found.'}, status_code=404, headers=HEADERS)

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if not enabled:
            return unavailable()
        host_fields = [value for name, value in request.scope.get('headers', ()) if name.lower() == b'host']
        if len(host_fields) != 1 or request.headers.get('host') not in hosts or request.url.scheme != 'https':
            return unavailable()
        peer = request.client.host if request.client else ''
        if not limiter.allow(peer):
            return JSONResponse({'detail': 'Request limit reached.'}, status_code=429,
                                headers={**HEADERS, 'Retry-After': '60'})
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers[name] = value
        return response

    if not enabled:
        return app

    public_bytes = config.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_hash = hashlib.sha256(public_bytes).hexdigest()
    public_x = base64.urlsafe_b64encode(public_bytes).rstrip(b'=').decode('ascii')

    def key_approval(now, *, active):
        value = key_status_source(config.issuer, config.key_id, public_hash)
        if (type(value) is not KeyPublicationApproval or value.issuer != config.issuer
                or value.key_id != config.key_id or value.public_key_sha256 != public_hash
                or not _future(value.expires_at, now) or not _revision(value.revision)
                or type(value.revoked) is not bool or (active and value.revoked)):
            raise ReceiptInvalid('Current public key permission is unavailable.')
        return value

    def disclosure(public_ref, audience, now):
        projection = _projection(projection_source(public_ref), now)
        if projection['subject_ref'] != public_ref:
            raise ReceiptInvalid('The sanitized projection subject changed.')
        projection_hash = hashlib.sha256(_canonical(projection)).hexdigest()
        approval = disclosure_authorizer(public_ref, audience, projection_hash)
        if (type(approval) is not DisclosureApproval or approval.public_ref != public_ref
                or approval.audience != audience or approval.projection_sha256 != projection_hash
                or approval.authorized is not True or not _future(approval.expires_at, now)
                or not all(_revision(value) for value in (approval.authority_revision,
                    approval.disclosure_revision, approval.revocation_revision))):
            raise ReceiptInvalid('Current explicit public disclosure permission is unavailable.')
        return projection, approval

    def key_status(value, now):
        return {'key_id': config.key_id, 'revoked': value.revoked,
                'revision': value.revision, 'checked_at': int(now), 'expires_at': value.expires_at}

    @app.get('/v1/receipts/{public_ref}')
    def receipt(public_ref: str, request: Request):
        query = list(request.query_params.multi_items())
        if (not re.fullmatch(r'public_[0-9a-f]{32}', public_ref)
                or len(query) != 1 or query[0][0] != 'audience'
                or query[0][1] not in config.audiences):
            return unavailable()
        audience = query[0][1]
        try:
            now = _clock(clock())
            key = key_approval(now, active=True)
            projection, approval = disclosure(public_ref, audience, now)
            ttl = min(60, int(approval.expires_at - now), int(key.expires_at - now))
            issuer = PortableReceiptIssuer(config, projection_source=lambda _: projection)
            raw, signature = issuer.issue(public_ref, audience, ttl_seconds=ttl, now=now)
            current = _clock(clock())
            if current < now or key_approval(current, active=True) != key:
                return unavailable()
            fresh_projection, fresh_approval = disclosure(public_ref, audience, current)
            if fresh_projection != projection or fresh_approval != approval or current >= json.loads(raw)['expires_at']:
                return unavailable()
            return JSONResponse({'profile': PROFILE, 'receipt': json.loads(raw), 'signature': signature,
                                 'key_status': key_status(key, current)}, headers=HEADERS)
        except Exception:
            # Denial details and trusted callback exceptions are never public.
            return unavailable()

    @app.get('/.well-known/jwks.json')
    def jwks(request: Request):
        if request.query_params:
            return unavailable()
        try:
            now = _clock(clock())
            key = key_approval(now, active=False)
            current = _clock(clock())
            if current < now or key_approval(current, active=False) != key:
                return unavailable()
            keys = [] if key.revoked else [{'kty': 'OKP', 'crv': 'Ed25519', 'use': 'sig',
                                            'alg': 'EdDSA', 'kid': config.key_id, 'x': public_x}]
            return JSONResponse({'keys': keys, 'key_status': key_status(key, current)}, headers=HEADERS)
        except Exception:
            return unavailable()

    @app.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nDisallow: /\n', media_type='text/plain', headers=HEADERS)

    return app
