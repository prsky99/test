"""Independent opt-in origin-bound deployment purpose for published connections.

Publication, deployment and each manual input-sharing run remain separate
authorities. No row is placed in the legacy workflow_apps identity space.
"""
import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

from .capability_registry import canonical, digest
from . import workflow_public_flow as flow

PROFILE = 'connected-informational-deployment-v1'
GRANT_NOTICE = 'workflow-connection-app-v13-grant-v1'
SHARE_NOTICE = 'workflow-connection-app-v13-share-v1'
RUN_NOTICE = 'workflow-connection-app-v13-run-v1'
PLAN = 'workflow-connection-app-v13-export-v1'
TICKET = 'workflow-connection-app-v13-ticket-v1'
DEFAULTS = {'minute_limit': 10, 'day_limit': 500, 'ttl_seconds': 86400}
BODY_FIELDS = {'proposal', 'signature', 'sharing_authority', 'sharing_notice', 'run_authority', 'run_notice'}
TICKET_FIELDS = {'audience', 'profile', 'app_id', 'grant_id', 'revision', 'release_id', 'publication_revision',
                 'definition_hash', 'rule_hash', 'nonce', 'origin', 'created', 'expires', 'reviewed_at', 'sharing_notice', 'run_notice'}
SCHEMA = '''CREATE TABLE IF NOT EXISTS workflow_connection_deployments (
 id TEXT PRIMARY KEY,grant_id TEXT NOT NULL UNIQUE,release_id TEXT NOT NULL,export_nonce TEXT NOT NULL UNIQUE,
 revision INTEGER NOT NULL,active INTEGER NOT NULL,key_hash TEXT NOT NULL,
 payload TEXT NOT NULL,signature TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
'''


def origins(values):
    from .workflow_apps import normalize_origins
    normalized = normalize_origins(values)
    if not normalized: raise ValueError('Register at least one exact HTTP(S) origin.')
    return normalized


class ConnectionDeployments:
    def __init__(self, runtime):
        self.runtime, self.store, self.publication = runtime, runtime.store, runtime.publication
        with self.store._lock: self.store._db.executescript(SCHEMA)

    def _owner(self, actor): return self.publication._owner(actor)

    @staticmethod
    def _config(publication):
        return {'release_id': publication['id'], 'title': 'Reviewed news to documentation connection',
                'description': 'One news search, then one documentation search using only its first verified safe title.',
                'api_origin': 'https://agentconcierge.biz'}

    def options(self, release_id, actor):
        self._owner(actor)
        try:
            publication, workflow = self.publication.current(release_id)
            config = self._config(publication); available = True
        except (ValueError, TypeError, KeyError, IndexError):
            config = {'release_id': release_id, 'title': 'Reviewed connection', 'description': ''}; available = False
        return {'ok': True, 'profile': PROFILE, 'release_id': release_id, 'available': available, 'config': config, 'defaults': dict(DEFAULTS),
                'deployments': self.deployments(release_id, actor)['deployments'],
                'notices': {'grant': GRANT_NOTICE, 'share': SHARE_NOTICE, 'run': RUN_NOTICE}}

    def prepare_admin(self, release_id, body, actor):
        owner = self._owner(actor)
        if not isinstance(body, dict) or set(body) != {'allowed_origins', 'minute_limit', 'day_limit', 'ttl_seconds'}: raise ValueError('Review exact origins, limits and deployment duration.')
        allowed = origins(body['allowed_origins']); minute, day, ttl = (body[key] for key in ('minute_limit', 'day_limit', 'ttl_seconds'))
        if (type(minute) is not int or not 1 <= minute <= 30 or type(day) is not int or not 1 <= day <= 5000
                or type(ttl) is not int or not 300 <= ttl <= 86400): raise ValueError('Use bounded deployment limits and duration.')
        publication, workflow = self.publication.current(release_id); created = flow.stamp(time.time())
        expires = flow.stamp(min(created + ttl, publication['expires'], publication['proof']['valid_until']))
        if expires - created < 300: raise ValueError('Review a publication with at least five minutes of retained validity.')
        proposal = {'audience': PLAN, 'profile': PROFILE, 'owner': owner, 'release_id': release_id,
                    'publication_revision': publication['revision'], 'definition_hash': publication['definition_hash'],
                    'rule_hash': digest(workflow['nodes'][2]['data']['composition']['payload']['connection']),
                    'proof_hash': digest(publication['proof']), 'created': created, 'expires': min(created + 900, expires),
                    'grant_expires': expires, 'nonce': secrets.token_hex(16), 'allowed_origins': allowed,
                    'minute_limit': minute, 'day_limit': day}
        return {'ok': True, 'profile': PROFILE, **self.publication._envelope(proposal),
                'preview': {**self.publication._preview(workflow, expires), 'release_id': release_id,
                            'title': self._config(publication)['title'],
                            'allowed_origins': allowed, 'minute_limit': minute, 'day_limit': day},
                'executed': False, 'notices': {'grant': GRANT_NOTICE, 'share': SHARE_NOTICE, 'run': RUN_NOTICE}}

    def issue(self, release_id, body, actor):
        owner = self._owner(actor)
        if (not isinstance(body, dict) or set(body) != {'proposal', 'signature', 'deployment_authority', 'deployment_notice'}
                or body['deployment_authority'] is not True or body['deployment_notice'] != GRANT_NOTICE): raise ValueError('Separate explicit deployment authorization is required.')
        fields = {'audience', 'profile', 'owner', 'release_id', 'publication_revision', 'definition_hash', 'rule_hash', 'proof_hash',
                  'created', 'expires', 'grant_expires', 'nonce', 'allowed_origins', 'minute_limit', 'day_limit'}
        p = self.publication._unpack(body, PLAN, fields)
        if (p['profile'] != PROFILE or p['owner'] != owner or p['release_id'] != release_id
                or p['expires'] != min(p['created'] + 900, p['grant_expires'])
                or not 300 <= flow.timestamp(p['grant_expires']) - p['created'] <= 86400
                or origins(p['allowed_origins']) != p['allowed_origins']
                or type(p['minute_limit']) is not int or not 1 <= p['minute_limit'] <= 30
                or type(p['day_limit']) is not int or not 1 <= p['day_limit'] <= 5000
                or not isinstance(p['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', p['nonce'])): raise ValueError('The independent deployment review changed.')
        publication, workflow = self.publication.current(release_id)
        if (type(p['publication_revision']) is not int or p['publication_revision'] != publication['revision']
                or p['definition_hash'] != publication['definition_hash'] or p['proof_hash'] != digest(publication['proof'])
                or p['rule_hash'] != digest(workflow['nodes'][2]['data']['composition']['payload']['connection'])
                or p['grant_expires'] > min(publication['expires'], publication['proof']['valid_until'])): raise ValueError('The reviewed publication or source-test proof changed.')
        self.publication._epoch(p['created'])
        app_id = 'capp_' + secrets.token_hex(16); grant_id = 'cdg_' + secrets.token_hex(16)
        key = 'cpk_' + secrets.token_urlsafe(32); key_hash = hashlib.sha256(key.encode()).hexdigest(); created = time.time()
        payload = {'audience': GRANT_NOTICE, 'profile': PROFILE, 'id': app_id, 'grant_id': grant_id, 'release_id': release_id,
                   'export_nonce': p['nonce'],
                   'revision': 1, 'publication_revision': p['publication_revision'], 'definition_hash': p['definition_hash'],
                   'rule_hash': p['rule_hash'], 'proof_hash': p['proof_hash'], 'owner': owner, 'created': created,
                   'reviewed_at': p['created'], 'expires': p['grant_expires'], 'origins': p['allowed_origins'],
                   'limits': {'minute': p['minute_limit'], 'day': p['day_limit']}, 'key_hash': key_hash}
        signature = self.runtime.authority.signature(payload)
        with self.store._lock:
            if self.store._db.in_transaction: raise ValueError('Connected deployment issuance is temporarily unavailable.')
            with self.store.tx() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM workflow_connection_deployments WHERE export_nonce=?', (p['nonce'],)).fetchone(): raise ValueError('This deployment proposal was already consumed; prepare a new review.')
                if db.execute("SELECT COUNT(*) FROM workflow_connection_deployments WHERE created>? AND json_extract(payload,'$.owner')=?", (created - 3600, owner)).fetchone()[0] >= 20: raise ValueError('The connected deployment review limit has been reached.')
                db.execute('INSERT INTO workflow_connection_deployments VALUES (?,?,?,?,1,1,?,?,?,?,?,NULL)',
                           (app_id, grant_id, release_id, p['nonce'], key_hash, canonical(payload), signature, created, p['grant_expires']))
        deployment = {'app_id': app_id, 'publish_key': key, 'grant_id': grant_id, 'revision': 1, 'release_id': release_id,
                      'profile': PROFILE, 'sdk_version': '1.3.0', 'allowed_origins': p['allowed_origins'],
                      'minute_limit': p['minute_limit'], 'day_limit': p['day_limit'], 'expires': p['grant_expires']}
        return {'config': self._config(publication), 'deployment': deployment}

    export_issue = issue

    def metadata(self, app_id, origin):
        if not isinstance(app_id, str) or not re.fullmatch(r'capp_[a-f0-9]{32}', app_id): raise ValueError('The connected application is unavailable.')
        rows = self.store.query('SELECT * FROM workflow_connection_deployments WHERE id=? AND active=1', (app_id,))
        if len(rows) != 1 or len(rows[0]['payload']) > 32000: raise ValueError('The connected deployment grant is unavailable.')
        row = dict(rows[0]); payload = json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'], self.runtime.authority.signature(payload))
                or payload.get('audience') != GRANT_NOTICE or payload.get('profile') != PROFILE or row['revoked'] is not None
                or type(payload.get('revision')) is not int or payload['revision'] < 1
                or type(payload.get('publication_revision')) is not int or payload['publication_revision'] < 1
                or not isinstance(payload.get('grant_id'), str) or not re.fullmatch(r'cdg_[a-f0-9]{32}', payload['grant_id'])
                or any(payload.get(key) != row[key] for key in ('id', 'grant_id', 'release_id', 'export_nonce', 'revision', 'key_hash', 'created', 'expires'))
                or not flow.timestamp(payload['created']) <= time.time() < flow.timestamp(payload['expires']) <= payload['created'] + 86400
                or flow.timestamp(payload['reviewed_at']) > payload['created'] + 5
                or type(payload['limits']['minute']) is not int or not 1 <= payload['limits']['minute'] <= 30
                or type(payload['limits']['day']) is not int or not 1 <= payload['limits']['day'] <= 5000): raise ValueError('The connected deployment was revoked, expired or changed.')
        self._owner(payload['owner'])
        publication = self.publication.metadata(payload['release_id'])
        if (payload['publication_revision'] != publication['revision'] or payload['definition_hash'] != publication['definition_hash']
                or payload['proof_hash'] != digest(publication['proof'])
                or payload['rule_hash'] != digest(publication['workflow']['nodes'][2]['data']['composition']['payload']['connection'])
                or payload['expires'] > min(publication['expires'], publication['proof']['valid_until'])
                or origins(payload['origins']) != payload['origins'] or origins([origin])[0] not in payload['origins']): raise ValueError('The publication or registered origin changed.')
        return {'grant': payload, 'publication': publication}

    def current(self, app_id, origin):
        context = self.metadata(app_id, origin); grant = context['grant']
        self.publication._epoch(grant['reviewed_at'])
        publication, workflow = self.publication.current(grant['release_id'])
        return {**context, 'workflow': workflow}

    def authorize(self, app_id, key, origin, *, read=False):
        context = self.metadata(app_id, origin) if read else self.current(app_id, origin)
        if (not isinstance(key, str) or not re.fullmatch(r'cpk_[A-Za-z0-9_-]{43}', key) or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), context['grant']['key_hash'])): raise ValueError('The connected application key is unavailable.')
        grant = context['grant']
        return {'id': app_id, 'release_id': grant['release_id'], 'minute_limit': grant['limits']['minute'], 'day_limit': grant['limits']['day']}

    def deployments(self, release_id, actor):
        self._owner(actor); result = []
        for row in self.store.query('SELECT id,grant_id,revision,active,created,expires,revoked FROM workflow_connection_deployments WHERE release_id=? ORDER BY created DESC LIMIT 50', (release_id,)):
            result.append({'app_id': row['id'], **{key: row[key] for key in ('grant_id', 'revision', 'created', 'expires', 'revoked')}, 'active': bool(row['active']), 'profile': PROFILE})
        return {'ok': True, 'profile': PROFILE, 'deployments': result}

    def revoke(self, release_id, app_id, revision, actor):
        self._owner(actor)
        if type(revision) is not int: raise ValueError('Use the current connected deployment revision.')
        with self.store.tx() as db:
            if db.execute('UPDATE workflow_connection_deployments SET active=0,revision=revision+1,revoked=? WHERE id=? AND release_id=? AND revision=? AND active=1', (time.time(), app_id, release_id, revision)).rowcount != 1: raise ValueError('The connected deployment revision changed.')
        for row in self.store.query("SELECT id FROM workflow_runs WHERE actor=? AND status IN ('queued','running')", ('connection-app:' + app_id,)): self.runtime.cancel(row['id'])
        return {'ok': True, 'app_id': app_id, 'active': False, 'revision': revision + 1}

    def prepare_run(self, app_id, origin):
        context = self.current(app_id, origin); grant = context['grant']; created = flow.stamp(time.time()); normalized = origins([origin])[0]
        p = {'audience': TICKET, 'profile': PROFILE, 'app_id': app_id, 'grant_id': grant['grant_id'], 'revision': grant['revision'],
             'release_id': grant['release_id'], 'publication_revision': grant['publication_revision'], 'definition_hash': grant['definition_hash'],
             'rule_hash': grant['rule_hash'], 'nonce': secrets.token_hex(16), 'origin': normalized, 'created': created,
             'expires': flow.stamp(min(created + 300, grant['expires'])), 'reviewed_at': created, 'sharing_notice': SHARE_NOTICE, 'run_notice': RUN_NOTICE}
        return {'ok': True, 'profile': PROFILE, **self.publication._envelope(p),
                'preview': self.publication._preview(context['workflow'], p['expires']), 'executed': False, 'notices': {'share': SHARE_NOTICE, 'run': RUN_NOTICE}}

    @staticmethod
    def _declared(body):
        if (not isinstance(body, dict) or set(body) != BODY_FIELDS or body['sharing_authority'] is not True or body['sharing_notice'] != SHARE_NOTICE
                or body['run_authority'] is not True or body['run_notice'] != RUN_NOTICE): raise ValueError('Separate current connected-app sharing and live-run declarations are required.')

    def _ticket(self, app_id, body, origin, *, current=True, admitted=None):
        self._declared(body); p = body['proposal']
        if (not isinstance(p, dict) or set(p) != TICKET_FIELDS or p['audience'] != TICKET or p['profile'] != PROFILE
                or not isinstance(body['signature'], str) or not hmac.compare_digest(body['signature'], self.runtime.authority.signature(p))
                or p['app_id'] != app_id or p['sharing_notice'] != SHARE_NOTICE or p['run_notice'] != RUN_NOTICE
                or not isinstance(p['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', p['nonce'])
                or p['reviewed_at'] != p['created'] or not flow.timestamp(p['created']) <= (time.time() if admitted is None else flow.timestamp(admitted)) < flow.timestamp(p['expires'])
                or p['expires'] > p['created'] + 300 or origins([origin])[0] != p['origin']): raise ValueError('The connected application run ticket changed or expired.')
        context = self.current(app_id, origin) if current else self.metadata(app_id, origin); grant = context['grant']
        if (type(p['revision']) is not int or type(p['publication_revision']) is not int
                or any(p[key] != grant[key] for key in ('grant_id', 'revision', 'release_id', 'publication_revision', 'definition_hash', 'rule_hash'))
                or p['expires'] > grant['expires']): raise ValueError('The connected deployment or published rule changed.')
        if current: self.publication._epoch(p['reviewed_at'])
        return p, context

    @staticmethod
    def _scope(body):
        return {'profile': PROFILE, 'proposal': copy.deepcopy(body['proposal']), 'signature': body['signature'], 'sharing_authorized': True, 'run_authorized': True}

    def accepted_run(self, app_id, body, origin):
        p, _ = self._ticket(app_id, body, origin)
        rows = self.store.query('SELECT * FROM workflow_runs WHERE actor=? AND idempotency_key=?', ('connection-app:' + app_id, p['nonce']))
        if not rows: return None
        self.replay_scope(dict(rows[0]), self._scope(body))
        return rows[0]['id']

    def execute_run(self, app_id, body, origin):
        p, context = self._ticket(app_id, body, origin); workflow = context['workflow']
        args = {'actor': 'connection-app:' + app_id, 'source': 'public', 'public': True, 'idempotency': p['nonce'],
                'principal': self.runtime.principal('public', app_id, workflow['id']), 'connection_deployment': {**body, 'origin': origin}}
        try: job = self.runtime.submit(workflow, **args)
        except sqlite3.IntegrityError: job = self.runtime.submit(workflow, **args)
        return {'ok': True, 'profile': PROFILE, **job}

    def admit(self, workflow, claims, context, *, source, profile, fallback):
        if context is None: return None
        if (not flow.is_flow(workflow) or not isinstance(context, dict) or set(context) != BODY_FIELDS | {'origin'}
                or source != 'public' or claims.get('kind') != 'public' or profile != 'standard' or fallback): raise ValueError('Use one standard manual connected-app purpose.')
        body = {key: context[key] for key in BODY_FIELDS}; p, current = self._ticket(claims['subject'], body, context['origin'])
        if flow.graph_value(workflow) != flow.graph_value(current['workflow']): raise ValueError('The deployed canonical definition changed.')
        return self._scope(body)

    def run_scope(self, row, workflow, authority=None):
        authority = authority or self.runtime.authority.run(row['id'], workflow['id'], row['digest'], row['source'])
        principal = authority['principal']['payload']; scope = principal.get('connection_deployment')
        if (not isinstance(scope, dict) or set(scope) != {'profile', 'proposal', 'signature', 'sharing_authorized', 'run_authorized'}
                or scope['profile'] != PROFILE or scope['sharing_authorized'] is not True or scope['run_authorized'] is not True
                or row['source'] != 'public' or principal.get('kind') != 'public' or principal.get('public_connection') is not None
                or authority.get('grant_id') is not None or digest(workflow) != row['digest'] or self.runtime.budgets.get(row)['profile'] != 'standard'): raise ValueError('The connected deployment run purpose changed.')
        body = self._body(scope); p, current = self._ticket(principal['subject'], body, scope['proposal']['origin'])
        if (scope != self._scope(body) or flow.graph_value(workflow) != flow.graph_value(current['workflow'])
                or row['actor'] != 'connection-app:' + p['app_id'] or row['idempotency_key'] != p['nonce']): raise ValueError('The connected deployment nonce or canonical definition changed.')

    @staticmethod
    def _body(scope):
        return {'proposal': scope['proposal'], 'signature': scope['signature'], 'sharing_authority': True, 'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE}

    def replay_scope(self, row, scope, *, read=False):
        records = self.store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?', (row['id'],))
        if len(records) != 1 or len(records[0]['payload']) > 16384: raise ValueError('The retained connected-app authority is unavailable.')
        authority = json.loads(records[0]['payload']); envelope = authority['principal']; principal = envelope['payload']
        if (not isinstance(scope, dict) or set(scope) != {'profile', 'proposal', 'signature', 'sharing_authorized', 'run_authorized'}
                or scope['profile'] != PROFILE or scope['sharing_authorized'] is not True or scope['run_authorized'] is not True
                or not hmac.compare_digest(records[0]['signature'], self.runtime.authority.signature(authority))
                or not hmac.compare_digest(envelope['signature'], self.runtime.authority.signature(principal))
                or authority.get('run_id') != row['id'] or any(authority.get(key) != row[key] for key in ('workflow_id', 'digest', 'source'))
                or authority.get('grant_id') is not None or principal.get('connection_deployment') != scope or principal.get('public_connection') is not None
                or principal.get('kind') != 'public' or principal.get('audience') != 'workflow-runtime-v1' or principal.get('workflow_id') != row['workflow_id']
                or not flow.timestamp(row['created']) < flow.timestamp(principal.get('expires')) <= scope['proposal']['expires']): raise ValueError('The retained connected-app purpose changed.')
        p, _ = self._ticket(principal['subject'], self._body(scope), scope['proposal']['origin'], current=not read, admitted=row['created'] if read else None)
        if row['source'] != 'public' or row['actor'] != 'connection-app:' + p['app_id'] or row['idempotency_key'] != p['nonce']: raise ValueError('The connected-app nonce scope changed.')

    def run_key(self, row, scope):
        p = scope['proposal']; raw = hmac.new(self.runtime.key, ('workflow-connection-app-key-v1\0' + p['app_id'] + '\0' + p['origin'] + '\0' + p['nonce'] + '\0' + row['id']).encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    def _access(self, app_id, run_id, key, origin):
        self.metadata(app_id, origin)
        rows = self.store.query('SELECT * FROM workflow_runs WHERE id=? AND actor=?', (run_id, 'connection-app:' + app_id))
        if len(rows) != 1: raise ValueError('The scoped connected-app run is unavailable.')
        row = dict(rows[0]); records = self.store.query('SELECT substr(payload,1,16385) AS payload FROM workflow_run_authority WHERE run_id=?', (run_id,))
        if len(records) != 1 or len(records[0]['payload']) > 16384: raise ValueError('The retained run purpose is unavailable.')
        scope = json.loads(records[0]['payload'])['principal']['payload'].get('connection_deployment'); self.replay_scope(row, scope, read=True)
        if (scope['proposal']['origin'] != origins([origin])[0] or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', key) or not hmac.compare_digest(key, self.run_key(row, scope))
                or time.time() >= row['created'] + 3600): raise ValueError('The app/origin run capability is unavailable or expired.')
        return row

    def read_run(self, app_id, run_id, key, origin):
        self._access(app_id, run_id, key, origin); metadata = self.metadata(app_id, origin)
        return self.publication.project_result(metadata['grant']['release_id'], run_id, self.runtime.get(run_id))

    def cancel_run(self, app_id, run_id, key, origin):
        self._access(app_id, run_id, key, origin); self.runtime.cancel(run_id)
        return {'ok': True, 'cancel_requested': True}


ConnectionDeployment = ConnectionDeployments
