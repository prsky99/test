"""Provider ownership proof (11-11, PM decision 2): no e-mail, no password, only control of the host.

The token for a host is HMAC-SHA256(OWNER_PROOF_SECRET, host): it is deterministic, so issuing it stores
nothing. A provider proves control by serving it at https://<host>/.well-known/agentconcierge-verify.txt
or in a DNS TXT record at _agentconcierge.<host>. Verification reads exactly that one file (public address
check, no redirects, 4 KB, 3 s) or asks a DNS-over-HTTPS resolver; it never sends credentials.

Recording a verified owner and hiding opted-out listings need the agentcon_owner table (waiting for the
user's approval, deploy/growth/owner-claims). Until OWNER_PROOF_STORE=1 the answer says stored: false.
"""
import hashlib
import hmac
import os
import threading
import time

import httpx

from .agent_check import CheckError, normalize

WELL_KNOWN = '/.well-known/agentconcierge-verify.txt'
DNS_PREFIX = '_agentconcierge.'
TOKEN_PREFIX = 'agentconcierge-verify='
DOH = 'https://cloudflare-dns.com/dns-query'
MAX_BYTES = 4096
TIMEOUT = 3.0
PER_IP_HOUR = 5
PER_HOST_SECONDS = 600


class ProofError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def secret():
    value = os.environ.get('OWNER_PROOF_SECRET', '')
    return value.encode() if len(value) >= 32 else None


def host_of(raw):
    raw = (raw or '').strip()
    try:
        _, host = normalize(raw if '://' in raw else 'https://' + raw)
    except CheckError as error:
        raise ProofError(str(error)) from None
    return host


def token(host):
    key = secret()
    if key is None:
        raise ProofError('Ownership proof is not available yet.', 503)
    return TOKEN_PREFIX + hmac.new(key, host.encode(), hashlib.sha256).hexdigest()[:40]


def instructions(raw):
    host = host_of(raw)
    value = token(host)
    return {'host': host, 'token': value,
            'well_known': {'url': f'https://{host}{WELL_KNOWN}', 'content': value},
            'dns_txt': {'name': DNS_PREFIX + host, 'value': value},
            'verify': {'method': 'POST', 'path': '/api/agent/v1/owner/verify', 'body': {'host': host}},
            'note': 'Put the token in either place, then ask us to verify. We never ask for e-mail or a password.'}


class Limiter:
    def __init__(self, clock=time.time):
        self.clock, self.lock, self.ips, self.hosts = clock, threading.Lock(), {}, {}

    def allow(self, ip, host):
        now = self.clock()
        with self.lock:
            recent = [t for t in self.ips.get(ip, []) if now - t < 3600]
            if len(recent) >= PER_IP_HOUR or now - self.hosts.get(host, -1e9) < PER_HOST_SECONDS:
                self.ips[ip] = recent
                return False
            self.ips[ip] = recent + [now]
            self.hosts[host] = now
            if len(self.ips) > 10000:
                self.ips = {k: v for k, v in self.ips.items() if v and now - v[-1] < 3600}
            return True


LIMITER = Limiter()


def _well_known(host, client):
    from agent_market.broker.discovery import DiscoveryError, check_public_url
    url = f'https://{host}{WELL_KNOWN}'
    try:
        check_public_url(url)
    except DiscoveryError:
        return False
    try:
        with client.stream('GET', url, timeout=TIMEOUT, follow_redirects=False,
                           headers={'User-Agent': 'AgentConcierge-owner-proof/1.0', 'Accept': 'text/plain'}) as response:
            if response.status_code != 200:
                return False
            body = b''
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    return False
    except httpx.HTTPError:
        return False
    return body.decode('utf-8', 'replace')


def _dns_txt(host, client):
    try:
        response = client.get(DOH, params={'name': DNS_PREFIX + host, 'type': 'TXT'}, timeout=TIMEOUT,
                              headers={'Accept': 'application/dns-json'}, follow_redirects=False)
        answers = response.json().get('Answer') or [] if response.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []
    return [str(a.get('data') or '').replace('"', '').replace(' ', '') for a in answers if a.get('type') == 16]


def verify(raw, ip, client=None, limiter=None):
    host = host_of(raw)
    expected = token(host)
    if not (limiter or LIMITER).allow(ip, host):
        raise ProofError('Too many verification requests; try again later.', 429)
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False)
    try:
        method = None
        text = _well_known(host, client)
        if text and expected in text.split():
            method = 'well_known'
        elif expected in _dns_txt(host, client):
            method = 'dns_txt'
    finally:
        if owned:
            client.close()
    return {'host': host, 'verified': method is not None, 'method': method,
            'stored': False if method else None,
            'message': ('Ownership verified. Recording it and opt-out requests open after our storage is enabled.'
                        if method else f'Token not found at https://{host}{WELL_KNOWN} or in TXT {DNS_PREFIX}{host}.')}
