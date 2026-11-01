"""Explicit OIDC code/PKCE customer identity and revocable BFF capabilities.

Configuration is supplied by the host, never discovered from environment values.
Customer subjects/sessions/links are independent from staff and visitor identity.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .workspace_access import (WorkspaceAccess, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid,
                               _canonical, _hash, _identity, _revision, _rows, _tree)
from .workspace_admin_events import track_auth_failure

PROFILE = 'customer-oidc-bff-v1'
AUDIENCE = 'workspace-private-bff-v1'
GITHUB_AUTHORIZATION_ISSUER = 'https://github.com/login/oauth'
# A session ends after an hour without requests and 12 hours after sign-in at the latest.
SESSION_IDLE, SESSION_MAX = 3600, 12 * 3600
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS customer_oidc_flows(id TEXT PRIMARY KEY,browser_hash TEXT NOT NULL,
       config_hash TEXT NOT NULL,sealed TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,consumed REAL)''',
    '''CREATE TABLE IF NOT EXISTS customer_identities(id TEXT PRIMARY KEY,issuer TEXT NOT NULL,
       subject_hash TEXT NOT NULL,active INTEGER NOT NULL,revision INTEGER NOT NULL,created REAL NOT NULL,
       last_login REAL NOT NULL,UNIQUE(issuer,subject_hash))''',
    '''CREATE TABLE IF NOT EXISTS customer_sessions(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,
       config_hash TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL)''',
    '''CREATE TABLE IF NOT EXISTS customer_workspace_links(workspace_id TEXT NOT NULL,customer_id TEXT NOT NULL,
       role TEXT NOT NULL,active INTEGER NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL,
       PRIMARY KEY(workspace_id,customer_id))''',
    '''CREATE TABLE IF NOT EXISTS customer_bff_tokens(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,
       customer_id TEXT NOT NULL,session_ref TEXT NOT NULL,workspace_id TEXT NOT NULL,purpose TEXT NOT NULL,
       created REAL NOT NULL,expires REAL NOT NULL,revoked REAL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)


def _time():
    value = time.time()
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise WorkspaceConflict()
    return value


def _b64(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decode(value, maximum=65536):
    if type(value) is not str or len(value) > maximum or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise WorkspaceDenied()
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        if _b64(raw) != value:
            raise WorkspaceDenied()
        return raw
    except (ValueError, TypeError):
        raise WorkspaceDenied() from None


def _object(raw):
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                raise WorkspaceDenied()
            value[key] = child
        return value
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(WorkspaceDenied()))
        if type(value) is not dict:
            raise WorkspaceDenied()
        _tree(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkspaceDenied() from None


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    redirect_uri: str
    client_secret: str | None = field(default=None, repr=False)

    def validate(self):
        from .concierge.recommendation_security import usable_endpoint
        for value in (self.issuer, self.authorization_endpoint, self.token_endpoint, self.jwks_uri, self.redirect_uri):
            if (not usable_endpoint(value) or urlsplit(value).scheme != 'https'
                    or urlsplit(value).query or urlsplit(value).fragment):
                raise WorkspaceInvalid()
        if (self.issuer != 'https://accounts.google.com'
                or self.authorization_endpoint != 'https://accounts.google.com/o/oauth2/v2/auth'
                or self.token_endpoint != 'https://oauth2.googleapis.com/token'
                or self.jwks_uri != 'https://www.googleapis.com/oauth2/v3/certs'
                or not re.fullmatch(r'[A-Za-z0-9._~-]{1,200}\.apps\.googleusercontent\.com', self.client_id)
                or type(self.client_secret) is not str or not 1 <= len(self.client_secret) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in self.client_secret)):
            raise WorkspaceInvalid()
        return self


def google_config(client_id, redirect_uri, client_secret):
    return OIDCConfig('https://accounts.google.com', client_id,
        'https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token',
        'https://www.googleapis.com/oauth2/v3/certs', redirect_uri, client_secret).validate()


def load_google_config(values=None):
    """Only these explicitly named settings are read; nothing is inferred."""
    if values is None:
        import os
        values = os.environ
    configured = [values.get(name) for name in ('GOOGLE_OIDC_CLIENT_ID', 'GOOGLE_OIDC_REDIRECT_URI', 'GOOGLE_OIDC_CLIENT_SECRET')]
    if not all(configured):
        return None
    return google_config(configured[0], configured[1], configured[2])


@dataclass(frozen=True)
class GitHubConfig:
    client_id: str
    redirect_uri: str
    client_secret: str = field(repr=False)
    issuer: str = 'https://github.com'
    authorization_endpoint: str = 'https://github.com/login/oauth/authorize'
    token_endpoint: str = 'https://github.com/login/oauth/access_token'
    user_endpoint: str = 'https://api.github.com/user'

    def validate(self):
        from .concierge.recommendation_security import usable_endpoint
        if (not re.fullmatch('[A-Za-z0-9._-]{1,200}', self.client_id)
                or not usable_endpoint(self.redirect_uri) or urlsplit(self.redirect_uri).scheme != 'https'
                or urlsplit(self.redirect_uri).query or self.issuer != 'https://github.com'
                or self.authorization_endpoint != 'https://github.com/login/oauth/authorize'
                or self.token_endpoint != 'https://github.com/login/oauth/access_token'
                or self.user_endpoint != 'https://api.github.com/user'
                or type(self.client_secret) is not str or not 1 <= len(self.client_secret) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in self.client_secret)):
            raise WorkspaceInvalid()
        return self


def load_github_config(values=None):
    if values is None:
        import os
        values = os.environ
    configured = [values.get(name) for name in ('GITHUB_OAUTH_CLIENT_ID', 'GITHUB_OAUTH_REDIRECT_URI', 'GITHUB_OAUTH_CLIENT_SECRET')]
    return GitHubConfig(*configured).validate() if all(configured) else None


def customer_identity_for(store, key):
    """The host explicitly calls this factory to read the six named settings."""
    providers = []
    for loader in (load_google_config, load_github_config):
        try:
            providers.append(loader())
        except (WorkspaceInvalid, ValueError, TypeError, UnicodeError):
            # Configuration errors disable this provider, never the whole site.
            providers.append(None)
    return CustomerIdentity(store, key, providers[0], github_config=providers[1])


@dataclass(frozen=True, repr=False)
class CustomerActor:
    customer_id: str
    session_ref: str
    token_ref: str | None = None

    def __repr__(self):
        return '<CustomerSession private>'


class CustomerIdentity:
    def __init__(self, store, key, config=None, http=None, *, github_config=None):
        if (type(key) is not bytes or len(key) < 32 or config is not None and type(config) is not OIDCConfig
                or github_config is not None and type(github_config) is not GitHubConfig):
            raise WorkspaceInvalid()
        self.store, self.http = store, http
        self.config = config.validate() if config else None
        self.github_config = github_config.validate() if github_config else None
        self.key = hmac.new(key, PROFILE.encode(), hashlib.sha256).digest()
        self.box = Fernet(base64.urlsafe_b64encode(hmac.new(self.key, b'flow-sealing', hashlib.sha256).digest()))
        self.google_config_hash = self._mac('configuration', _canonical(vars(config))) if config else None
        self.github_config_hash = self._mac('configuration', _canonical(vars(github_config))) if github_config else None
        self.config_hash = self._mac('configuration-bundle', _canonical([self.google_config_hash, self.github_config_hash])) if config or github_config else None
        with self.tx() as db:
            for statement in SCHEMA:
                db.execute(statement)

    @contextmanager
    def tx(self):
        with self.store._lock:
            db = self.store._db
            if db.in_transaction:
                raise WorkspaceConflict()
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException as error:
                db.rollback()
                if isinstance(error, sqlite3.Error):
                    raise WorkspaceConflict() from None
                raise

    @contextmanager
    def read_tx(self):
        """Reads skip the global writer lock on PostgreSQL so a busy writer cannot time them out."""
        if getattr(self.store, 'backend', '') == 'postgresql':
            with self.store.tx(readonly=True) as db:
                yield db
        else:
            with self.tx() as db:
                yield db

    def _mac(self, namespace, value):
        return hmac.new(self.key, (namespace + ':' + value).encode('utf-8'), hashlib.sha256).hexdigest()

    def _enabled(self):
        if self.config is None and self.github_config is None:
            raise WorkspaceDenied()

    def _configuration(self, provider):
        if provider == 'google' and self.config is not None:
            return self.config, self.google_config_hash
        if provider == 'github' and self.github_config is not None:
            return self.github_config, self.github_config_hash
        raise WorkspaceDenied()

    def _issuer_configuration(self, issuer):
        if issuer == 'https://accounts.google.com':
            return self._configuration('google')[1]
        if issuer == 'https://github.com':
            return self._configuration('github')[1]
        raise WorkspaceDenied()

    def options(self):
        providers = [{'id': 'google', 'label': 'Google', 'configured': self.config is not None},
                     {'id': 'github', 'label': 'GitHub', 'configured': self.github_config is not None}]
        return {'profile': PROFILE, 'configured': any(item['configured'] for item in providers),
                'customer_authentication_enabled': any(item['configured'] for item in providers),
                'providers': providers, 'provider': 'google', 'standard': 'authorization_code_pkce_s256', 'bff_audience': AUDIENCE,
                'automatic_workspace_membership': False, 'provider_ownership_inferred': False}

    def begin(self, browser, provider='google', return_to=None):
        config, config_hash = self._configuration(provider)
        if type(browser) is not str or not re.fullmatch('[a-f0-9]{64}', browser):
            raise WorkspaceInvalid()
        now = _time()
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with self.tx() as db:
            from .workspace_admin_events import emit
            emit(self.store, db, 'auth.begin', provider=provider)
            # Keep consumed/expired hashes briefly; no replayed flow is reopened.
            db.execute('DELETE FROM customer_oidc_flows WHERE expires<?', (now - 86400,))
            if db.execute('SELECT COUNT(*) FROM customer_oidc_flows').fetchone()[0] >= 1000:
                raise WorkspaceConflict()
            payload = {'nonce': nonce, 'verifier': verifier, 'provider': provider}
            if return_to is not None:
                from .customer_navigation import destination
                payload['return_to'] = destination(return_to)
            db.execute('INSERT INTO customer_oidc_flows VALUES(?,?,?,?,?,?,NULL)',
                       (self._mac('state', state), self._mac('browser', browser), config_hash,
                        self.box.encrypt(_canonical(payload).encode()).decode(), now, now + 300))
        arguments = {'response_type': 'code', 'client_id': config.client_id, 'redirect_uri': config.redirect_uri,
                     'scope': 'openid' if provider == 'google' else '', 'state': state,
                     'code_challenge': _b64(hashlib.sha256(verifier.encode('ascii')).digest()), 'code_challenge_method': 'S256'}
        if provider == 'google':
            arguments['nonce'] = nonce
        url = config.authorization_endpoint + '?' + urlencode(arguments)
        return {'authorization_url': url, 'expires': now + 300}

    def _request(self, method, url, **kwargs):
        from .concierge.http_security import bounded_client, outbound_operation
        with outbound_operation(8):
            client = bounded_client(self.http, limit=65536, timeout=8)
            try:
                response = client.request(method, url, **kwargs)
                if response.status_code != 200:
                    raise WorkspaceDenied()
                return _object(response.content)
            except Exception:
                raise WorkspaceDenied() from None
            finally:
                client.close()

    def _verify(self, token, nonce):
        if type(token) is not str or len(token) > 24000 or token.count('.') != 2:
            raise WorkspaceDenied()
        encoded_header, encoded_claims, encoded_signature = token.split('.')
        header, claims = _object(_decode(encoded_header)), _object(_decode(encoded_claims))
        if (header.get('alg') != 'RS256' or type(header.get('kid')) is not str or not 0 < len(header['kid']) <= 200
                or set(header) - {'alg', 'kid', 'typ'} or header.get('typ', 'JWT') != 'JWT'):
            raise WorkspaceDenied()
        keys = self._request('GET', self.config.jwks_uri).get('keys')
        if type(keys) is not list or not 0 < len(keys) <= 20:
            raise WorkspaceDenied()
        candidates = [item for item in keys if type(item) is dict and item.get('kid') == header['kid']]
        if len(candidates) != 1:
            raise WorkspaceDenied()
        jwk = candidates[0]
        try:
            if (jwk.get('kty') != 'RSA' or jwk.get('use', 'sig') != 'sig' or jwk.get('alg', 'RS256') != 'RS256'
                    or 'key_ops' in jwk and jwk['key_ops'] != ['verify']
                    or any(key in jwk for key in ('d', 'p', 'q', 'dp', 'dq', 'qi', 'oth'))):
                raise WorkspaceDenied()
            modulus, exponent = int.from_bytes(_decode(jwk['n'], 1400), 'big'), int.from_bytes(_decode(jwk['e'], 16), 'big')
            if not 2048 <= modulus.bit_length() <= 8192 or exponent != 65537:
                raise WorkspaceDenied()
            rsa.RSAPublicNumbers(exponent, modulus).public_key().verify(
                _decode(encoded_signature, 1400), (encoded_header + '.' + encoded_claims).encode('ascii'),
                padding.PKCS1v15(), hashes.SHA256())
        except Exception:
            raise WorkspaceDenied() from None
        now = _time()
        audience = claims.get('aud')
        audiences = [audience] if type(audience) is str else audience
        if (claims.get('iss') not in ('https://accounts.google.com', 'accounts.google.com') or type(audiences) is not list
                or not audiences or len(audiences) > 10 or any(type(value) is not str for value in audiences)
                or len(set(audiences)) != len(audiences) or self.config.client_id not in audiences
                or (len(audiences) > 1 or 'azp' in claims) and claims.get('azp') != self.config.client_id
                or claims.get('nonce') != nonce or type(claims.get('sub')) is not str
                or not 0 < len(claims['sub']) <= 255 or any(ord(char) < 32 for char in claims['sub'])):
            raise WorkspaceDenied()
        for field in ('iat', 'exp'):
            if type(claims.get(field)) not in (int, float) or not math.isfinite(claims[field]):
                raise WorkspaceDenied()
        if (not 0 <= claims['iat'] <= now + 30 or not now < claims['exp'] <= claims['iat'] + 86400
                or 'nbf' in claims and (type(claims['nbf']) not in (int, float)
                    or not math.isfinite(claims['nbf']) or claims['nbf'] > now)):
            raise WorkspaceDenied()
        # Google documents both issuer spellings. Normalize only after verifying
        # the signature and all claims so one subject cannot split into accounts.
        return {**claims, 'iss': self.config.issuer}

    def _consume_flow(self, state, browser, provider='google'):
        _, config_hash = self._configuration(provider)
        if (type(state) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}', state)
                or type(browser) is not str or not re.fullmatch('[a-f0-9]{64}', browser)):
            raise WorkspaceDenied()
        with self.tx() as db:
            rows = _rows(db, 'SELECT * FROM customer_oidc_flows WHERE id=?', (self._mac('state', state),))
            if (len(rows) != 1 or rows[0]['consumed'] is not None or rows[0]['expires'] <= _time()
                    or rows[0]['config_hash'] != config_hash
                    or not hmac.compare_digest(rows[0]['browser_hash'], self._mac('browser', browser))):
                raise WorkspaceDenied()
            flow = _object(self.box.decrypt(rows[0]['sealed'].encode()))
            if flow['provider'] != provider:
                raise WorkspaceDenied()
            db.execute('UPDATE customer_oidc_flows SET consumed=? WHERE id=? AND consumed IS NULL', (_time(), rows[0]['id']))
            return flow

    def cancel(self, state, browser, provider='google'):
        flow = self._consume_flow(state, browser, provider)
        return {'authenticated': False, 'cancelled': True,
                **({'return_to': flow['return_to']} if 'return_to' in flow else {})}

    @track_auth_failure
    def complete(self, state, code, browser, provider='google'):
        if type(code) is not str or not 0 < len(code) <= 2048 or any(ord(c) < 33 for c in code):
            raise WorkspaceDenied()
        config, config_hash = self._configuration(provider)
        flow = self._consume_flow(state, browser, provider)
        response = self._request('POST', config.token_endpoint, headers={'Accept': 'application/json'}, data={
            'grant_type': 'authorization_code', 'client_id': config.client_id, 'code': code,
            'client_secret': config.client_secret, 'redirect_uri': config.redirect_uri, 'code_verifier': flow['verifier']})
        if provider == 'google':
            claims = self._verify(response.get('id_token'), flow['nonce'])
        else:
            access_token = response.get('access_token')
            if (type(access_token) is not str or not re.fullmatch('[A-Za-z0-9_.-]{16,1024}', access_token)
                    or response.get('token_type', '').lower() != 'bearer'):
                raise WorkspaceDenied()
            user = self._request('GET', config.user_endpoint, headers={'Authorization': 'Bearer ' + access_token,
                'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
            if type(user.get('id')) is not int or not 0 < user['id'] < 2**63:
                raise WorkspaceDenied()
            claims = {'iss': config.issuer, 'sub': str(user['id']), 'exp': _time() + 3600}
        now = _time()
        subject_hash = self._mac('subject', claims['iss'] + '\0' + claims['sub'])
        token = 'cst_' + secrets.token_urlsafe(32)
        with self.tx() as db:
            rows = _rows(db, 'SELECT * FROM customer_identities WHERE issuer=? AND subject_hash=?', (config.issuer, subject_hash))
            if rows and rows[0]['active'] != 1:
                raise WorkspaceDenied()
            identity = rows[0]['id'] if rows else 'cu_' + secrets.token_hex(16)
            if not rows:
                if db.execute('SELECT COUNT(*) FROM customer_identities').fetchone()[0] >= 10000:
                    raise WorkspaceConflict()
                db.execute('INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)', (identity, config.issuer, subject_hash, now, now))
            else:
                db.execute('UPDATE customer_identities SET last_login=? WHERE id=?', (now, identity))
            db.execute('DELETE FROM customer_sessions WHERE expires<?', (now - 86400,))
            if db.execute('SELECT COUNT(*) FROM customer_sessions WHERE customer_id=?', (identity,)).fetchone()[0] >= 50:
                raise WorkspaceConflict()
            db.execute('INSERT INTO customer_sessions VALUES(?,?,?,?,?,NULL)',
                       (self._mac('session', token), identity, config_hash, now, now + SESSION_IDLE))
            from .workspace_admin_events import emit
            emit(self.store, db, 'auth.succeeded', customer=identity, outcome='succeeded', provider=provider)
        return {'session_token': token, 'customer_id': identity, 'expires': now + SESSION_IDLE,
                'absolute_expires': now + SESSION_MAX,
                'csrf_token': self.csrf(token), **({'return_to': flow['return_to']} if 'return_to' in flow else {})}

    def csrf(self, token):
        return self._mac('csrf', token)

    def actor(self, token):
        self._enabled()
        if type(token) is not str or not re.fullmatch('cst_[A-Za-z0-9_-]{43}', token):
            raise WorkspaceDenied()
        reference = self._mac('session', token)
        # Checking a session is a read (11-01: it used to wait on every background writer).
        with self.read_tx() as db:
            row = self._session(db, reference)
        # Each request keeps the session alive; only that write, at most once a minute, takes the writer lock.
        if min(_time() + SESSION_IDLE, row['created'] + SESSION_MAX) - row['expires'] >= 60:
            with self.tx() as db:
                row = self._session(db, reference)
                extended = min(_time() + SESSION_IDLE, row['created'] + SESSION_MAX)
                if extended - row['expires'] >= 60:
                    db.execute('UPDATE customer_sessions SET expires=? WHERE id=? AND revoked IS NULL', (extended, row['id']))
        return CustomerActor(row['customer_id'], row['id'])

    def _session(self, db, reference, customer=None):
        self._enabled()
        rows = _rows(db, '''SELECT s.*,i.active,i.issuer FROM customer_sessions s JOIN customer_identities i ON i.id=s.customer_id
             WHERE s.id=? AND s.revoked IS NULL AND s.expires>? AND i.active=1''', (reference, _time()))
        if (len(rows) != 1 or rows[0]['config_hash'] != self._issuer_configuration(rows[0]['issuer'])
                or customer is not None and rows[0]['customer_id'] != customer):
            raise WorkspaceDenied()
        return rows[0]

    def authorize(self, db, actor, ws, purpose):
        if (db is not self.store._db or not db.in_transaction or type(actor) is not CustomerActor
                or purpose not in ('read', 'execute', 'edit', 'manage')):
            raise WorkspaceDenied()
        _identity(ws, 'ws'); _identity(actor.customer_id, 'cu')
        session = self._session(db, actor.session_ref, actor.customer_id)
        rows = _rows(db, '''SELECT w.revision AS workspace_revision,l.revision AS link_revision,l.role
            FROM organization_workspaces w JOIN customer_workspace_links l ON l.workspace_id=w.id
            WHERE w.id=? AND w.active=1 AND l.customer_id=? AND l.active=1''', (ws, actor.customer_id))
        permissions = {'read': ('owner', 'editor', 'viewer', 'runner'),
                       'execute': ('owner', 'editor', 'runner'),
                       'edit': ('owner', 'editor'), 'manage': ('owner',)}
        if len(rows) != 1 or rows[0]['role'] not in permissions[purpose]:
            raise WorkspaceDenied()
        # Expanded customer roles only exist in the separate customer-owned
        # namespace; a modified legacy link never becomes staff ownership.
        exists = db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='customer_organizations'").fetchone()
        organization = db.execute('SELECT active FROM customer_organizations WHERE workspace_id=?', (ws,)).fetchone() if exists else None
        if (organization is not None and organization[0] != 1
                or rows[0]['role'] in ('owner', 'editor') and organization is None):
            raise WorkspaceDenied()
        if purpose in ('edit', 'manage') and actor.token_ref is not None:
            raise WorkspaceDenied()
        scope = {**rows[0], 'customer_id': actor.customer_id, 'workspace_id': ws, 'session_ref': actor.session_ref,
                 'session_expires': session['expires'], 'identity_config_hash': session['config_hash'],
                 'audience': AUDIENCE, 'purpose': purpose}
        if actor.token_ref is not None:
            _identity(actor.token_ref, 'cbr')
            tokens = _rows(db, 'SELECT * FROM customer_bff_tokens WHERE id=? AND revoked IS NULL AND expires>?',
                           (actor.token_ref, _time()))
            if len(tokens) != 1:
                raise WorkspaceDenied()
            token = tokens[0]
            payload = self._open_token(token)
            # The session expiry moves with activity; the token already carries its own shorter expiry.
            if any(payload.get(key) != value for key, value in scope.items() if key != 'session_expires'):
                raise WorkspaceDenied()
            scope.update(token_ref=token['id'], token_expires=token['expires'])
        return scope

    @staticmethod
    def actor_from_scope(scope):
        if type(scope) is not dict:
            raise WorkspaceDenied()
        return CustomerActor(scope['customer_id'], scope['session_ref'], scope.get('token_ref'))

    def session(self, token):
        actor = self.actor(token)
        with self.tx() as db:
            row = self._session(db, actor.session_ref, actor.customer_id)
            links = _rows(db, '''SELECT l.workspace_id,l.role,l.revision FROM customer_workspace_links l
                 JOIN organization_workspaces w ON w.id=l.workspace_id WHERE l.customer_id=? AND l.active=1 AND w.active=1
                 ORDER BY l.workspace_id LIMIT 100''', (actor.customer_id,))
            revision = db.execute('SELECT revision FROM customer_identities WHERE id=?', (actor.customer_id,)).fetchone()[0]
            return {'customer_id': actor.customer_id, 'account_revision': revision,
                    'expires': row['expires'], 'absolute_expires': row['created'] + SESSION_MAX,
                    'csrf_token': self.csrf(token), 'workspaces': links}

    def logout(self, token):
        actor = self.actor(token)
        with self.tx() as db:
            self._session(db, actor.session_ref, actor.customer_id)
            db.execute('UPDATE customer_sessions SET revoked=? WHERE id=?', (_time(), actor.session_ref))
            db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE session_ref=? AND revoked IS NULL', (_time(), actor.session_ref))
            from .workspace_admin_events import emit
            emit(self.store, db, 'session.logged_out', customer=actor.customer_id)
        return {'signed_out': True}

    def links(self, access, ws, actor):
        with access._tx(actor) as (db, _):
            access._access(ws, actor, owner=True)
            return _rows(db, 'SELECT customer_id,role,active,revision FROM customer_workspace_links WHERE workspace_id=? ORDER BY customer_id LIMIT 100', (ws,))

    def set_link(self, access, ws, body, actor):
        if (type(body) is not dict or set(body) != {'customer_id', 'role', 'active', 'revision'}
                or body['role'] not in ('viewer', 'runner') or type(body['active']) is not bool or not _revision(body['revision'], zero=True)):
            raise WorkspaceInvalid()
        _identity(body['customer_id'], 'cu')
        with access._tx(actor, write=True) as (db, _):
            access._access(ws, actor, write=True, owner=True)
            if not db.execute('SELECT 1 FROM customer_identities WHERE id=? AND active=1', (body['customer_id'],)).fetchone():
                raise WorkspaceDenied()
            rows = _rows(db, 'SELECT revision FROM customer_workspace_links WHERE workspace_id=? AND customer_id=?', (ws, body['customer_id']))
            if (rows and rows[0]['revision'] != body['revision']) or not rows and body['revision'] != 0:
                raise WorkspaceConflict()
            if not rows and db.execute('SELECT COUNT(*) FROM customer_workspace_links WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            revision = body['revision'] + 1
            db.execute('''INSERT INTO customer_workspace_links VALUES(?,?,?,?,?,?) ON CONFLICT(workspace_id,customer_id)
                DO UPDATE SET role=excluded.role,active=excluded.active,revision=excluded.revision,updated=excluded.updated''',
                (ws, body['customer_id'], body['role'], int(body['active']), revision, _time()))
            db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE workspace_id=? AND customer_id=? AND revoked IS NULL',
                       (_time(), ws, body['customer_id']))
            access._audit(db, actor, ws, 'customer.link', body['customer_id'], revision)
            return {'customer_id': body['customer_id'], 'role': body['role'], 'active': body['active'], 'revision': revision}

    def issue_token(self, token, ws, purpose):
        if purpose not in ('read', 'execute'):
            raise WorkspaceDenied()
        actor = self.actor(token)
        now, raw = _time(), 'cbt_' + secrets.token_urlsafe(32)
        with self.tx() as db:
            scope = self.authorize(db, actor, ws, purpose)
            if db.execute('SELECT COUNT(*) FROM customer_bff_tokens WHERE session_ref=? AND revoked IS NULL AND expires>?',
                          (actor.session_ref, now)).fetchone()[0] >= 20:
                raise WorkspaceConflict()
            db.execute('DELETE FROM customer_bff_tokens WHERE expires<?', (now - 86400,))
            identity = 'cbr_' + secrets.token_hex(16)
            payload = {**scope, 'id': identity, 'profile': PROFILE, 'config_hash': scope['identity_config_hash'],
                       'created': now, 'expires': min(now + 300, scope['session_expires'])}
            db.execute('INSERT INTO customer_bff_tokens VALUES(?,?,?,?,?,?,?,?,NULL,?,?)',
                (identity, self._mac('bff', raw), actor.customer_id, actor.session_ref, ws, purpose, now, payload['expires'],
                 _canonical(payload), self._mac('bff-payload', _canonical(payload))))
            return {'access_token': raw, 'token_type': 'Bearer', 'audience': AUDIENCE, 'purpose': purpose, 'expires': payload['expires']}

    def validate_token(self, raw, ws, purpose, db=None):
        if db is None:
            with self.tx() as connection:
                return self.validate_token(raw, ws, purpose, connection)
        if db is not self.store._db or not db.in_transaction or type(raw) is not str or not re.fullmatch('cbt_[A-Za-z0-9_-]{43}', raw):
            raise WorkspaceDenied()
        rows = _rows(db, 'SELECT * FROM customer_bff_tokens WHERE token_hash=? AND revoked IS NULL AND expires>?',
                     (self._mac('bff', raw), _time()))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]
        payload = self._open_token(row)
        if row['workspace_id'] != ws or row['purpose'] != purpose:
            raise WorkspaceDenied()
        return self.authorize(db, CustomerActor(row['customer_id'], row['session_ref'], row['id']), ws, purpose)

    def _open_token(self, row):
        payload = _object(row['payload'])
        if (not hmac.compare_digest(row['signature'], self._mac('bff-payload', _canonical(payload)))
                or payload.get('profile') != PROFILE or payload.get('config_hash') != payload.get('identity_config_hash')
                or any(payload.get(key) != row[key] for key in ('id', 'customer_id', 'session_ref', 'workspace_id', 'purpose', 'created', 'expires'))):
            raise WorkspaceDenied()
        return payload
