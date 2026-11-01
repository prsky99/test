"""Purpose-authorized, transactional private-runtime simulation accounting.

This records logical runs separately from actual dispatch attempts. It never
charges an account, moves money, or grants authority to execute a provider.
"""
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import (SessionActor, WorkspaceConflict, WorkspaceDenied,
    WorkspaceInvalid, _canonical, _hash, _revision, _rows)

PROFILE = 'workspace-runtime-meter-v1'
NOTICE = 'workspace-runtime-meter-authorize-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_meter_policies (
       workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,enabled INTEGER NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_meter_operations (
       run_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,policy_revision INTEGER NOT NULL,
       status TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_meter_attempts (
       run_id TEXT NOT NULL,ordinal INTEGER NOT NULL,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(run_id,ordinal))''',
    '''CREATE TABLE IF NOT EXISTS workspace_meter_entries (
       run_id TEXT NOT NULL,ordinal INTEGER NOT NULL,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(run_id,ordinal))''',
)


class WorkspaceMetering(SignedWorkspaceModule):
    def __init__(self, access, execution=None):
        super().__init__(access, PROFILE, SCHEMA)
        self.execution = execution

    def _policy(self, db, ws):
        rows = _rows(db, 'SELECT * FROM workspace_meter_policies WHERE workspace_id=?', (ws,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if (value.get('profile') != PROFILE or value.get('workspace_id') != ws
                or value.get('revision') != rows[0]['revision']
                or int(value.get('enabled', False)) != rows[0]['enabled']):
            raise WorkspaceConflict()
        return value

    def configure(self, ws, body, actor):
        exact(body, ('revision', 'enabled', 'units_per_success', 'max_runs', 'ttl_seconds', 'authorized', 'notice'))
        if (not _revision(body['revision'], zero=True) or type(body['enabled']) is not bool
                or type(body['units_per_success']) is not int or not 1 <= body['units_per_success'] <= 1000
                or type(body['max_runs']) is not int or not 1 <= body['max_runs'] <= 10000
                or type(body['ttl_seconds']) is not int or not 60 <= body['ttl_seconds'] <= 86400
                or body['authorized'] is not True or body['notice'] != NOTICE):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = self._policy(db, ws)
            revision = old['revision'] if old else 0
            if revision != body['revision']:
                raise WorkspaceConflict()
            historical = db.execute('SELECT COALESCE(MAX(policy_revision),0) FROM workspace_meter_operations WHERE workspace_id=?', (ws,)).fetchone()[0]
            value = {'profile': PROFILE, 'workspace_id': ws, 'revision': max(revision, historical)+1,
                'enabled': body['enabled'], 'units_per_success': body['units_per_success'],
                'max_runs': body['max_runs'], 'created': clock(), 'expires': clock()+body['ttl_seconds'],
                'owner_id': actor.user_id, 'owner_session': actor.session_ref,
                'owner_kind': getattr(actor, 'principal_kind', 'admin'),
                'owner_token_ref': getattr(actor, 'token_ref', None),
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'owner_role': user['role'], 'asset': 'TEST_UNIT'}
            db.execute('''INSERT INTO workspace_meter_policies VALUES(?,?,?,?,?)
                ON CONFLICT(workspace_id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,
                payload=excluded.payload,signature=excluded.signature''',
                (ws, value['revision'], int(value['enabled']), _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'meter.configure', None, value['revision'])
            return self._policy_dto(value)

    @staticmethod
    def _policy_dto(value):
        keys = ('revision', 'enabled', 'units_per_success', 'max_runs', 'expires')
        return {key: value[key] for key in keys} | {'simulation': True, 'actual_money': False}

    def _owner(self, value):
        access = self.access
        if value.get('owner_kind', 'admin') == 'customer':
            from .customer_workspace_runtime import CustomerWorkspaceAccess
            access = getattr(self, 'customer_access', self.access)
            if not isinstance(access, CustomerWorkspaceAccess) or access.store is not self.store:
                raise WorkspaceDenied()
            factory = getattr(access, 'actor_from_claims', None)
            if factory is None:
                raise WorkspaceDenied()
            owner = factory({'actor_kind': 'customer', 'actor_user_id': value['owner_id'],
                'session_ref': value['owner_session'], 'workspace_id': value['workspace_id'],
                'token_ref': value.get('owner_token_ref')})
        else:
            owner = SessionActor(value['owner_id'], value['owner_session'])
        member, user = access._access(value['workspace_id'], owner, write=True, owner=True)
        if (member['revision'] != value['workspace_revision']
                or member['member_revision'] != value['member_revision'] or user['role'] != value['owner_role']):
            raise WorkspaceDenied()

    def _operation(self, db, run_id):
        rows = _rows(db, 'SELECT * FROM workspace_meter_operations WHERE run_id=?', (run_id,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if (value.get('run_id') != run_id or value.get('workspace_id') != rows[0]['workspace_id']
                or value.get('policy_revision') != rows[0]['policy_revision']
                or value.get('status') != rows[0]['status']):
            raise WorkspaceConflict()
        return value

    def _save(self, db, value):
        db.execute('''INSERT INTO workspace_meter_operations VALUES(?,?,?,?,?,?) ON CONFLICT(run_id)
            DO UPDATE SET status=excluded.status,payload=excluded.payload,signature=excluded.signature''',
            (value['run_id'], value['workspace_id'], value['policy_revision'], value['status'], _canonical(value), self.sign(value)))

    def admit(self, db, claims, run):
        """Called in the same writer transaction as the private run admission."""
        ws = run['workspace_id']
        policy = self._policy(db, ws)
        if not policy or not policy['enabled']:
            return
        self._owner(policy)
        if policy['expires'] <= clock():
            raise WorkspaceDenied()
        if self._operation(db, run['id']) is not None:
            raise WorkspaceConflict()
        count = db.execute('''SELECT COUNT(*) FROM workspace_meter_operations
            WHERE workspace_id=? AND policy_revision=?''', (ws, policy['revision'])).fetchone()[0]
        if count >= policy['max_runs']:
            raise WorkspaceConflict()
        if db.execute('SELECT COUNT(*) FROM workspace_meter_operations WHERE workspace_id=?', (ws,)).fetchone()[0] >= 10000:
            raise WorkspaceConflict()
        self._save(db, {'profile': PROFILE, 'run_id': run['id'], 'workspace_id': ws,
            'policy_revision': policy['revision'], 'policy_hash': _hash(policy),
            'units_per_success': policy['units_per_success'], 'asset': 'TEST_UNIT',
            'ticket_hash': _hash(claims), 'status': 'admitted', 'dispatched': False,
            'attempt_count': 0,
            'created': run['created'], 'finished': None, 'settled_units': 0,
            'actor_kind': claims.get('actor_kind', 'admin'), 'revision': 1})

    def dispatch(self, db, claims, run, ordinal=1):
        value = self._operation(db, run['id'])
        if value is None:
            return
        policy = self._policy(db, run['workspace_id'])
        if (not policy or not policy['enabled'] or policy['expires'] <= clock()
                or _hash(policy) != value['policy_hash'] or _hash(claims) != value['ticket_hash']
                or value['status'] != 'admitted' or type(ordinal) is not int
                or not 1 <= ordinal <= 6 or ordinal != value.get('attempt_count', 0)+1):
            raise WorkspaceDenied()
        self._owner(policy)
        attempt = {'run_id': run['id'], 'workspace_id': run['workspace_id'], 'ordinal': ordinal,
                   'created': clock(), 'status': 'dispatched', 'operation_hash': _hash(value)}
        db.execute('INSERT INTO workspace_meter_attempts VALUES(?,?,?,?,?)',
            (run['id'], ordinal, run['workspace_id'], _canonical(attempt), self.sign(attempt)))
        value.update(dispatched=True, attempt_count=ordinal, revision=value['revision']+1)
        self._save(db, value)

    def finish(self, db, run):
        value = self._operation(db, run['id'])
        if value is None:
            return
        if value['status'] != 'admitted':
            if value['status'] != run['status']:
                raise WorkspaceConflict()
            return
        amount = value['units_per_success'] if run['status'] == 'succeeded' and value['dispatched'] else 0
        for ordinal, (account, units) in enumerate((('simulation_usage', amount), ('simulation_clearing', -amount))):
            if amount:
                entry = {'run_id': run['id'], 'workspace_id': value['workspace_id'],
                         'account': account, 'asset': 'TEST_UNIT', 'units': units}
                db.execute('INSERT INTO workspace_meter_entries VALUES(?,?,?,?,?)',
                    (run['id'], ordinal, value['workspace_id'], _canonical(entry), self.sign(entry)))
        value.update(status=run['status'], finished=run['finished'], settled_units=amount,
                     revision=value['revision']+1)
        self._save(db, value)

    def summary(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            policy = self._policy(db, ws)
            rows = _rows(db, 'SELECT run_id FROM workspace_meter_operations WHERE workspace_id=? ORDER BY run_id LIMIT 10001', (ws,))
            if len(rows) > 10000:
                raise WorkspaceConflict()
            counts, total, attempts, entry_count = {}, 0, 0, 0
            for row in rows:
                value = self._operation(db, row['run_id'])
                counts[value['status']] = counts.get(value['status'], 0)+1
                entries = _rows(db, 'SELECT * FROM workspace_meter_entries WHERE run_id=? ORDER BY ordinal', (row['run_id'],))
                opened = [self.opened(entry) for entry in entries]
                if any(entry['run_id'] != row['run_id'] or entry['workspace_id'] != ws
                       or entry['ordinal'] != ordinal for ordinal, entry in enumerate(entries)):
                    raise WorkspaceConflict()
                entry_count += len(entries)
                expected = value['settled_units']
                if (len(opened) != (2 if expected else 0) or sum(item['units'] for item in opened) != 0
                        or opened and (opened[0] != {'run_id': row['run_id'], 'workspace_id': ws,
                            'account': 'simulation_usage', 'asset': 'TEST_UNIT', 'units': expected}
                        or opened[1] != {'run_id': row['run_id'], 'workspace_id': ws,
                            'account': 'simulation_clearing', 'asset': 'TEST_UNIT', 'units': -expected})):
                    raise WorkspaceConflict()
                records = _rows(db, 'SELECT * FROM workspace_meter_attempts WHERE run_id=? ORDER BY ordinal', (row['run_id'],))
                if len(records) != value.get('attempt_count', int(value['dispatched'])):
                    raise WorkspaceConflict()
                for ordinal, record in enumerate(records, 1):
                    attempt = self.opened(record)
                    if (record['ordinal'] != ordinal or record['workspace_id'] != ws
                            or attempt['run_id'] != row['run_id'] or attempt['workspace_id'] != ws
                            or attempt['ordinal'] != ordinal or attempt['status'] != 'dispatched'):
                        raise WorkspaceConflict()
                attempts += len(records)
                total += expected
            if (db.execute('SELECT COUNT(*) FROM workspace_meter_entries WHERE workspace_id=?', (ws,)).fetchone()[0] != entry_count
                    or db.execute('SELECT COUNT(*) FROM workspace_meter_attempts WHERE workspace_id=?', (ws,)).fetchone()[0] != attempts):
                raise WorkspaceConflict()
            return {'profile': PROFILE, 'notice': NOTICE, 'policy': self._policy_dto(policy) if policy else None,
                'operations': len(rows), 'attempts': attempts, 'outcomes': counts,
                'simulated_units': total, 'asset': 'TEST_UNIT', 'balanced': True,
                'simulation': True, 'actual_money': False, 'automatic_payment': False,
                'max_retained_operations': 10000}

    def recover(self, ws, actor):
        """An expired unfinished run remains unknown; never resend or charge it."""
        if self.execution is None:
            raise WorkspaceDenied()
        recovered = 0
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            rows = _rows(db, '''SELECT m.run_id,r.draft_id,r.snapshot_id FROM workspace_meter_operations m
                JOIN workspace_private_runs r ON r.id=m.run_id WHERE m.workspace_id=?
                AND m.status='admitted' AND r.deadline<=? ORDER BY r.created LIMIT 100''', (ws, clock()))
            for row in rows:
                value = self._operation(db, row['run_id'])
                if value['status'] != 'admitted':
                    continue
                _, _, _, run = self.execution._load_run(db, row['run_id'], ws, row['draft_id'], row['snapshot_id'])
                if run['status'] in ('prepared', 'dispatched'):
                    run = {**run, 'status': 'unknown', 'finished': clock()}
                self.finish(db, run)
                recovered += 1
            typed = getattr(self, 'typed_flows', None)
            if typed is not None:
                rows = _rows(db, '''SELECT m.run_id,r.flow_id FROM workspace_meter_operations m
                    JOIN workspace_typed_flow_runs r ON r.id=m.run_id WHERE m.workspace_id=?
                    AND m.status='admitted' AND r.deadline<=? ORDER BY r.created LIMIT 100''', (ws, clock()))
                for row in rows:
                    run, _, _ = typed._run(db, ws, row['flow_id'], row['run_id'])
                    if run['status'] == 'running':
                        run = {**run, 'status': 'unknown', 'finished': clock()}
                    self.finish(db, run)
                    recovered += 1
            self.access._audit(db, actor, ws, 'meter.recover', None, recovered)
        return {'recovered': recovered, 'provider_calls': 0, 'simulation': True, 'actual_money': False}
