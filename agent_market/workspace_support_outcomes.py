"""Purpose-authorized support history from retained private runs, not customer analytics."""
import math

from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows

PROFILE = 'workspace-support-outcomes-v1'
NOTICE = 'workspace-support-outcome-record-v1'
WITHDRAW_NOTICE = 'workspace-support-outcome-withdraw-v1'
CATEGORIES = ('setup', 'contract', 'execution', 'recovery')
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_support_cases(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_support_withdrawals(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS workspace_support_restore_blocks(authority_id TEXT PRIMARY KEY)',
)


class SupportOutcomes(SignedWorkspaceModule):
    def __init__(self, access, execution, typed_flows):
        if execution.access is not access or typed_flows.access is not access: raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.execution, self.typed = execution, typed_flows

    def _source(self, db, ws, body):
        if body['source_kind'] == 'typed':
            value, _, claims = self.typed._run(db, ws, body['subject_id'], body['run_id'])
            if body['version_id'] != claims['version_id']: raise WorkspaceDenied()
            status, created, finished, signature = value['status'], value['created'], value.get('finished'), _hash(value)
        elif body['source_kind'] == 'single':
            row, _, _, value = self.execution._load_run(db, body['run_id'], ws, body['subject_id'], body['version_id'], decrypt_output=False)
            status, created, finished, signature = value['status'], value['created'], value.get('finished'), row['signature']
        else: raise WorkspaceInvalid()
        if status not in ('succeeded', 'failed', 'unknown', 'denied'): raise WorkspaceConflict()
        if any(type(number) not in (int, float) or not math.isfinite(number) for number in (created, finished)):
            raise WorkspaceConflict()
        if not 0 < created <= finished <= clock() + 5: raise WorkspaceConflict()
        return {'run_id': body['run_id'], 'source_kind': body['source_kind'], 'subject_id': body['subject_id'],
                'version_id': body['version_id'], 'execution_status': status, 'created': created, 'finished': finished,
                'source_hash': _hash(signature)}

    def _case(self, db, ws, identity):
        rows = _rows(db, 'SELECT * FROM workspace_support_cases WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        value = self.opened(rows[0])
        if (value.get('profile') != PROFILE or value.get('id') != identity or value.get('workspace_id') != ws
                or value.get('revision') != rows[0]['revision']): raise WorkspaceConflict()
        return value

    def record(self, ws, body, actor):
        exact(body, ('source_kind', 'subject_id', 'version_id', 'run_id', 'category', 'resolution',
                     'iterations', 'revision', 'authorized', 'notice'))
        if (body['category'] not in CATEGORIES or body['resolution'] not in ('open', 'resolved', 'unresolved', 'unknown')
                or type(body['iterations']) is not int or not 0 <= body['iterations'] <= 100
                or type(body['revision']) is not int or not 0 <= body['revision'] < 100
                or body['authorized'] is not True or body['notice'] != NOTICE): raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True)
            source = self._source(db, ws, body)
            identity = 'wso_' + _hash([ws, source['source_kind'], source['run_id'], body['category']])[:32]
            if (db.execute('SELECT 1 FROM workspace_support_withdrawals WHERE id=? AND workspace_id=?', (identity, ws)).fetchone()
                    or db.execute('SELECT 1 FROM workspace_support_restore_blocks WHERE authority_id=?', (identity,)).fetchone()):
                raise WorkspaceDenied()
            previous = _rows(db, 'SELECT * FROM workspace_support_cases WHERE id=? AND workspace_id=?', (identity, ws))
            command = {'source': source, 'category': body['category'], 'resolution': body['resolution'], 'iterations': body['iterations']}
            if previous:
                old = self._case(db, ws, identity)
                if old['command'] == command and old['revision'] == body['revision'] + 1:
                    return {'case_id': identity, 'revision': old['revision'], 'replayed': True, 'business_outcome': 'unassessed'}
                if old['revision'] != body['revision']: raise WorkspaceConflict()
            elif body['revision'] != 0: raise WorkspaceConflict()
            if not previous and db.execute('SELECT COUNT(*) FROM workspace_support_cases WHERE workspace_id=?', (ws,)).fetchone()[0] >= 200:
                raise WorkspaceConflict()
            value = {'profile': PROFILE, 'id': identity, 'workspace_id': ws, 'revision': body['revision'] + 1,
                     'command': command, 'created': old['created'] if previous else clock(), 'updated': clock(),
                     'recorded_by': actor.user_id, 'purpose': 'support_evaluation', 'provenance': 'staff_reported_support_resolution'}
            if not previous:
                db.execute('INSERT INTO workspace_support_cases VALUES(?,?,?,?,?)', (identity, ws, value['revision'], _canonical(value), self.sign(value)))
            elif db.execute('UPDATE workspace_support_cases SET revision=?,payload=?,signature=? WHERE id=? AND workspace_id=? AND revision=?',
                    (value['revision'], _canonical(value), self.sign(value), identity, ws, body['revision'])).rowcount != 1:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'support_outcome.record', identity, value['revision'])
            return {'case_id': identity, 'revision': value['revision'], 'replayed': False, 'business_outcome': 'unassessed'}

    def withdraw(self, ws, body, actor):
        exact(body, ('case_id', 'revision', 'authorized', 'notice'))
        if (type(body['revision']) is not int or body['authorized'] is not True or body['notice'] != WITHDRAW_NOTICE):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._case(db, ws, body['case_id'])
            if value['revision'] != body['revision']: raise WorkspaceConflict()
            previous = _rows(db, 'SELECT * FROM workspace_support_withdrawals WHERE id=? AND workspace_id=?', (value['id'], ws))
            if previous:
                tombstone = self.opened(previous[0])
                if tombstone.get('case_hash') != _hash(value): raise WorkspaceConflict()
                return {'case_id': value['id'], 'withdrawn': True, 'replayed': True}
            tombstone = {'id': value['id'], 'workspace_id': ws, 'case_hash': _hash(value), 'created': clock()}
            db.execute('INSERT INTO workspace_support_withdrawals VALUES(?,?,?,?)', (value['id'], ws, _canonical(tombstone), self.sign(tombstone)))
            self.access._audit(db, actor, ws, 'support_outcome.withdraw', value['id'], value['revision'])
            return {'case_id': value['id'], 'withdrawn': True, 'replayed': False}

    def report(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            member, user = self.scope(ws, actor)
            found = _rows(db, 'SELECT * FROM workspace_support_cases WHERE workspace_id=? ORDER BY id LIMIT 201', (ws,))
            if len(found) > 200: raise WorkspaceConflict()
            cases, logical, subjects = [], {}, {}
            states = {key: 0 for key in ('open', 'resolved', 'unresolved', 'unknown')}
            excluded = {'withdrawn': 0, 'restored': 0, 'source_unavailable': 0, 'source_changed': 0}
            for row in found:
                value = self._case(db, ws, row['id']); source = value['command']['source']; reason = None
                tombstones = _rows(db, 'SELECT * FROM workspace_support_withdrawals WHERE id=? AND workspace_id=?', (row['id'], ws))
                if tombstones:
                    tombstone = self.opened(tombstones[0])
                    if tombstone.get('case_hash') != _hash(value): raise WorkspaceConflict()
                    reason = 'withdrawn'
                elif db.execute('SELECT 1 FROM workspace_support_restore_blocks WHERE authority_id=?', (row['id'],)).fetchone(): reason = 'restored'
                else:
                    try: current = self._source(db, ws, source)
                    except (WorkspaceDenied, WorkspaceConflict): reason = 'source_unavailable'
                    else:
                        if current != source: reason = 'source_changed'
                if reason: excluded[reason] += 1
                else:
                    states[value['command']['resolution']] += 1
                    logical[source['run_id']] = source
                    subjects.setdefault((source['source_kind'], source['subject_id']), {})[source['run_id']] = source['created']
                cases.append({'case_id': value['id'], 'revision': value['revision'], 'category': value['command']['category'],
                    'resolution': value['command']['resolution'], 'state': reason or 'retained', 'source_kind': source['source_kind'],
                    'run_id': source['run_id'], 'subject_id': source['subject_id'], 'version_id': source['version_id'],
                    'execution_status': source['execution_status'], 'iterations': value['command']['iterations'],
                    'iterations_provenance': 'staff_reported', 'business_outcome': 'unassessed'})
            repeated = sum(len(times) >= 2 and max(times.values()) - min(times.values()) >= 28 * 86400 for times in subjects.values())
            return {'profile': PROFILE, 'scope': 'private_workspace_support_history', 'cases': cases, 'resolution_counts': states,
                    'excluded': excluded, 'logical_run_samples': len(logical), 'sample_threshold_met': len(logical) >= 20,
                    'observed_subject_repeat_after_28_days': repeated, 'customer_reuse_qualified': False,
                    'business_outcome': 'unassessed', 'provider_quality_qualified': False, 'provider_calls': 0,
                    'marketing_permission': False, 'model_training_permission': False, 'public_activation': False,
                    'can_edit': member['member_role'] in ('owner', 'editor') and user['role'] != 'operator',
                    'can_withdraw': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'notice': NOTICE, 'withdrawal_notice': WITHDRAW_NOTICE, 'categories': list(CATEGORIES)}
