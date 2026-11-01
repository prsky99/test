"""Revocable fixed-input informational deployment purpose, separate from SDK 1.1.

Public package keys identify deployments. They never supply this profile's
per-run sharing/execution declaration or any private connected-flow permission.
"""
import copy
import hmac
import json
import math
import re
import secrets
import time

from .capability_contracts import validate
from .capability_registry import digest
from .concierge.execution_policy import ExecutionDenied

PROFILE = 'literal-informational-deployment-v1'
GRANT_NOTICE = 'workflow-app-v12-deployment-grant-v1'
SHARE_NOTICE = 'workflow-app-v12-share-v1'
RUN_NOTICE = 'workflow-app-v12-run-v1'
TICKET_AUDIENCE = 'workflow-app-v12-ticket-v1'
SCHEMA = '''CREATE TABLE IF NOT EXISTS workflow_deployment_grants (
 id TEXT PRIMARY KEY,app_id TEXT NOT NULL UNIQUE,workflow_id INTEGER NOT NULL,
 revision INTEGER NOT NULL,active INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
 created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
'''
CONTEXT_FIELDS = {'ticket', 'signature', 'sharing_authority', 'sharing_notice', 'run_authority', 'run_notice', 'origin'}
TICKET_FIELDS = {'audience', 'profile', 'app_id', 'grant_id', 'grant_revision', 'definition_hash',
                 'projection_hash', 'inputs_hash', 'aliases_hash', 'nonce', 'created', 'expires',
                 'reviewed_at', 'origin', 'sharing_notice', 'run_notice'}


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('A valid bounded timestamp is required.')
    return value


def _graph(workflow):
    return {key: workflow.get(key) for key in ('id', 'name', 'description', 'category', 'trigger_type', 'nodes', 'edges')}


class DeploymentConsent:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        with self.store._lock:
            self.store._db.executescript(SCHEMA)

    def is_v12(self, app_id):
        return bool(self.store.query('SELECT 1 FROM workflow_deployment_grants WHERE app_id=?', (app_id,)))

    def list(self, workflow_id):
        return [{**{key: row[key] for key in ('app_id', 'revision', 'active', 'created', 'expires', 'revoked')}, 'grant_id': row['id'], 'profile': PROFILE}
                for row in self.store.query('SELECT id,app_id,revision,active,created,expires,revoked FROM workflow_deployment_grants WHERE workflow_id=? ORDER BY created DESC LIMIT 50', (workflow_id,))]

    def _epoch(self, reviewed_at):
        rows = self.store.query('SELECT updated FROM execution_controls WHERE id=1')
        if len(rows) != 1 or _time(rows[0]['updated']) > _time(reviewed_at):
            raise ValueError('Execution controls changed; review a new deployment.')

    def _owner(self, principal, workflow_id, *, issuing=False, created=None):
        p = principal['payload']
        if not hmac.compare_digest(principal['signature'], self.runtime.authority.signature(p)):
            raise ValueError('Administrator authority changed.')
        if (p.get('kind') != 'admin' or p.get('role') != 'superadmin'
                or p.get('workflow_id') != workflow_id or p.get('audience') != 'workflow-runtime-v1'
                or not isinstance(p.get('subject'), str) or not p['subject'].isdecimal()
                or _time(p.get('expires')) <= (time.time() if issuing else _time(created))):
            raise ValueError('Current highest-administrator deployment authority is required.')
        rows = self.store.query('SELECT role,active FROM admin_users WHERE id=?', (int(p['subject']),))
        if len(rows) != 1 or rows[0]['role'] != 'superadmin' or not rows[0]['active']:
            raise ValueError('Administrator deployment authority was revoked.')
        return p

    def _proof(self, workflow, required=None):
        records = (self.store.query("SELECT id,created,digest FROM workflow_runs WHERE id=? AND workflow_id=? AND source='admin' AND status='succeeded' AND execution_outcome='succeeded' LIMIT 1", (required, workflow['id'])) if required is not None else
                   self.store.query("SELECT id,created,digest FROM workflow_runs WHERE workflow_id=? AND source='admin' AND status='succeeded' AND execution_outcome='succeeded' ORDER BY created DESC LIMIT 20", (workflow['id'],)))
        for record in records:
            if required is not None and record['id'] != required:
                continue
            try:
                proof_hash = self.runtime.composer.validate_publish(workflow, record['id'])
                authorities = self.store.query('SELECT payload,signature FROM workflow_run_authority WHERE run_id=?', (record['id'],))
                if len(authorities) != 1 or len(authorities[0]['payload']) > 16384:
                    raise ValueError()
                authority = json.loads(authorities[0]['payload']); envelope = authority['principal']; principal = envelope['payload']
                if (not hmac.compare_digest(authorities[0]['signature'], self.runtime.authority.signature(authority))
                        or not hmac.compare_digest(envelope['signature'], self.runtime.authority.signature(principal))
                        or any(authority.get(key) != value for key, value in {'run_id': record['id'], 'workflow_id': workflow['id'], 'digest': record['digest'], 'source': 'admin'}.items())
                        or principal.get('kind') != 'admin' or principal.get('workflow_id') != workflow['id']
                        or principal.get('audience') != 'workflow-runtime-v1' or _time(principal.get('expires')) <= _time(record['created'])):
                    raise ValueError()
                checkpoints = self.store.query('SELECT node_id,substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=?', (record['id'],))
                nodes = {node['id']: node for node in workflow['nodes']}
                if {cp['node_id'] for cp in checkpoints} != set(nodes):
                    raise ValueError()
                attempts = self.store.query('SELECT node_id,input_hash,status FROM workflow_execution_attempts WHERE run_id=?', (record['id'],))
                agent_ids = {node['id'] for node in workflow['nodes'] if node['type'] == 'agent'}
                if {attempt['node_id'] for attempt in attempts} != agent_ids:
                    raise ValueError()
                if self.store.query('SELECT 1 FROM workflow_routing_attempts WHERE run_id=? LIMIT 1', (record['id'],)):
                    raise ValueError()
                attempts = {attempt['node_id']: attempt for attempt in attempts}
                observed = []
                for row in checkpoints:
                    if len(row['payload']) > 262144:
                        raise ValueError()
                    cp = json.loads(row['payload']); value = cp['record']; node = nodes[row['node_id']]
                    if (not hmac.compare_digest(row['signature'], self.runtime.authority.signature(cp))
                            or any(cp.get(key) != expected for key, expected in {'audience': 'workflow-checkpoint-v1', 'run_id': record['id'], 'digest': record['digest'], 'node_id': node['id']}.items())
                            or value['node_id'] != node['id'] or value['status'] != 'succeeded' or value['type'] != node['type']):
                        raise ValueError()
                    if value['type'] != 'agent':
                        continue
                    binding = node['data']['composition']['payload']; attempt = attempts[node['id']]
                    if (value['kind'] != 'mcp' or value['resource_id'] != node['resource_id']
                            or value['input'] != binding['input'] or value['data'] != cp['flow_output']
                            or attempt['status'] != 'succeeded'
                            or attempt['input_hash'] != self.runtime.authority.signature({'audience': 'workflow-input-v1', 'digest': record['digest'], 'node_id': node['id'], 'input': binding['input']})):
                        raise ValueError()
                    started = _time(value['started']); latency = _time(value['latency_ms'])
                    if (latency > 60000 or started < record['created'] or principal['expires'] <= started
                            or not math.isfinite(started + latency / 1000) or started + latency / 1000 > time.time() + 5):
                        raise ValueError()
                    observed.append(started + latency / 1000)
                if not observed:
                    raise ValueError()
                until = min(_time(value) + 86400 for value in observed)
                if until <= time.time():
                    raise ValueError()
                return {'run_id': record['id'], 'definition_hash': proof_hash, 'valid_until': until}
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                continue
        raise ValueError('A retained successful explicit test of this published definition is required.')

    def definition(self, workflow_id):
        from .workflow_composer import NODE
        from .workflow_typed_flow import validate_title
        from .workflows import public_template, sensitive
        from .concierge.recommendation_security import public_data
        workflow = self.store.get_workflow(workflow_id)
        if (not workflow or public_template(workflow) is None or workflow.get('trigger_type') != 'manual'
                or self.runtime.fallback.fingerprint(workflow_id)):
            raise ValueError('Choose a published manual compiled informational workflow without fallback.')
        nodes = workflow['nodes']; edges = workflow['edges']
        if (not 2 <= len(nodes) <= 3 or nodes[0].get('id') != 'start'
                or nodes[0].get('type') != 'trigger' or nodes[0].get('kind') != 'trigger'
                or nodes[0].get('data') != {} or set(nodes[0]) - {'id', 'name', 'type', 'kind', 'position', 'data'}
                or len(edges) != len(nodes) - 1):
            raise ValueError('Only the fixed literal informational compiler graph is supported.')
        contracts = set(); inputs = []
        for index, node in enumerate(nodes[1:], 1):
            data = node.get('data', {})
            if (node.get('id') != 'search-' + str(index)
                    or set(node) - {'id', 'name', 'type', 'kind', 'resource_id', 'position', 'data'}
                    or set(data) != {'tool', 'input', 'composition'} or sensitive(data)):
                raise ValueError('Only fixed credential-free literal search inputs are supported.')
            binding = self.runtime.composer.validate_node(node, data['input'])
            if (not binding or binding['audience'] != NODE or binding['contract'] not in ('news.search.v1', 'docs.search.v1')
                    or binding['contract'] in contracts or data['input'].get('language') != 'en'
                    or type(data['input'].get('limit')) is not int or not 1 <= data['input']['limit'] <= 5
                    or validate_title(data['input'].get('query')) != data['input'].get('query')
                    or public_data(data['input']) != data['input']):
                raise ValueError('The approved literal search binding is unavailable or unsafe.')
            contracts.add(binding['contract'])
            inputs.append({key: value for key, value in data['input'].items() if key != 'from_utc'})
            edge = edges[index - 1]
            if edge != {'id': 'start-' + node['id'], 'source': 'start', 'target': node['id']}:
                raise ValueError('Use only independent fixed literal searches.')
        if any(value != inputs[0] for value in inputs):
            raise ValueError('Reviewed literal settings must remain identical.')
        self._proof(workflow)
        return workflow

    def _describe(self, workflow):
        from .workflows import public_template
        aliases = []; bindings = []
        for node in workflow['nodes'][1:]:
            value = node['data']['composition']['payload']
            alias = ('News agent ' if value['contract'] == 'news.search.v1' else 'Documentation agent ') + value['pin']['version']['agent_ref'][-8:]
            aliases.append({'alias': alias, 'contract': value['contract'], 'input': copy.deepcopy(value['input'])})
            bindings.append({'node_id': node['id'], 'contract': value['contract'], 'pin': copy.deepcopy(value['pin']),
                             'input': copy.deepcopy(value['input'])})
        projection = public_template(workflow)
        return {'definition_hash': digest(_graph(workflow)), 'projection_hash': projection['definition_hash'],
                'inputs_hash': digest([binding['input'] for binding in bindings]),
                'aliases_hash': digest(aliases), 'aliases': aliases, 'bindings': bindings}

    def expiry_limit(self, workflow):
        return min(time.time() + 86400, self._proof(workflow)['valid_until'])

    def issue(self, db, app_id, workflow, principal, *, expires, authority=False, notice=None, reviewed_at=None):
        created = time.time(); reviewed_at = created if reviewed_at is None else _time(reviewed_at)
        if authority is not True or notice != GRANT_NOTICE or reviewed_at > created + 5:
            raise ValueError('Explicit current deployment-grant authorization is required.')
        owner = self._owner(principal, workflow['id'], issuing=True)
        current = self.definition(workflow['id'])
        if _graph(current) != _graph(workflow):
            raise ValueError('The reviewed fixed definition changed.')
        self._epoch(reviewed_at)
        if not created < _time(expires) <= self.expiry_limit(current):
            raise ValueError('Use an expiry within the retained test validity and one day.')
        rows = db.execute('SELECT * FROM workflow_apps WHERE id=? AND workflow_id=? AND active=0', (app_id, workflow['id'])).fetchall()
        if len(rows) != 1:
            raise ValueError('The registered deployment is unavailable.')
        app = dict(rows[0])
        from .workflow_apps import normalize_origins
        origins = normalize_origins(json.loads(app['origins']))
        if not origins or json.loads(app['fields']) != []:
            raise ValueError('Use fixed inputs and at least one exact registered origin.')
        descriptor = self._describe(current)
        if app['definition_hash'] != descriptor['projection_hash']:
            raise ValueError('The registered public projection changed.')
        identity = 'dg_' + secrets.token_hex(16)
        payload = {'audience': GRANT_NOTICE, 'profile': PROFILE, 'id': identity, 'app_id': app_id,
                   'workflow_id': workflow['id'], 'revision': 1, 'owner': copy.deepcopy(principal),
                   'created': created, 'reviewed_at': reviewed_at, 'expires': expires,
                   'app_key_hash': app['key_hash'],
                   'origins': origins, 'limits': {'minute': app['minute_limit'], 'day': app['day_limit']},
                   'definition': descriptor, 'proof': self._proof(current)}
        db.execute('INSERT INTO workflow_deployment_grants VALUES (?,?,?,1,1,?,?,?, ?,NULL)',
                   (identity, app_id, workflow['id'], json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False),
                    self.runtime.authority.signature(payload), created, expires))
        return {'grant_id': identity, 'revision': 1, 'expires': expires, 'profile': PROFILE}

    def read_access(self, app_id, origin=None):
        """Authorize retained status without requiring live provider eligibility."""
        rows = self.store.query('SELECT * FROM workflow_deployment_grants WHERE app_id=? AND active=1', (app_id,))
        apps = self.store.query('SELECT * FROM workflow_apps WHERE id=? AND active=1', (app_id,))
        if len(rows) != 1 or len(apps) != 1 or len(rows[0]['payload']) > 65536:
            raise ValueError('The authorized deployment is unavailable.')
        row, app = dict(rows[0]), dict(apps[0]); payload = json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'], self.runtime.authority.signature(payload))
                or payload.get('audience') != GRANT_NOTICE or payload.get('profile') != PROFILE
                or type(payload.get('revision')) is not int or payload['revision'] < 1
                or any(payload.get(key) != row[key] for key in ('app_id', 'workflow_id', 'revision', 'created', 'expires'))
                or payload.get('id') != row['id'] or row['revoked'] is not None
                or not _time(payload['created']) <= time.time() < _time(payload['expires'])):
            raise ValueError('The deployment grant expired or changed.')
        self._owner(payload['owner'], payload['workflow_id'], created=payload['created'])
        if (app['workflow_id'] != payload['workflow_id'] or app['key_hash'] != payload['app_key_hash']
                or app['definition_hash'] != payload['definition']['projection_hash']
                or json.loads(app['origins']) != payload['origins'] or json.loads(app['fields']) != []
                or {'minute': app['minute_limit'], 'day': app['day_limit']} != payload['limits']):
            raise ValueError('The deployment definition, recipients or policy changed.')
        if origin is not None:
            from .workflow_apps import normalize_origins
            if not isinstance(origin, str) or normalize_origins([origin])[0] not in payload['origins']:
                raise ValueError('Use an exact registered deployment origin.')
        return {'app': app, 'grant': payload}

    def current(self, app_id, *, origin=None):
        context = self.read_access(app_id, origin); payload = context['grant']
        self._epoch(payload['reviewed_at'])
        workflow = self.definition(payload['workflow_id']); descriptor = self._describe(workflow)
        if self._proof(workflow, required=payload['proof']['run_id']) != payload['proof']:
            raise ValueError('The retained deployment test proof changed or was pruned.')
        if descriptor != payload['definition']:
            raise ValueError('The deployment definition, recipients or inputs changed.')
        return {**context, 'workflow': workflow}

    def prepare(self, app_id, origin):
        context = self.current(app_id, origin=origin); grant = context['grant']; definition = grant['definition']
        from .workflow_apps import normalize_origins
        normalized_origin = normalize_origins([origin])[0]
        now = time.time(); expires = min(now + 300, grant['expires'])
        now = int(now) if float(now).is_integer() else now
        expires = int(expires) if float(expires).is_integer() else expires
        ticket = {'audience': TICKET_AUDIENCE, 'profile': PROFILE, 'app_id': app_id, 'grant_id': grant['id'],
                  'grant_revision': grant['revision'], **{key: definition[key] for key in ('definition_hash', 'projection_hash', 'inputs_hash', 'aliases_hash')},
                  'nonce': secrets.token_hex(16), 'created': now, 'expires': expires, 'reviewed_at': now,
                  'origin': normalized_origin, 'sharing_notice': SHARE_NOTICE, 'run_notice': RUN_NOTICE}
        return {'ticket': ticket, 'signature': self.runtime.authority.signature(ticket),
                'preview': {'profile': PROFILE, 'title': context['workflow']['name'], 'recipients': copy.deepcopy(definition['aliases']),
                            'expires': expires, 'sharing_notice': SHARE_NOTICE, 'run_notice': RUN_NOTICE}}

    def _ticket(self, body, workflow, principal):
        if not isinstance(body, dict) or set(body) != CONTEXT_FIELDS:
            raise ValueError('Provide one exact run ticket and separate current sharing/execution declarations.')
        ticket = body['ticket']
        if (not isinstance(ticket, dict) or set(ticket) != TICKET_FIELDS or not isinstance(body['signature'], str)
                or not hmac.compare_digest(body['signature'], self.runtime.authority.signature(ticket))
                or ticket['audience'] != TICKET_AUDIENCE or ticket['profile'] != PROFILE
                or ticket['sharing_notice'] != SHARE_NOTICE or ticket['run_notice'] != RUN_NOTICE
                or body['sharing_authority'] is not True or body['sharing_notice'] != SHARE_NOTICE
                or body['run_authority'] is not True or body['run_notice'] != RUN_NOTICE
                or principal['kind'] != 'deployment' or principal['subject'] != ticket['app_id']
                or not isinstance(ticket['app_id'], str) or not re.fullmatch(r'app_[a-f0-9]{32}', ticket['app_id'])
                or not isinstance(ticket['grant_id'], str) or not re.fullmatch(r'dg_[a-f0-9]{32}', ticket['grant_id'])
                or type(ticket['grant_revision']) is not int or ticket['grant_revision'] < 1
                or not isinstance(ticket['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', ticket['nonce'])
                or not _time(ticket['created']) <= time.time() < _time(ticket['expires'])
                or ticket['expires'] > ticket['created'] + 300 or ticket['reviewed_at'] != ticket['created']):
            raise ValueError('The run ticket or explicit authorization expired or changed.')
        context = self.current(ticket['app_id'], origin=body['origin']); grant = context['grant']
        from .workflow_apps import normalize_origins
        if (normalize_origins([body['origin']])[0] != ticket['origin'] or ticket['grant_id'] != grant['id']
                or ticket['grant_revision'] != grant['revision'] or _graph(workflow) != _graph(context['workflow'])
                or any(ticket[key] != grant['definition'][key] for key in ('definition_hash', 'projection_hash', 'inputs_hash', 'aliases_hash'))
                or ticket['expires'] > grant['expires']):
            raise ValueError('The reviewed deployment input, recipients or grant changed.')
        self._epoch(ticket['reviewed_at'])
        return {'profile': PROFILE, 'ticket': copy.deepcopy(ticket), 'signature': body['signature'],
                'sharing_authorized': True, 'run_authorized': True}

    def admit(self, workflow, claims, body, *, source, profile, fallback):
        app_id = claims.get('subject') if claims.get('kind') == 'deployment' else None
        registered = bool(app_id and self.is_v12(app_id))
        if body is None and not registered:
            return None
        if (body is None or not registered or source != 'webapp' or profile != 'standard' or fallback
                or any(node.get('data', {}).get('credential_refs') for node in workflow['nodes'])):
            raise ValueError('This deployment requires its own manual standard per-run authorization.')
        return self._ticket(body, workflow, claims)

    def run_scope(self, row, workflow):
        authority = self.runtime.authority.run(row['id'], workflow['id'], row['digest'], row['source'])
        principal = authority['principal']['payload'] if authority else {}
        scope = principal.get('deployment_consent')
        registered = principal.get('kind') == 'deployment' and self.is_v12(principal.get('subject'))
        if scope is None and not registered:
            return
        if (not isinstance(scope, dict) or set(scope) != {'profile', 'ticket', 'signature', 'sharing_authorized', 'run_authorized'}
                or scope['profile'] != PROFILE or scope['sharing_authorized'] is not True or scope['run_authorized'] is not True
                or row['source'] != 'webapp' or authority.get('grant_id') is not None
                or row['actor'] != 'webapp-v12:' + scope['ticket']['app_id'] or row['idempotency_key'] != scope['ticket']['nonce']
                or digest(workflow) != row['digest'] or self.runtime.budgets.get(row)['profile'] != 'standard'):
            raise ValueError('Current deployment run purpose is required.')
        body = {'ticket': scope['ticket'], 'signature': scope['signature'], 'sharing_authority': True,
                'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE,
                'origin': scope['ticket']['origin']}
        if self._ticket(body, workflow, principal) != scope:
            raise ValueError('The deployment run purpose changed.')

    def dispatch_guard(self, row, workflow):
        try:
            return self.run_scope(row, workflow)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise ExecutionDenied('The current deployment authorization is unavailable.', error_code='POLICY_DENIED') from None

    def replay_scope(self, row, scope):
        records = self.store.query('SELECT payload,signature FROM workflow_run_authority WHERE run_id=?', (row['id'],))
        if len(records) != 1 or len(records[0]['payload']) > 16384:
            raise ValueError('The previous run authority is unavailable.')
        value = json.loads(records[0]['payload']); principal = value['principal']
        if (not hmac.compare_digest(records[0]['signature'], self.runtime.authority.signature(value))
                or not hmac.compare_digest(principal['signature'], self.runtime.authority.signature(principal['payload']))
                or value.get('run_id') != row['id'] or value.get('digest') != row['digest']
                or value.get('workflow_id') != row['workflow_id'] or value.get('source') != row['source'] or row['source'] != 'webapp'
                or row['actor'] != 'webapp-v12:' + scope['ticket']['app_id'] or row['idempotency_key'] != scope['ticket']['nonce']
                or principal['payload'].get('kind') != 'deployment' or principal['payload'].get('subject') != scope['ticket']['app_id']
                or principal['payload'].get('audience') != 'workflow-runtime-v1' or principal['payload'].get('workflow_id') != row['workflow_id']
                or not _time(row['created']) < _time(principal['payload'].get('expires')) <= scope['ticket']['expires']
                or principal['payload'].get('deployment_consent') != scope or value.get('grant_id') is not None):
            raise ValueError('The idempotency key belongs to another deployment purpose.')

    def revoke(self, app_id, revision):
        if type(revision) is not int:
            raise ValueError('Use the current deployment grant revision.')
        with self.store.tx() as db:
            changed = db.execute('UPDATE workflow_deployment_grants SET active=0,revision=revision+1,revoked=? WHERE app_id=? AND active=1 AND revision=?',
                                 (time.time(), app_id, revision)).rowcount
        if changed != 1:
            raise ValueError('The deployment grant revision changed.')
        for row in self.store.query("SELECT id FROM workflow_runs WHERE actor=? AND status IN ('queued','running')", ('webapp-v12:' + app_id,)):
            self.runtime.cancel(row['id'])
        return {'app_id': app_id, 'active': False, 'revision': revision + 1, 'profile': PROFILE}


Consent = DeploymentConsent
