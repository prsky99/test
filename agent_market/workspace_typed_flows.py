"""Private typed MCP DAGs with whole-graph consent and no automatic replay."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from .capability_contracts import CONTRACTS, validate
from .capability_registry import Registry, version_parts, digest
from .private_artifact_keys import ArtifactSigner, ArtifactCipher
from .workspace_access import (SessionActor, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid,
    _canonical, _hash, _identity, _revision, _rows, _tree, _safe_text, _literals)
from .workspace_execution import _slots

PROFILE = 'workspace-private-typed-flow-v1'
NOTICE = 'workspace-whole-graph-run-v1'
ALLOWED = ('news.search.v1', 'docs.search.v1', 'products.compare.v1', 'products.compare.v2')
LIMITS = {'nodes': 10, 'calls': 10, 'seconds': 60, 'node_seconds': 12, 'pending_tickets': 20,
          'ticket_seconds': 300, 'versions': 100, 'daily_runs': 100, 'output_bytes': 65536}
# Providers limit bursts (observed: the sixth call within about four seconds
# fails), so consecutive calls to one agent are spaced within this process.
AGENT_INTERVAL_SECONDS = 1.25
_last_dispatch, _pace_lock = {}, threading.Lock()


def _pace(resource_id, deadline, stopped):
    with _pace_lock:
        now = time.monotonic()
        start = max(now, _last_dispatch.get(resource_id, 0.0) + AGENT_INTERVAL_SECONDS)
        _last_dispatch[resource_id] = start
    wait = start - now
    if wait > 0 and (time.time() + wait >= deadline or stopped.wait(wait)):
        raise WorkspaceDenied()


SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_typed_flows(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
       revision INTEGER NOT NULL,active INTEGER NOT NULL,version_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_typed_flow_versions(id TEXT PRIMARY KEY,flow_id TEXT NOT NULL,
       workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,UNIQUE(flow_id,revision))''',
    '''CREATE TABLE IF NOT EXISTS workspace_typed_flow_tickets(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
       flow_id TEXT NOT NULL,version_id TEXT NOT NULL,expires REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,run_id TEXT UNIQUE)''',
    '''CREATE TABLE IF NOT EXISTS workspace_typed_flow_runs(id TEXT PRIMARY KEY,ticket_id TEXT UNIQUE NOT NULL,
       workspace_id TEXT NOT NULL,flow_id TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,deadline REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_typed_flow_steps(run_id TEXT NOT NULL,node_id TEXT NOT NULL,
       status TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(run_id,node_id))''',
    'CREATE TABLE IF NOT EXISTS workspace_typed_flow_restore_blocks(id TEXT PRIMARY KEY)',
    'CREATE INDEX IF NOT EXISTS workspace_typed_flow_run_scope ON workspace_typed_flow_runs(workspace_id,created)',
    # Workspaces keep any number of workflows (11-01); listing pages through them by id.
    'CREATE INDEX IF NOT EXISTS workspace_typed_flow_scope ON workspace_typed_flows(workspace_id,id)',
)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='private-typed-flow')


def _schema_path(schema, path):
    if type(path) is not list or not 1 <= len(path) <= 6:
        raise WorkspaceInvalid()
    current = schema
    for component in path:
        if type(component) is str and current.get('type') == 'object' and component in current.get('properties', {}):
            current = current['properties'][component]
        elif type(component) is int and current.get('type') == 'array' and 0 <= component < min(current.get('maxItems', 10), 10):
            current = current['items']
        else:
            raise WorkspaceInvalid()
    return current


def _types(schema):
    kind = schema.get('type')
    if type(kind) is str:
        return {kind}
    if type(kind) is list:
        return set(kind)
    if 'const' in schema:
        return {_primitive_type(schema['const'])}
    if 'enum' in schema:
        return {_primitive_type(value) for value in schema['enum']}
    return set()


def _primitive_type(value):
    return {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null', float: 'number'}.get(type(value))


def _project(value, path):
    try:
        for component in path:
            if type(component) is str and type(value) is dict:
                value = value[component]
            elif type(component) is int and type(value) is list:
                value = value[component]
            else:
                raise WorkspaceInvalid()
        return copy.deepcopy(value)
    except (KeyError, IndexError, TypeError):
        raise WorkspaceInvalid() from None


class _AdapterOutputRejected(WorkspaceInvalid):
    pass


class TypedFlows:
    # Names the engine whose authority check the execution worker must reuse.
    EXECUTOR = 'admin'

    def __init__(self, execution, registry=None):
        self.execution, self.access, self.store = execution, execution.access, execution.store
        self.registry = registry or Registry(self.store)
        self.authority_guard = None
        key = hmac.new(self.access.key, PROFILE.encode(), hashlib.sha256).digest()
        self.signer = ArtifactSigner(key, PROFILE)
        self.cipher = ArtifactCipher(PROFILE + ':outputs')
        with execution._internal() as db:
            for statement in SCHEMA:
                db.execute(statement)

    def _open(self, row, fields):
        try:
            if len(row['payload']) > 200000:
                raise WorkspaceConflict()
            value = json.loads(row['payload'])
            if type(value) is not dict:
                raise WorkspaceConflict()
            _tree({name: item for name, item in value.items() if name != 'encrypted_output'})
            if (type(value) is not dict or value.get('profile') != PROFILE or not self.signer.verify(value, row['signature'])
                    or any(value.get(name) != row[name] for name in fields)):
                raise WorkspaceConflict()
            return value
        except (ValueError, TypeError, KeyError):
            raise WorkspaceConflict() from None

    def _authority(self, ws, actor, *, write=True):
        if not isinstance(actor, SessionActor):
            raise WorkspaceDenied()
        membership, user = self.access._access(ws, actor, write=write)
        return {'workspace_id': ws, 'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': membership['revision'], 'member_revision': membership['member_revision'],
                'member_role': membership['member_role'], 'user_role': user['role']}

    def _actor_from_claims(self, claims):
        return SessionActor(claims['actor_user_id'], claims['session_ref'])

    def _guard(self, db, ticket, claims):
        if self.authority_guard is not None:
            self.authority_guard(db, ticket, claims)

    def _pin(self, db, node, arguments):
        from .concierge.execution_policy import admit
        rid, contract = node['resource_id'], node['contract_id']
        if type(rid) is not int or not 0 < rid < 2**31 or contract not in ALLOWED:
            raise WorkspaceInvalid()
        resource = self.store.resource(rid)
        try:
            validate(contract, arguments)
            admit(resource, 'mcp', public=True)
            parts = version_parts(resource)
            vid = 'cv_' + digest([rid, *parts[:3]])[:32]
            rows = _rows(db, 'SELECT v.*,a.agent_ref FROM connection_versions v JOIN connection_agents a ON a.resource_id=v.resource_id WHERE v.id=?', (vid,))
            approvals = _rows(db, 'SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?', (vid, contract))
            if len(rows) != 1 or len(approvals) != 1 or not parts[3] or parts[2] != 'mcp-stateless-v1':
                raise WorkspaceDenied()
            tool = approvals[0]['tool']
            full = json.loads(resource['usage_full_tools']) if type(resource.get('usage_full_tools')) is str else resource.get('usage_full_tools')
            specs = [spec for spec in full if type(spec) is dict and spec.get('name') == tool] if type(full) is list else []
            from .capability_adapter_dispatch import profile as adapter_profile, arguments as adapter_arguments
            adapter=adapter_profile(resource,contract,tool)
            if len(specs) != 1 or not adapter and any(specs[0].get(field) != CONTRACTS[contract][schema] for field, schema in (('inputSchema', 'input_schema'), ('outputSchema', 'output_schema'))):
                raise WorkspaceDenied()
            profile = {name: rows[0][name] for name in ('id', 'resource_id', 'agent_ref', 'binding_hash', 'schema_hash', 'profile_version', 'schema_complete')}
            projection = self.registry.projection(resource, version=profile)
            if (not projection.get('connection_readiness', {}).get('verified_callable')
                    or not any(item['id'] == contract and item['verified'] for item in projection.get('capability_contracts', []))):
                raise WorkspaceDenied()
            provider_input=adapter_arguments(resource,contract,tool,arguments,expected=adapter)
            _, binding = self.execution._resource(db, {'resource_id': rid, 'data': {'tool': tool, 'input': provider_input}})
            return {'resource_id': rid, 'contract_id': contract, 'tool': tool, 'version': profile,
                    'approval': approvals[0], 'binding_hash': binding, **({'adapter':adapter} if adapter else {})}
        except (ValueError, TypeError, KeyError):
            raise WorkspaceDenied() from None

    def _definition(self, definition):
        from .concierge.execution_policy import validate_arguments
        _tree(definition)
        if type(definition) is not dict or set(definition) != {'nodes'} or type(definition['nodes']) is not list or not 1 <= len(definition['nodes']) <= LIMITS['nodes']:
            raise WorkspaceInvalid()
        nodes = {}
        for node in definition['nodes']:
            if (type(node) is not dict or set(node) != {'id', 'resource_id', 'contract_id', 'input', 'bindings', 'after', 'when'}
                    or type(node['id']) is not str or not re.fullmatch('[a-z][a-z0-9_]{0,31}', node['id']) or node['id'] in nodes
                    or node['contract_id'] not in ALLOWED or type(node['input']) is not dict or type(node['bindings']) is not dict
                    or type(node['after']) is not list or len(node['after']) >= LIMITS['nodes'] or any(type(item) is not str for item in node['after'])
                    or len(set(node['after'])) != len(node['after'])):
                raise WorkspaceInvalid()
            nodes[node['id']] = node
        for node in nodes.values():
            schema = CONTRACTS[node['contract_id']]['input_schema']
            properties = schema['properties']
            if (set(node['input']) & set(node['bindings']) or set(node['input']) | set(node['bindings']) != set(properties)
                    or any(identity not in nodes or identity == node['id'] for identity in node['after'])):
                raise WorkspaceInvalid()
            for name, value in node['input'].items():
                _literals({name: value})
                validate_arguments({'inputSchema': {'type': 'object', 'properties': {name: properties[name]}, 'required': [name], 'additionalProperties': False}}, {name: value})
            for name, source in node['bindings'].items():
                if type(source) is not dict or set(source) != {'node_id', 'path'} or type(source['node_id']) is not str or source['node_id'] not in node['after']:
                    raise WorkspaceInvalid()
                source_schema = _schema_path(CONTRACTS[nodes[source['node_id']]['contract_id']]['output_schema'], source['path'])
                types = _types(source_schema)
                if not types or not types.issubset({'string', 'integer', 'number', 'boolean'}) or not types.issubset(_types(properties[name])):
                    raise WorkspaceInvalid()
            condition = node['when']
            if condition is not None:
                if type(condition) is not dict or set(condition) != {'node_id', 'path', 'equals'} or type(condition['node_id']) is not str or condition['node_id'] not in node['after']:
                    raise WorkspaceInvalid()
                source_schema = _schema_path(CONTRACTS[nodes[condition['node_id']]['contract_id']]['output_schema'], condition['path'])
                allowed = source_schema.get('enum', [True, False] if source_schema.get('type') == 'boolean' else [])
                if not allowed or not any(type(condition['equals']) is type(value) and condition['equals'] == value for value in allowed):
                    raise WorkspaceInvalid()
        order, remaining = [], set(nodes)
        while remaining:
            ready = sorted(identity for identity in remaining if all(parent in order for parent in nodes[identity]['after']))
            if not ready:
                raise WorkspaceInvalid()
            order.extend(ready); remaining.difference_update(ready)
        return {'nodes': [copy.deepcopy(nodes[identity]) for identity in order]}

    @staticmethod
    def _sample(node):
        # Used for policy/schema admission only; it is never sent to a provider.
        result = copy.deepcopy(node['input'])
        for name in node['bindings']:
            schema = CONTRACTS[node['contract_id']]['input_schema']['properties'][name]
            result[name] = {'string': 'Reviewed prior step value', 'integer': 1, 'number': 1, 'boolean': False}[next(iter(_types(schema)))]
        return result

    def _flow(self, db, ws, identity, *, active=True):
        _identity(identity, 'wtf')
        rows = _rows(db, 'SELECT * FROM workspace_typed_flows WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]; value = self._open(row, ('id', 'workspace_id', 'revision', 'active', 'version_id'))
        if active and (not row['active'] or db.execute('SELECT 1 FROM workspace_typed_flow_restore_blocks WHERE id=?', (identity,)).fetchone()):
            raise WorkspaceDenied()
        return row, value

    def _version(self, db, ws, flow, identity):
        _identity(identity, 'wtv')
        rows = _rows(db, 'SELECT * FROM workspace_typed_flow_versions WHERE id=? AND workspace_id=? AND flow_id=?', (identity, ws, flow))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self._open(rows[0], ('id', 'workspace_id', 'flow_id', 'revision'))
        if self._definition(value['definition']) != value['definition']:
            raise WorkspaceConflict()
        return value

    def options(self, ws, actor):
        with self.access._tx(actor, readonly=True) as (db, _):
            authority = self._authority(ws, actor, write=False); candidates = []
            rows = _rows(db, 'SELECT DISTINCT v.resource_id,a.contract_id FROM connection_versions v JOIN capability_approvals a ON a.version_id=v.id ORDER BY v.resource_id,a.contract_id LIMIT 100')
            for row in rows:
                if row['contract_id'] not in ALLOWED:
                    continue
                candidates.append({'resource_id': row['resource_id'], 'contract_id': row['contract_id']})
            return {'profile': PROFILE, 'limits': dict(LIMITS), 'contracts': list(ALLOWED), 'candidates': candidates,
                    'candidates_require_current_review': True, 'can_edit': authority['member_role'] in ('owner', 'editor') and authority['user_role'] != 'operator',
                    'publication': False, 'deployment': False, 'fallback': False, 'notice': NOTICE}

    def save(self, ws, body, actor):
        with self.access._tx(actor, write=True) as (db, _):
            return self._save_in_transaction(db, ws, body, actor)

    def _save_in_transaction(self, db, ws, body, actor):
        """Compose atomically with a reviewed server-side factory command."""
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        if type(body) is not dict or set(body) != {'flow_id', 'revision', 'name', 'definition'} or not _revision(body['revision'], zero=True):
            raise WorkspaceInvalid()
        name = _safe_text(body['name'], 120); definition = self._definition(body['definition'])
        self._authority(ws, actor)
        pins = {node['id']: self._pin(db, node, self._sample(node)) for node in definition['nodes']}
        now = time.time()
        if body['flow_id'] is None:
            if body['revision'] != 0:
                raise WorkspaceConflict()
            identity, revision = 'wtf_' + secrets.token_hex(16), 1
        else:
            row, _ = self._flow(db, ws, body['flow_id'])
            if row['revision'] != body['revision'] or row['revision'] >= LIMITS['versions']:
                raise WorkspaceConflict()
            identity, revision = row['id'], row['revision'] + 1
        version_id = 'wtv_' + secrets.token_hex(16)
        version = {'profile': PROFILE, 'id': version_id, 'flow_id': identity, 'workspace_id': ws, 'revision': revision,
                   'name': name, 'definition': definition, 'pins': pins, 'created': now, 'created_by': actor.user_id}
        state = {'profile': PROFILE, 'id': identity, 'workspace_id': ws, 'revision': revision, 'active': 1,
                 'version_id': version_id, 'name': name, 'updated': now}
        db.execute('INSERT INTO workspace_typed_flow_versions VALUES(?,?,?,?,?,?)', (version_id, identity, ws, revision, _canonical(version), self.signer.sign(version)))
        if body['flow_id'] is None:
            db.execute('INSERT INTO workspace_typed_flows VALUES(?,?,?,?,?,?,?)', (identity, ws, revision, 1, version_id, _canonical(state), self.signer.sign(state)))
        elif db.execute('UPDATE workspace_typed_flows SET revision=?,version_id=?,payload=?,signature=? WHERE id=? AND revision=?',
                        (revision, version_id, _canonical(state), self.signer.sign(state), identity, revision - 1)).rowcount != 1:
            raise WorkspaceConflict()
        self.access._audit(db, actor, ws, 'typed_flow.save', identity, revision)
        return {'id': identity, 'version_id': version_id, 'revision': revision, 'name': name, 'provider_calls': 0}

    def listing(self, ws, actor):
        # Every workflow is listed, retired ones included, so it can be found again (QA 19).
        # Workspaces have no workflow cap (11-01): read 500 at a time along workspace_typed_flow_scope.
        with self.access._tx(actor, readonly=True) as (db, _):
            self._authority(ws, actor, write=False)
            values, versions, after = [], {}, ''
            while True:
                page = _rows(db, 'SELECT * FROM workspace_typed_flows WHERE workspace_id=? AND id>? ORDER BY id LIMIT 500', (ws, after))
                values += [self._open(row, ('id', 'workspace_id', 'revision', 'active', 'version_id')) for row in page]
                if page:
                    versions.update((row['id'], self._open(row, ('id', 'workspace_id', 'flow_id', 'revision')))
                                    for row in _rows(db, '''SELECT v.* FROM workspace_typed_flow_versions v
                            JOIN workspace_typed_flows f ON f.version_id=v.id AND f.id=v.flow_id AND f.workspace_id=v.workspace_id
                            WHERE f.workspace_id=? AND f.id>? AND f.id<=? ORDER BY f.id LIMIT 500''', (ws, after, page[-1]['id'])))
                if len(page) < 500:
                    break
                after = page[-1]['id']
            for value in values:
                version = versions.get(value['version_id'])
                if not version or version['flow_id'] != value['id']:
                    raise WorkspaceConflict()
                # The signed version holds a definition validated when it was saved; counting
                # its nodes needs no second validation (most of a listing's time at 400 flows).
                nodes = version['definition'].get('nodes') if type(version.get('definition')) is dict else None
                if type(nodes) is not list:
                    raise WorkspaceConflict()
                value['step_count'] = len(nodes)
            return [{name: value[name] for name in ('id', 'version_id', 'revision', 'name', 'active', 'updated', 'step_count')}
                    for value in sorted(values, key=lambda item: (item['updated'], item['id']), reverse=True)]

    def _may_disable(self, ws, actor):
        """Additional role check, evaluated inside the disabling transaction."""

    def disable(self, ws, flow, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(ws, actor); self._may_disable(ws, actor); row, value = self._flow(db, ws, flow)
            if row['revision'] != body['revision']:
                raise WorkspaceConflict()
            value.update(active=0, revision=row['revision'] + 1, updated=time.time())
            if db.execute('UPDATE workspace_typed_flows SET active=0,revision=?,payload=?,signature=? WHERE id=? AND revision=? AND active=1',
                          (value['revision'], _canonical(value), self.signer.sign(value), flow, row['revision'])).rowcount != 1:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'typed_flow.disable', flow, value['revision'])
            return {'id': flow, 'active': False, 'revision': value['revision'], 'automatic_retry': False}

    def detail(self, ws, flow, actor):
        with self.access._tx(actor) as (db, _):
            self._authority(ws, actor, write=False); row, state = self._flow(db, ws, flow, active=False)
            version = self._version(db, ws, flow, row['version_id'])
            return {'id': flow, 'name': state['name'], 'revision': row['revision'], 'version_id': version['id'],
                    'definition': version['definition'], 'active': bool(row['active']), 'publication': False, 'deployment': False}

    def _binding(self, db, ws, flow, actor, *, pins=True):
        authority = self._authority(ws, actor); row, _ = self._flow(db, ws, flow)
        version = self._version(db, ws, flow, row['version_id'])
        # Recording a returned result must not depend on readiness that this
        # very call may have just changed; every dispatch re-checks its pin.
        if pins and {node['id']: self._pin(db, node, self._sample(node)) for node in version['definition']['nodes']} != version['pins']:
            raise WorkspaceDenied()
        return {**authority, 'flow_id': flow, 'flow_revision': row['revision'], 'version_id': version['id'],
                'version_hash': _hash(version), 'controls': self.execution._control(db)}, version

    def prepare(self, ws, flow, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            binding, version = self._binding(db, ws, flow, actor); now = time.time()
            if binding['flow_revision'] != body['revision']:
                raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM workspace_typed_flow_tickets WHERE workspace_id=? AND run_id IS NULL AND expires>?', (ws, now)).fetchone()[0] >= LIMITS['pending_tickets']:
                raise WorkspaceConflict()
            value = {'profile': PROFILE, 'id': 'wtt_' + secrets.token_hex(16), **binding,
                     'created': now, 'expires': now + LIMITS['ticket_seconds'], 'notice': NOTICE}
            db.execute('INSERT INTO workspace_typed_flow_tickets VALUES(?,?,?,?,?,?,?,NULL)',
                       (value['id'], ws, flow, value['version_id'], value['expires'], _canonical(value), self.signer.sign(value)))
            self.access._audit(db, actor, ws, 'typed_flow.prepare', value['id'], binding['flow_revision'])
            return {'ticket_id': value['id'], 'expires': value['expires'], 'notice': NOTICE,
                    'review': {'name': version['name'], 'nodes': version['definition']['nodes'],
                               'destinations': [{'node_id': node['id'], 'resource_id': node['resource_id'], 'contract_id': node['contract_id'], 'tool': version['pins'][node['id']]['tool'], **({'input_notice':version['pins'][node['id']]['adapter']['input_notice']} if version['pins'][node['id']].get('adapter') else {})} for node in version['definition']['nodes']],
                               'max_calls': len(version['definition']['nodes']), 'seconds': LIMITS['seconds'],
                               'prior_output_sharing': any(node['bindings'] for node in version['definition']['nodes']),
                               'provider_calls': 0, 'fallback': False, 'delivery': False}}

    def _ticket(self, db, ws, flow, identity):
        _identity(identity, 'wtt')
        rows = _rows(db, 'SELECT * FROM workspace_typed_flow_tickets WHERE id=? AND workspace_id=? AND flow_id=?', (identity, ws, flow))
        if len(rows) != 1:
            raise WorkspaceDenied()
        return rows[0], self._open(rows[0], ('id', 'workspace_id', 'flow_id', 'version_id', 'expires'))

    def _run(self, db, ws, flow, identity):
        _identity(identity, 'wtr')
        rows = _rows(db, 'SELECT * FROM workspace_typed_flow_runs WHERE id=? AND workspace_id=? AND flow_id=?', (identity, ws, flow))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]; value = self._open(row, ('id', 'ticket_id', 'workspace_id', 'flow_id', 'status', 'created', 'deadline'))
        ticket, claims = self._ticket(db, ws, flow, value['ticket_id'])
        if ticket['run_id'] != identity or value['ticket_hash'] != _hash(claims):
            raise WorkspaceConflict()
        return value, ticket, claims

    def _write_run(self, db, value):
        db.execute('UPDATE workspace_typed_flow_runs SET status=?,payload=?,signature=? WHERE id=?',
                   (value['status'], _canonical(value), self.signer.sign(value), value['id']))

    @staticmethod
    def _step_context(value):
        return {name: value[name] for name in ('profile', 'run_id', 'node_id', 'version_id', 'input_hash')}

    def _step(self, row, *, version_id=None, decrypt=True):
        value = self._open(row, ('run_id', 'node_id', 'status'))
        _identity(value['version_id'], 'wtv')
        if version_id is not None and value['version_id'] != version_id:
            raise WorkspaceConflict()
        if 'encrypted_output' in value and decrypt:
            if value.get('output') is not None:
                raise WorkspaceConflict()
            try:
                value['output'] = json.loads(self.cipher.open(_canonical(value['encrypted_output']).encode('ascii'),
                    self._step_context(value)))
                del value['encrypted_output']
            except (ValueError, TypeError, KeyError):
                raise WorkspaceConflict() from None
        return value

    def _write_step(self, db, value, *, insert=False):
        stored = copy.deepcopy(value)
        if self.cipher.configured and stored.get('output') is not None:
            stored['encrypted_output'] = json.loads(self.cipher.seal(_canonical(stored['output']).encode('ascii'),
                self._step_context(stored))); stored['output'] = None
        if insert:
            db.execute('INSERT INTO workspace_typed_flow_steps VALUES(?,?,?,?,?)', (value['run_id'], value['node_id'], value['status'], _canonical(stored), self.signer.sign(stored)))
        else:
            db.execute('UPDATE workspace_typed_flow_steps SET status=?,payload=?,signature=? WHERE run_id=? AND node_id=?',
                       (value['status'], _canonical(stored), self.signer.sign(stored), value['run_id'], value['node_id']))

    def _current(self, db, run, stopped, *, pins=True):
        value, _, claims = self._run(db, run['workspace_id'], run['flow_id'], run['id'])
        if stopped.is_set() or value['status'] != 'running' or time.time() >= value['deadline']:
            raise WorkspaceDenied()
        actor = self._actor_from_claims(claims)
        self._guard(db, value['ticket_id'], claims)
        current, version = self._binding(db, value['workspace_id'], value['flow_id'], actor, pins=pins)
        if any(claims.get(name) != item for name, item in current.items()):
            raise WorkspaceDenied()
        return value, version

    def _dispatch(self, run, node, arguments, stopped):
        from .concierge.execution_policy import ExecutionDenied
        try:
            with self.execution._internal() as db:
                current, version = self._current(db, run, stopped)
                if self._pin(db, node, arguments) != version['pins'][node['id']]:
                    raise WorkspaceDenied()
                rows = _rows(db, 'SELECT * FROM workspace_typed_flow_steps WHERE run_id=? AND node_id=?', (run['id'], node['id']))
                if len(rows) != 1:
                    raise WorkspaceDenied()
                step = self._step(rows[0], version_id=version['id'])
                if step['status'] != 'prepared' or step['input_hash'] != _hash(arguments):
                    raise WorkspaceDenied()
                if self.execution.meter is not None:
                    _, claims = self._ticket(db, run['workspace_id'], run['flow_id'], run['ticket_id'])
                    ordinal = db.execute("SELECT COUNT(*) FROM workspace_typed_flow_steps WHERE run_id=? AND status IN ('dispatched','succeeded','failed','unknown')", (run['id'],)).fetchone()[0] + 1
                    self.execution.meter.dispatch(db, claims, current, ordinal=ordinal)
                step.update(status='dispatched', dispatched=time.time()); self._write_step(db, step)
                current['dispatched'] = True; self._write_run(db, current)
        except (WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict):
            raise ExecutionDenied('The reviewed private graph is no longer current.', error_code='POLICY_DENIED') from None

    def _finish(self, run, status, code=None):
        with self.execution._internal() as db:
            value, _, claims = self._run(db, run['workspace_id'], run['flow_id'], run['id'])
            if value['status'] != 'running':
                return value
            if time.time() >= value['deadline']:
                status, code = ('unknown' if value['dispatched'] else 'denied'), 'TIME_LIMIT'
            elif status == 'succeeded':
                try:
                    self._guard(db, value['ticket_id'], claims)
                    current, _ = self._binding(db, value['workspace_id'], value['flow_id'], self._actor_from_claims(claims))
                    if any(claims.get(name) != item for name, item in current.items()):
                        raise WorkspaceDenied()
                except (WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict):
                    status, code = 'unknown', 'AUTHORITY_OR_OUTCOME_UNCONFIRMED'
            value.update(status=status, error_code=code, finished=time.time()); self._write_run(db, value)
            from .workspace_admin_events import emit
            customer = claims.get('actor_user_id')
            emit(self.store, db, 'execution.' + status,
                 customer=customer if isinstance(customer, str) and customer.startswith('cu_') else None,
                 workspace=value['workspace_id'], object_id=value['id'], outcome=status,
                 event_key='typed-execution:' + value['id'] + ':' + status, error_code=code)
            if self.execution.meter is not None:
                self.execution.meter.finish(db, value)
            return value

    def _work(self, run, version, stopped):
        from .concierge.http_security import outbound_operation
        from .workflow_persistence import dispatch_scope
        outputs, skipped = {}, set()
        try:
            for node in version['definition']['nodes']:
                with self.execution._internal() as db:
                    current, checked = self._current(db, run, stopped)
                if any(parent in skipped for parent in node['after']):
                    should_skip = True
                else:
                    condition = node['when']
                    should_skip = bool(condition is not None and _project(outputs[condition['node_id']], condition['path']) != condition['equals'])
                arguments = copy.deepcopy(node['input'])
                if not should_skip:
                    for name, source in node['bindings'].items():
                        arguments[name] = _project(outputs[source['node_id']], source['path'])
                    _literals(arguments)
                    try:
                        validate(node['contract_id'], arguments)
                    except ValueError:
                        raise WorkspaceInvalid() from None
                step = {'profile': PROFILE, 'run_id': run['id'], 'node_id': node['id'], 'version_id': version['id'], 'status': 'skipped' if should_skip else 'prepared',
                        'input_hash': _hash(arguments), 'dispatched': None, 'finished': time.time() if should_skip else None, 'output': None}
                with self.execution._internal() as db:
                    self._current(db, run, stopped); self._write_step(db, step, insert=True)
                if should_skip:
                    skipped.add(node['id']); continue
                _pace(node['resource_id'], run['deadline'], stopped)
                remaining = min(LIMITS['node_seconds'], run['deadline'] - time.time())
                if remaining <= 0:
                    raise WorkspaceDenied()
                from .edge_gateway.result_transport import parent_scope
                with parent_scope(run['id'],node['id']),outbound_operation(remaining), dispatch_scope(lambda: self._dispatch(run, node, arguments, stopped)):
                    from .capability_adapter_dispatch import arguments as adapter_arguments
                    pin=checked['pins'][node['id']]
                    provider_input=adapter_arguments(self.store.resource(node['resource_id']),node['contract_id'],pin['tool'],arguments,expected=pin.get('adapter'))
                    from .edge_gateway.native import execute as edge_execute
                    result = edge_execute(self.store, self.store.resource(node['resource_id']),
                        {'tool': pin['tool'], 'arguments': provider_input}, scope=run['id'] + ':' + node['id'])
                    if result is None:
                        result = self.execution.proxy.execute(node['resource_id'], pin['tool'], provider_input, public=True)
                with self.execution._internal() as db:
                    self._current(db, run, stopped, pins=False)
                    rows = _rows(db, 'SELECT * FROM workspace_typed_flow_steps WHERE run_id=? AND node_id=?', (run['id'], node['id']))
                    step = self._step(rows[0], version_id=checked['id'])
                    if step['status'] != 'dispatched':
                        raise WorkspaceDenied()
                    if type(result) is not dict or result.get('ok') is not True:
                        code = result.get('error_code') if type(result) is dict else 'UPSTREAM_PROTOCOL'
                        step.update(status='unknown' if code in ('UPSTREAM_TIMEOUT', 'UPSTREAM_NETWORK', 'UPSTREAM_PROTOCOL') else 'failed', finished=time.time())
                        self._write_step(db, step)
                        outcome = step['status']
                    else:
                        raw = result.get('result', result.get('output', result.get('data')))
                        raw = raw.get('structuredContent', raw) if type(raw) is dict else raw
                        resource = self.store.resource(node['resource_id'])
                        from .capability_adapter_dispatch import normalize
                        try:
                            raw=normalize(resource,node['contract_id'],checked['pins'][node['id']]['tool'],arguments,raw,expected=checked['pins'][node['id']].get('adapter'))
                        except ValueError:
                            if checked['pins'][node['id']].get('adapter'):
                                raise _AdapterOutputRejected() from None
                            raise WorkspaceInvalid() from None
                        output = self.execution._output(raw, resource)
                        try:
                            validate(node['contract_id'], arguments, output)
                        except ValueError:
                            raise WorkspaceInvalid() from None
                        if len(_canonical(outputs).encode('ascii')) + len(_canonical(output).encode('ascii')) > LIMITS['output_bytes']:
                            raise WorkspaceInvalid()
                        step.update(status='succeeded', output=output, finished=time.time()); self._write_step(db, step)
                        outputs[node['id']] = output; outcome = 'succeeded'
                if outcome != 'succeeded':
                    return self._finish(run, outcome, 'UPSTREAM_FAILURE')
            return self._finish(run, 'succeeded')
        except Exception as error:
            with self.execution._internal() as db:
                current, _, _ = self._run(db, run['workspace_id'], run['flow_id'], run['id'])
            if isinstance(error, _AdapterOutputRejected):
                with self.execution._internal() as db:
                    rows=_rows(db,'SELECT * FROM workspace_typed_flow_steps WHERE run_id=? AND node_id=?',(run['id'],node['id']))
                    rejected=self._step(rows[0],version_id=checked['id'])
                    if rejected['status']=='dispatched':
                        rejected.update(status='failed',finished=time.time());self._write_step(db,rejected)
                result=self._finish(run,'failed','CONTRACT_REJECTED')
                from .capability_adapter_dispatch import evidence_dataset
                pin=checked['pins'][node['id']]
                expected=(pin['version']['binding_hash'],pin['version']['schema_hash'],pin['version']['profile_version'],True)
                self.registry.record(pin['version'],scope='contract',outcome='failed',
                    started=rejected['dispatched'],finished=time.time(),contract_id=node['contract_id'],
                    code='UPSTREAM_PROTOCOL',dataset=evidence_dataset(pin['adapter']),
                    guard=lambda:version_parts(self.store.resource(node['resource_id']))==expected)
                return result
            if isinstance(error, WorkspaceInvalid):
                return self._finish(run, 'failed', 'CONTRACT_REJECTED')
            return self._finish(run, 'unknown' if current['dispatched'] else 'denied', 'AUTHORITY_OR_OUTCOME_UNCONFIRMED')

    def execute(self, ws, flow, body, actor):
        if type(body) is not dict or set(body) != {'ticket_id', 'authorized', 'notice'} or body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        control = getattr(self.store, '_service_control', None)
        remote = getattr(self.store, '_service_role', 'legacy') in ('frontend', 'admin')
        if remote and (control is None or not control.status('execution').get('available')):
            raise WorkspaceConflict()
        if not _slots.acquire(blocking=False):
            raise WorkspaceConflict()
        submitted = False
        try:
            with self.access._tx(actor, write=True) as (db, _):
                self._authority(ws, actor); ticket, claims = self._ticket(db, ws, flow, body['ticket_id'])
                if claims['actor_user_id'] != actor.user_id or claims['session_ref'] != actor.session_ref:
                    raise WorkspaceDenied()
                if ticket['run_id']:
                    run, _, _ = self._run(db, ws, flow, ticket['run_id'])
                    return {'run': self._dto(db, run), 'replayed': True}
                self._guard(db, ticket['id'], claims)
                binding, version = self._binding(db, ws, flow, actor); now = time.time()
                if claims['expires'] <= now or any(claims.get(name) != value for name, value in binding.items()):
                    raise WorkspaceDenied()
                if (db.execute('SELECT COUNT(*) FROM workspace_typed_flow_runs WHERE workspace_id=? AND created>?', (ws, now - 86400)).fetchone()[0] >= LIMITS['daily_runs']
                        or db.execute("SELECT COUNT(*) FROM workspace_typed_flow_runs WHERE status='running' AND deadline>?", (now,)).fetchone()[0]
                           + db.execute("SELECT COUNT(*) FROM workspace_private_runs WHERE status IN ('prepared','dispatched') AND deadline>?", (now,)).fetchone()[0] >= 4):
                    raise WorkspaceConflict()
                run = {'profile': PROFILE, 'id': 'wtr_' + secrets.token_hex(16), 'ticket_id': ticket['id'], 'ticket_hash': _hash(claims),
                       'workspace_id': ws, 'flow_id': flow, 'status': 'running', 'created': now, 'deadline': now + LIMITS['seconds'],
                       'dispatched': False, 'finished': None, 'error_code': None}
                if remote:
                    run['worker_execution'] = True
                    run['executor'] = self.EXECUTOR
                db.execute('INSERT INTO workspace_typed_flow_runs VALUES(?,?,?,?,?,?,?,?,?)',
                           (run['id'], ticket['id'], ws, flow, 'running', now, run['deadline'], _canonical(run), self.signer.sign(run)))
                if self.execution.meter is not None:
                    self.execution.meter.admit(db, claims, run)
                if db.execute('UPDATE workspace_typed_flow_tickets SET run_id=? WHERE id=? AND run_id IS NULL', (run['id'], ticket['id'])).rowcount != 1:
                    raise WorkspaceConflict()
                self.access._audit(db, actor, ws, 'typed_flow.admit', run['id'], binding['flow_revision'])
            if remote:
                # Keep the existing response contract, while execution ownership
                # survives a web disconnect or restart. Replays use the same ID.
                while time.time() < run['deadline']:
                    result = self.get(ws, flow, run['id'], actor)
                    if result['status'] != 'running':
                        return {'run': result, 'replayed': False}
                    time.sleep(.25)
                return {'run': self.get(ws, flow, run['id'], actor), 'replayed': False}
            stopped = threading.Event(); future = _pool.submit(self._work, run, version, stopped); submitted = True
            future.add_done_callback(lambda _: _slots.release())
            try:
                future.result(timeout=LIMITS['seconds'])
            except FutureTimeout:
                stopped.set(); self._finish(run, 'unknown', 'TIME_LIMIT')
            finally:
                stopped.set()
            return {'run': self.get(ws, flow, run['id'], actor), 'replayed': False}
        finally:
            if not submitted:
                _slots.release()

    def execute_admitted(self, identity, ws, flow):
        """Consume a once-claimed run; revalidate signed consent before I/O."""
        stopped = threading.Event()
        with self.execution._internal() as db:
            run, _, _ = self._run(db, ws, flow, identity)
            if run.get('worker_execution') is not True:
                raise WorkspaceDenied()
            _, version = self._current(db, run, stopped)
        return self._work(run, version, stopped)

    def admitted_actor_kind(self, identity, ws, flow):
        """Which authority admitted a worker run; customer runs must execute under the customer adapter."""
        with self.execution._internal() as db:
            _, _, claims = self._run(db, ws, flow, identity)
        return 'customer' if claims.get('actor_kind') == 'customer' else 'staff'

    def reconcile_interrupted(self, identity, ws, flow):
        with self.execution._internal() as db:
            run, _, _ = self._run(db, ws, flow, identity)
            if run.get('worker_execution') is not True or run['deadline'] > time.time():
                raise WorkspaceDenied()
        return self._finish(run, 'unknown', 'TIME_LIMIT')

    def _dto(self, db, value, *, output=True):
        blocked = db.execute('SELECT 1 FROM workspace_typed_flow_restore_blocks WHERE id=?', (value['flow_id'],)).fetchone()
        interrupted = value['status'] == 'running' and (value['deadline'] <= time.time() or blocked)
        result = {name: value[name] for name in ('id', 'status', 'created', 'deadline', 'finished', 'error_code')}
        if interrupted:
            result.update(status='unknown', error_code='INTERRUPTED', finished=None)
        _, claims = self._ticket(db, value['workspace_id'], value['flow_id'], value['ticket_id'])
        result['version_id'] = claims['version_id']
        steps = [self._step(row, version_id=claims['version_id'], decrypt=output and result['status']=='succeeded' and not blocked)
                 for row in _rows(db, 'SELECT * FROM workspace_typed_flow_steps WHERE run_id=? ORDER BY node_id', (value['id'],))]
        result['steps'] = [{'node_id': item['node_id'], 'status': item['status'],
                            'output': item.get('output') if output and result['status'] == 'succeeded' and not blocked else None} for item in steps]
        result['automatic_retry'] = False
        return result

    def get(self, ws, flow, identity, actor):
        with self.access._tx(actor) as (db, _):
            self._authority(ws, actor, write=False); self._flow(db, ws, flow, active=False)
            value, _, _ = self._run(db, ws, flow, identity)
            return self._dto(db, value)

    def runs(self, ws, flow, actor):
        with self.access._tx(actor, readonly=True) as (db, _):
            self._authority(ws, actor, write=False); self._flow(db, ws, flow, active=False)
            rows = _rows(db, 'SELECT id FROM workspace_typed_flow_runs WHERE workspace_id=? AND flow_id=? ORDER BY created DESC,id LIMIT 30', (ws, flow))
            return [self._dto(db, self._run(db, ws, flow, row['id'])[0]) for row in rows]
