"""Separately approved immutable typed-DAG SDK 2 deployments.

Customer attribution stays opaque and uses current customer authority at every
external dispatch. Existing single-tool releases keep their own contract.
"""
import secrets

from .customer_identity import CustomerActor
from .customer_workspace_runtime import CustomerRuntimeActor
from .workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, _canonical, _hash, _rows, _tree
from .workspace_execution import _now
from .workspace_release import WorkspaceReleases
from .workspace_typed_flows import TypedFlows, LIMITS, NOTICE

PROFILE = 'workspace-typed-executable-release-v1'
SDK_PROFILE = 'workspace-typed-sdk-v2'
RUN_NOTICE = 'workspace-sdk-whole-graph-run-v2'


class CustomerTypedFlows(TypedFlows):
    """Execution adapter only; no customer provisioning or edit transport."""
    def _authority(self, ws, actor, *, write=True):
        if type(actor) is not CustomerRuntimeActor or actor.workspace_id != ws:
            raise WorkspaceDenied()
        scope = self.access._authorize(actor, write)
        self.access._access(ws, actor, write=write)
        return {'workspace_id': ws, 'actor_kind': 'customer', 'actor_user_id': actor.customer_id,
                'session_ref': actor.session_ref, 'token_ref': actor.token_ref,
                'workspace_revision': scope['workspace_revision'], 'member_revision': scope['link_revision'],
                'member_role': scope['role'], 'user_role': 'customer'}

    def _actor_from_claims(self, claims):
        return self.access.actor_from_claims(claims)

    def save(self, *args, **kwargs):
        raise WorkspaceDenied()

    def disable(self, *args, **kwargs):
        raise WorkspaceDenied()


class WorkspaceTypedReleases(WorkspaceReleases):
    def __init__(self, typed_flows, *, customer_identity, customer_flows):
        self.typed, self.customer_typed = typed_flows, customer_flows
        if (typed_flows.execution.store is not customer_flows.store
                or customer_flows.access.identity is not customer_identity):
            raise WorkspaceDenied()
        super().__init__(typed_flows.execution, customer_identity=customer_identity,
                         customer_executor=customer_flows)
        customer_flows.authority_guard = self.guard_ticket

    def _release(self, db, rid, *, active=True):
        row, value = super()._release(db, rid, active=active)
        if value.get('profile') != PROFILE:
            raise WorkspaceDenied()
        return row, value

    def _deployment(self, db, app, *, active=True):
        row, value = super()._deployment(db, app, active=active)
        self._release(db, value['release_id'], active=active)
        return row, value

    def _profile(self, db, version):
        for node in version['definition']['nodes']:
            self._release_profile(db, version['id'], node['resource_id'], version['pins'][node['id']]['tool'],
                                  admission_scope=(version['workspace_id'], version['flow_id']))

    def _current(self, db, release, actor, *, customer=False):
        engine = self.customer_typed if customer else self.typed
        bound, version = engine._binding(db, release['workspace_id'], release['draft_id'], actor)
        if (not 2 <= len(version['definition']['nodes']) <= LIMITS['nodes']
                or any(bound[k] != release[k] for k in ('flow_revision', 'version_id', 'version_hash'))
                or version['id'] != release['snapshot_id']):
            raise WorkspaceDenied()
        self._profile(db, version)
        return bound, version

    def _admin_current(self, db, release, actor):
        return self._current(db, release, actor)

    def _customer_current(self, db, release, actor):
        scope = self._customer(db, actor, release['workspace_id'])
        return self._current(db, release, self.customer_typed.access.from_scope(scope), customer=True)[0]

    def create(self, ws, flow, version_id, body, actor):
        _tree(body)
        if (type(body) is not dict or set(body) != {'run_id', 'ttl_seconds'}
                or type(body['ttl_seconds']) is not int or not 300 <= body['ttl_seconds'] <= 2592000):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._owner(ws, actor)
            binding, version = self.typed._binding(db, ws, flow, actor)
            if version_id != version['id'] or not 2 <= len(version['definition']['nodes']) <= LIMITS['nodes']:
                raise WorkspaceDenied()
            self._profile(db, version)
            run, _, claims = self.typed._run(db, ws, flow, body['run_id'])
            if (run['status'] != 'succeeded' or not run['dispatched']
                    or any(claims.get(k) != binding[k] for k in ('flow_revision', 'version_id', 'version_hash'))):
                raise WorkspaceDenied()
            # Verify retained step signatures and full typed contracts; do not replay.
            result = self.typed._dto(db, run)
            if any(step['status'] not in ('succeeded', 'skipped') for step in result['steps']):
                raise WorkspaceDenied()
            if db.execute('SELECT COUNT(*) FROM workspace_executable_releases WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            now = _now(); identity = 'wrl_' + secrets.token_hex(16)
            value = {'profile': PROFILE, 'id': identity, 'workspace_id': ws, 'draft_id': flow,
                     'snapshot_id': version_id, 'created': now, 'expires': now + body['ttl_seconds'],
                     'flow_revision': binding['flow_revision'], 'version_id': version_id,
                     'version_hash': binding['version_hash'], 'test_run_id': run['id'],
                     'max_calls': len(version['definition']['nodes']), 'seconds': LIMITS['seconds']}
            state = {'id': identity, 'revision': 1, 'active': 1, 'revoked': None}
            db.execute('INSERT INTO workspace_executable_releases VALUES(?,?,?,?,1,1,?,?,NULL,?,?,?)',
                       (identity, ws, flow, version_id, now, value['expires'], _canonical(value), self._sign(value), self._state(state, 'release')))
            self.access._audit(db, actor, ws, 'typed_release.create', identity, 1)
            return self._dto({**value, **state})

    def releases(self, ws, flow, version_id, actor):
        with self.access._tx(actor) as (db, _):
            self.access._access(ws, actor)
            self.typed._version(db, ws, flow, version_id)
            return [self._dto(row) for row in _rows(db,
                'SELECT * FROM workspace_executable_releases WHERE workspace_id=? AND draft_id=? AND snapshot_id=? ORDER BY created DESC LIMIT 100',
                (ws, flow, version_id)) if self._release(db, row['id'], active=False)]

    def deploy(self, *args):
        return {**super().deploy(*args), 'profile': SDK_PROFILE}

    def deployments(self, ws, flow, version_id, rid, actor):
        with self.access._tx(actor) as (db, _):
            self.access._access(ws, actor); _, value = self._release(db, rid, active=False)
            self._scope(value, ws, flow, version_id)
            result = []
            for row in _rows(db, 'SELECT * FROM workspace_release_deployments WHERE release_id=? ORDER BY created DESC LIMIT 100', (rid,)):
                _, deployment = self._deployment(db, row['app_id'], active=False)
                result.append({**self._dto(row, True), 'allowed_origins': deployment['allowed_origins']})
            return result

    def package_config(self, ws, flow, version_id, app, actor):
        with self.access._tx(actor) as (db, _):
            self._owner(ws, actor); _, deployment = self._deployment(db, app)
            _, release = self._release(db, deployment['release_id']); self._scope(release, ws, flow, version_id)
            self._admin_current(db, release, actor)
            return {'app_id': app, 'profile': SDK_PROFILE, 'sdk_version': '2.1.0',
                    'allowed_origins': deployment['allowed_origins'], 'release_id': release['id']}

    def prepare(self, app, raw, request_origin):
        with self.execution._internal() as db:
            value, actor, release = self._token(db, app, raw, 'app-run', request_origin)
            runtime_actor = self.customer_typed.access.from_scope(self._customer(db, actor, release['workspace_id']))
        plan = self.customer_typed.prepare(release['workspace_id'], release['draft_id'],
                    {'revision': release['flow_revision']}, runtime_actor)
        with self.execution._internal() as db:
            self._token(db, app, raw, 'app-run', request_origin)
            ticket, claims = self.customer_typed._ticket(db, release['workspace_id'], release['draft_id'], plan['ticket_id'])
            if any(claims[k] != release[k] for k in ('flow_revision', 'version_id', 'version_hash')):
                raise WorkspaceDenied()
            link = {'ticket_id': ticket['id'], 'app_id': app, 'token_hash': self._ref(raw), 'origin': value['origin'],
                    'customer_id': actor.customer_id, 'session_ref': actor.session_ref, 'release_id': release['id'], 'created': _now()}
            db.execute('INSERT INTO workspace_app_run_links VALUES(?,?,?,?,?)',
                       (ticket['id'], app, self._ref(raw), _canonical(link), self._sign(link)))
        return {**plan, 'notice': RUN_NOTICE, 'profile': SDK_PROFILE}

    def guard_ticket(self, db, ticket, claims=None):
        tid = ticket['id'] if type(ticket) is dict else ticket
        links = _rows(db, 'SELECT * FROM workspace_app_run_links WHERE ticket_id=?', (tid,))
        if len(links) != 1:
            raise WorkspaceDenied()
        link = self._link(links[0]); tokens = _rows(db, 'SELECT * FROM workspace_app_tokens WHERE token_hash=?', (link['token_hash'],))
        if len(tokens) != 1:
            raise WorkspaceDenied()
        value = self._open(tokens[0]); actor = CustomerActor(value['customer_id'], value['session_ref'])
        grant, deployment = self._deployment(db, link['app_id']); row, release = self._release(db, link['release_id'])
        if (value.get('token_ref') != link['token_hash'] or value['app_id'] != link['app_id'] or value['audience'] != 'app-run'
                or deployment['release_id'] != release['id'] or value['release_id'] != release['id']):
            raise WorkspaceDenied()
        _, ticket_claims = self.customer_typed._ticket(db, release['workspace_id'], release['draft_id'], tid)
        scope = self._customer(db, actor, release['workspace_id'])
        if (ticket_claims.get('actor_kind') != 'customer' or ticket_claims['actor_user_id'] != link['customer_id']
                or ticket_claims['session_ref'] != link['session_ref'] or actor.customer_id != link['customer_id']
                or actor.session_ref != link['session_ref'] or any(ticket_claims[k] != release[k] for k in ('flow_revision', 'version_id', 'version_hash'))
                or value['expires'] <= _now() or value['grant_revision'] != grant['revision'] or value['release_revision'] != row['revision']
                or value['link_revision'] != scope['link_revision'] or value['workspace_revision'] != scope['workspace_revision']
                or link['origin'] != value['origin']):
            raise WorkspaceDenied()
        self._customer_current(db, release, actor)
        return True

    def execute(self, app, raw, body, request_origin):
        if type(body) is not dict or set(body) != {'ticket_id', 'authorized', 'notice'} or body['authorized'] is not True or body['notice'] != RUN_NOTICE:
            raise WorkspaceInvalid()
        with self.execution._internal() as db:
            value, actor, release = self._token(db, app, raw, 'app-run', request_origin)
            links = _rows(db, 'SELECT * FROM workspace_app_run_links WHERE ticket_id=? AND app_id=?', (body['ticket_id'], app))
            if len(links) != 1 or links[0]['token_hash'] != self._ref(raw):
                raise WorkspaceDenied()
            self.guard_ticket(db, body['ticket_id']); deployment = self._deployment(db, app)[1]
            if not db.execute('SELECT ticket_id FROM workspace_app_admissions WHERE ticket_id=?', (body['ticket_id'],)).fetchone():
                for seconds, limit in ((60, deployment['minute_limit']), (86400, deployment['day_limit'])):
                    if db.execute('SELECT COUNT(*) FROM workspace_app_admissions WHERE app_id=? AND created>?', (app, _now() - seconds)).fetchone()[0] >= limit:
                        raise WorkspaceConflict()
                db.execute('INSERT INTO workspace_app_admissions VALUES(?,?,?)', (body['ticket_id'], app, _now()))
            runtime_actor = self.customer_typed.access.from_scope(self._customer(db, actor, release['workspace_id']))
        result = self.customer_typed.execute(release['workspace_id'], release['draft_id'], {**body, 'notice': NOTICE}, runtime_actor)['run']
        with self.execution._internal() as db:
            self._customer(db, actor, release['workspace_id'], 'read')
            capability = self._issue_token(db, app, value, 'run-status', result['id'])
        return {'profile': SDK_PROFILE, 'run': result, 'status_capability': capability}

    def _owned_run(self, db, app, actor, release, run_id):
        run, _, _ = self.customer_typed._run(db, release['workspace_id'], release['draft_id'], run_id)
        links = _rows(db, 'SELECT * FROM workspace_app_run_links WHERE ticket_id=? AND app_id=?', (run['ticket_id'], app))
        if len(links) != 1:
            raise WorkspaceDenied()
        link = self._link(links[0])
        if link['customer_id'] != actor.customer_id or link['session_ref'] != actor.session_ref or link['release_id'] != release['id']:
            raise WorkspaceDenied()
        return run

    def history(self, app, raw, request_origin):
        with self.execution._internal() as db:
            _, actor, release = self._token(db, app, raw, 'app-run', request_origin, current=False)
            rows = _rows(db, '''SELECT r.id FROM workspace_typed_flow_runs r JOIN workspace_app_run_links l ON l.ticket_id=r.ticket_id
                WHERE l.app_id=? ORDER BY r.created DESC LIMIT 30''', (app,))
            return [{**self.customer_typed._dto(db, self._owned_run(db, app, actor, release, row['id']), output=False), 'steps': []}
                    for row in rows if self._same_actor(db, row['id'], actor, release)]

    def _same_actor(self, db, rid, actor, release):
        _, _, claims = self.customer_typed._run(db, release['workspace_id'], release['draft_id'], rid)
        return claims['actor_user_id'] == actor.customer_id and claims['session_ref'] == actor.session_ref

    def status_capability(self, app, raw, run_id, request_origin):
        with self.execution._internal() as db:
            value, actor, release = self._token(db, app, raw, 'app-run', request_origin, current=False)
            self._owned_run(db, app, actor, release, run_id)
            return self._issue_token(db, app, value, 'run-status', run_id)

    def status(self, app, raw, run_id, request_origin):
        with self.execution._internal() as db:
            value, actor, release = self._token(db, app, raw, 'run-status', request_origin, current=False)
            if value['run_id'] != run_id:
                raise WorkspaceDenied()
            run = self._owned_run(db, app, actor, release, run_id)
            return self.customer_typed._dto(db, run)
