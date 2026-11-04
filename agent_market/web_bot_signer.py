"""Web Bot Auth: sign outgoing collector requests so providers can tell this crawler from impostors.

Follows the IETF web-bot-auth drafts on RFC 9421 HTTP message signatures (11-04):
  Signature-Agent: "https://agentconcierge.biz"
  Signature-Input: sig1=("@authority" "signature-agent");created=..;expires=..;keyid="<JWK thumbprint>";
                   alg="ed25519";nonce="..";tag="web-bot-auth"
  Signature:       sig1=:<base64 Ed25519 signature>:
The public key is published at /.well-known/http-message-signatures-directory. The private key stays in
gateway-data/ (never committed) and WEB_BOT_AUTH_KEY_FILE names it; without it nothing is signed.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIGNATURE_AGENT = 'https://agentconcierge.biz'
DIRECTORY_PATH = '/.well-known/http-message-signatures-directory'
DIRECTORY_MEDIA_TYPE = 'application/http-message-signatures-directory+json'
DEFAULT_KEY_FILE = 'gateway-data/web-bot-auth/ed25519.pem'
LIFETIME = 300  # seconds a signature stays valid


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class Signer:
    def __init__(self, private_key, agent=SIGNATURE_AGENT):
        self.key = private_key
        self.agent = agent
        raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.jwk = {'kty': 'OKP', 'crv': 'Ed25519', 'x': _b64url(raw)}
        # RFC 7638 thumbprint over the required members in lexical order.
        canonical = json.dumps({'crv': 'Ed25519', 'kty': 'OKP', 'x': self.jwk['x']}, separators=(',', ':'))
        self.keyid = _b64url(hashlib.sha256(canonical.encode()).digest())

    @classmethod
    def from_file(cls, path):
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError('web bot auth key must be Ed25519')
        return cls(key)

    def _sign(self, components, values, tag, now=None, nonce=None):
        created = int(now if now is not None else time.time())
        params = ('(' + ' '.join('"' + c + '"' for c in components) + ')'
                  + f';created={created};expires={created + LIFETIME};keyid="{self.keyid}";alg="ed25519"'
                  + f';nonce="{nonce or _b64url(secrets.token_bytes(32))}";tag="{tag}"')
        lines = [f'"{c}": {values[c]}' for c in components] + [f'"@signature-params": {params}']
        signature = base64.b64encode(self.key.sign('\n'.join(lines).encode())).decode()
        return {'Signature-Input': 'sig1=' + params, 'Signature': f'sig1=:{signature}:'}

    def request_headers(self, authority, now=None, nonce=None):
        """Headers for one outgoing request to `authority` (host[:port], lower case)."""
        agent = '"' + self.agent + '"'
        return {'Signature-Agent': agent,
                **self._sign(('@authority', 'signature-agent'), {'@authority': authority.lower(), 'signature-agent': agent},
                             'web-bot-auth', now, nonce)}

    def directory(self, authority, now=None):
        """The key directory body and the response signature the draft asks the directory to carry."""
        body = json.dumps({'keys': [self.jwk]})
        return body, self._sign(('@authority',), {'@authority': authority.lower()}, 'http-message-signatures-directory', now)


_cached = {}


def signer(path=None):
    """The configured signer, or None when no key file exists (signing is then off)."""
    # Services start from a release directory, so the key is named by an absolute path in the environment.
    path = path or os.environ.get('WEB_BOT_AUTH_KEY_FILE')
    if not path or os.environ.get('WEB_BOT_AUTH', '1') == '0' or not Path(path).is_file():
        return None
    stamp = Path(path).stat().st_mtime
    if _cached.get('path') != path or _cached.get('stamp') != stamp:
        _cached.update(path=path, stamp=stamp, signer=Signer.from_file(path))
    return _cached['signer']


def httpx_hooks(path=None):
    """event_hooks for an httpx Client: sign every outgoing request when a key is configured."""
    def sign(request):
        current = signer(path)
        if current is not None:
            request.headers.update(current.request_headers(request.url.netloc.decode('ascii')))
    return {'request': [sign]}


def create_key(path=DEFAULT_KEY_FILE):
    """Write a new Ed25519 private key (mode 600). Refuses to overwrite an existing key."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption())
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(pem)
    return Signer.from_file(target)


if __name__ == '__main__':
    import sys
    created = create_key(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEY_FILE)
    print('created web bot auth key', created.keyid)
