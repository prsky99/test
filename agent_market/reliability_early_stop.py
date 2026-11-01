"""Explicit private A2A intervention with durable, non-replayed cancellation.

This finite controller enforces approved elapsed/poll limits. It does not infer
task quality, successful work saved or false-stop rates from a cancellation.
"""
import secrets
import threading
import time

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .reliability_evaluation import bounded_int, finite, revision_authority
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _identity, _rows, _hash
from .workspace_remote_a2a import NOTICE as TASK_NOTICE, PROFILE as TASK_PROFILE, RemoteTasks
from .workspace_reliability import ReliabilityEvidence

PROFILE = 'private-a2a-early-stop-v1'
NOTICE = 'one-task-threshold-cancellation-v1'
PAIR_NOTICE = 'precommitted-independent-task-comparison-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_stop_policies (
       workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_stop_runs (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,task_id TEXT NOT NULL UNIQUE,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)


class ReliabilityEarlyStop(SignedWorkspaceModule):
    def __init__(self, access, remote, *, enabled=False, comparator=None,
                 environment='isolated', minimum_pairs=10, max_false_stop_rate=0,
                 max_success_loss=0, max_overhead_ms=50):
        if (type(remote) is not RemoteTasks or remote.access is not access
                or type(enabled) is not bool or comparator is not None and not callable(comparator)
                or environment not in ('isolated', 'approved_external')
                or type(minimum_pairs) is not int or not 1 <= minimum_pairs <= 100
                or any(not finite(v) or not 0 <= v <= 1 for v in (max_false_stop_rate, max_success_loss))
                or not finite(max_overhead_ms) or not 0 < max_overhead_ms <= 1000):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.remote, self.enabled = remote, enabled
        self._lock, self._tick_lock = threading.RLock(), threading.Lock()
        self._stop, self._thread, self._watches = threading.Event(), None, {}
        self.comparator, self.environment = comparator, environment
        self.minimum_pairs, self.max_false_stop_rate = minimum_pairs, max_false_stop_rate
        self.max_success_loss, self.max_overhead_ms = max_success_loss, max_overhead_ms

    @staticmethod
    def _authorize(body, fields):
        exact(body, (*fields, 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        if 'revision' in fields:
            bounded_int(body['revision'], 0, 2**31-1)
        if 'policy_revision' in fields:
            bounded_int(body['policy_revision'], 1, 2**31-1)

    def _policy(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_stop_policies WHERE workspace_id=?', (ws,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if value.get('workspace_id') != ws or value.get('revision') != rows[0]['revision']:
            raise WorkspaceConflict()
        return value

    def _current(self, db, ws, actor, revision=None):
        member, user = self.scope(ws, actor, write=True, owner=True)
        value = self._policy(db, ws)
        if (not self.enabled or not value or not value['enabled'] or value['expires'] <= clock()
                or revision is not None and value['revision'] != revision
                or any(value.get(k) != v for k, v in revision_authority(member, user, actor).items())):
            raise WorkspaceConflict()
        # This also checks current version, configured binding and invoke switch.
        self.remote._pin(value['resource_id'], value['version_id'])
        return value

    def configure(self, ws, body, actor):
        self._authorize(body, ('revision', 'resource_id', 'version_id', 'enabled',
                              'max_elapsed_seconds', 'max_polls', 'expires'))
        bounded_int(body['revision'], 0, 2**31-1)
        bounded_int(body['resource_id'], 1, 2**31-1)
        bounded_int(body['max_elapsed_seconds'], 1, 3600)
        bounded_int(body['max_polls'], 1, 100)
        _identity(body['version_id'], 'cv')
        if (type(body['enabled']) is not bool or not finite(body['expires'])
                or not clock() < body['expires'] <= clock()+3600):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            if not self.enabled:
                raise WorkspaceConflict()
            previous = self._policy(db, ws)
            if body['revision'] != (previous['revision'] if previous else 0):
                raise WorkspaceConflict()
            self.remote._pin(body['resource_id'], body['version_id'])
            value = {k: body[k] for k in ('resource_id', 'version_id', 'enabled',
                'max_elapsed_seconds', 'max_polls', 'expires')} | {
                'workspace_id': ws, 'revision': body['revision']+1, 'created': clock(),
                **revision_authority(member, user, actor)}
            db.execute('''INSERT INTO reliability_stop_policies VALUES(?,?,?,?) ON CONFLICT(workspace_id)
                DO UPDATE SET revision=excluded.revision,payload=excluded.payload,signature=excluded.signature''',
                (ws, value['revision'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.stop.configure', ws, value['revision'])
            return {k: value[k] for k in ('revision', 'enabled', 'max_elapsed_seconds', 'max_polls', 'expires')}

    def _load(self, db, ws, identity):
        _identity(identity, 'rst')
        rows = _rows(db, 'SELECT * FROM reliability_stop_runs WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value.get(k) != rows[0][k] for k in ('id', 'workspace_id', 'task_id')):
            raise WorkspaceConflict()
        return value

    def _save(self, db, value):
        db.execute('''INSERT INTO reliability_stop_runs VALUES(?,?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
            (value['id'], value['workspace_id'], value['task_id'], _canonical(value), self.sign(value)))

    @staticmethod
    def dto(value):
        return {k: value[k] for k in ('id', 'task_id', 'revision', 'policy_revision', 'state', 'polls',
            'reason', 'cancel_attempted', 'remote_cancel_confirmed', 'late_result', 'observed_at', 'overhead_ms')} | {
            'actual_interventions': int(value.get('cancel_dispatched', False)), 'public_activation': False,
            'false_stop_rate': None, 'successful_outcome_loss': None, 'quality_promotion_eligible': False,
            'paired_before_intervention': value.get('pair') is not None,
            'detection_delay_ms': value.get('detection_delay_ms')}

    def watch(self, ws, body, actor):
        if self._stop.is_set():
            raise WorkspaceConflict()
        with self._lock:
            if len(self._watches) >= 16 and (ws, body.get('task_id') if type(body) is dict else None) not in self._watches:
                raise WorkspaceConflict()
            value = self._watch(ws, body, actor)
            if value['state'] == 'watching':
                self._watches[(ws, value['task_id'])] = (actor, value['id'])
        return value

    def _watch(self, ws, body, actor):
        self._authorize(body, ('task_id', 'policy_revision', 'opt_in'))
        _identity(body['task_id'], 'rtk')
        if body['opt_in'] is not True:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            policy = self._current(db, ws, actor, body['policy_revision'])
            task = self.remote._load(db, ws, body['task_id'])
            if (task['owner'] != self.remote._owner(ws, actor) or task['resource_id'] != policy['resource_id']
                    or task['version_id'] != policy['version_id'] or task['state'] not in ('submitted', 'working', 'input-required')
                    or task['created'] < policy['created'] or task['expires'] <= clock()):
                raise WorkspaceConflict()
            previous = _rows(db, 'SELECT id FROM reliability_stop_runs WHERE task_id=?', (task['id'],))
            if previous:
                old = self._load(db, ws, previous[0]['id'])
                if old['policy_revision'] != policy['revision']:
                    raise WorkspaceConflict()
                return self.dto(old)
            if db.execute('SELECT COUNT(*) FROM reliability_stop_runs WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            value = {'id': 'rst_'+secrets.token_hex(16), 'workspace_id': ws, 'task_id': task['id'],
                'policy_revision': policy['revision'], 'revision': 1, 'state': 'watching', 'polls': 0,
                'reason': None, 'cancel_attempted': False, 'cancel_dispatched': False, 'remote_cancel_confirmed': False,
                'late_result': False, 'observed_at': None, 'overhead_ms': None,
                'task_revision': task['revision'], 'created': clock(), 'owner': task['owner'],
                'pair': None, 'assessment': None, 'assessment_count': 0, 'detection_delay_ms': None}
            self._save(db, value)
            self.access._audit(db, actor, ws, 'reliability.stop.watch', value['id'], 1)
            return self.dto(value)

    @staticmethod
    def _pair_authorize(body, fields):
        exact(body, (*fields, 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != PAIR_NOTICE:
            raise WorkspaceInvalid()

    def pair(self, ws, identity, body, actor):
        """Precommit an existing separately approved baseline, never create it."""
        self._pair_authorize(body, ('revision', 'baseline_task_id'))
        bounded_int(body['revision'], 1, 2**31-1); _identity(body['baseline_task_id'], 'rtk')
        with self.access._tx(actor, write=True) as (db, _):
            value = self._load(db, ws, identity); self._current(db, ws, actor, value['policy_revision'])
            intervention = self.remote._load(db, ws, value['task_id'])
            baseline = self.remote._load(db, ws, body['baseline_task_id'])
            if (value['revision'] != body['revision'] or value['pair'] is not None or value['state'] != 'watching'
                    or value['polls'] or value['cancel_attempted'] or baseline['id'] == intervention['id']
                    or intervention['revision'] != value['task_revision']
                    or any(t['state'] not in ('submitted', 'working', 'input-required') for t in (baseline, intervention))
                    or any(t['owner'] != value['owner'] for t in (baseline, intervention))
                    or any(baseline[k] != intervention[k] for k in ('resource_id', 'version_id'))
                    or baseline.get('task_profile', TASK_PROFILE) != intervention.get('task_profile', TASK_PROFILE)):
                raise WorkspaceConflict()
            first, second = self.remote._private(baseline), self.remote._private(intervention)
            if (first['text'] != second['text'] or not first.get('remote_id') or not second.get('remote_id')
                    or first['remote_id'] == second['remote_id']):
                raise WorkspaceConflict()
            others = _rows(db, 'SELECT id FROM reliability_stop_runs WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
            for row in others:
                other = self._load(db, ws, row['id'])
                if other.get('pair') and other['pair']['baseline_task_id'] == baseline['id']:
                    raise WorkspaceConflict()
            value['pair'] = {'baseline_task_id': baseline['id'], 'input_hash': _hash(first['text']),
                'resource_id': baseline['resource_id'], 'version_id': baseline['version_id'],
                'task_profile': baseline.get('task_profile', TASK_PROFILE),
                'baseline_created': baseline['created'], 'intervention_created': intervention['created'], 'created': clock()}
            value['revision'] += 1; self._save(db, value)
            self.access._audit(db, actor, ws, 'reliability.stop.pair', identity, value['revision'])
            return self.dto(value)

    def _comparison_snapshot(self, db, ws, identity, actor):
        value = self._load(db, ws, identity); self._current(db, ws, actor, value['policy_revision'])
        pair = value.get('pair')
        if pair is None or value['state'] not in ('completed', 'stopped', 'failed', 'rejected', 'unknown'):
            raise WorkspaceConflict()
        tasks = [self.remote._load(db, ws, ref) for ref in (pair['baseline_task_id'], value['task_id'])]
        bundles = []
        for task in tasks:
            if (task['owner'] != value['owner'] or task['resource_id'] != pair['resource_id']
                    or task['version_id'] != pair['version_id'] or task['expires'] <= clock()
                    or task.get('task_profile', TASK_PROFILE) != pair['task_profile']
                    or task['state'] not in ('completed', 'canceled', 'failed', 'rejected', 'unknown')):
                raise WorkspaceConflict()
            private = self.remote._private(task)
            if _hash(private['text']) != pair['input_hash']:
                raise WorkspaceConflict()
            bundles.append({'input': {'text': private['text']}, 'output': {'text': private.get('output')}})
        source = _hash([pair, tasks])
        return value, tasks, bundles, source

    def _assessor_binding(self):
        config = getattr(self.comparator, 'config', None)
        if config is None:
            raise WorkspaceDenied()
        return _hash([config.endpoint, config.key_id, config.evaluator_id, config.independence_hash,
            config.purpose, config.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()])

    def assess_pair(self, ws, identity, body, actor):
        self._pair_authorize(body, ('revision',))
        bounded_int(body['revision'], 1, 2**31-1)
        adapter = self.comparator
        evaluator_id = getattr(getattr(adapter, 'config', None), 'evaluator_id', None)
        if adapter is None or not evaluator_id or self.environment != 'approved_external':
            raise WorkspaceDenied()
        assessor = self._assessor_binding()
        with self.access._tx(actor) as (db, _):
            value, tasks, bundles, source = self._comparison_snapshot(db, ws, identity, actor)
            if value['revision'] != body['revision'] or value['assessment_count'] >= 3:
                raise WorkspaceConflict()
            if (value['assessment'] and value['assessment']['source'] == source
                    and value['assessment']['assessor'] == assessor and value['assessment']['expires'] > clock()):
                return self._assessment_dto(value['assessment'])
        outcomes, expiries, provenance = [], [], []
        for index, (task, bundle) in enumerate(zip(tasks, bundles)):
            if task['state'] == 'canceled' and not bundle['output']['text']:
                # Absence of work after cancellation is not an independent
                # failure label or proof of a counterfactual successful outcome.
                outcomes.append('canceled_unassessed'); continue
            if task['state'] == 'unknown' or task.get('output_truncated') or task['state'] == 'completed' and not bundle['output']['text']:
                outcomes.append('unassessed'); continue
            if task['state'] in ('failed', 'rejected'):
                outcomes.append('failed_unassessed'); continue
            binding = {'workspace_id': ws, 'resource_id': task['resource_id'], 'agent_version': task['version_id'],
                'task_hash': _hash(task), 'pairing_hash': _hash(value['pair']), 'arm': 'baseline' if index == 0 else 'intervention',
                'policy_revision': value['policy_revision'], 'purpose': 'early-stop-paired-comparison-v1',
                'environment': self.environment, 'evaluator_version': evaluator_id, 'bundle_hash': _hash(bundle).split(':')[-1]}
            # This is the only remote assessment boundary; both inputs were
            # explicitly approved and no caller-owned DB transaction is open.
            if self.store._db.in_transaction:
                raise WorkspaceConflict()
            verdict = ReliabilityEvidence._validated_verdict(binding, adapter(binding, bundle))
            if verdict is None or verdict.source_fidelity != 'verified':
                raise WorkspaceDenied()
            outcomes.append(verdict.quality); expiries.append(verdict.expires)
            provenance.append([verdict.binding_hash, verdict.qualification_hash, verdict.independence_hash])
        result = {'source': source, 'assessor': assessor, 'outcomes': outcomes, 'expires': min([t['expires'] for t in tasks]+expiries),
            'provenance': _hash(provenance), 'assessed': all(x in ('passed', 'failed') for x in outcomes),
            'confirmed_stop': value['remote_cancel_confirmed'], 'decision_overhead_ms': value['overhead_ms'],
            'detection_delay_ms': value.get('detection_delay_ms')}
        with self.access._tx(actor, write=True) as (db, _):
            current, _, _, fresh = self._comparison_snapshot(db, ws, identity, actor)
            if self.comparator is not adapter or self._assessor_binding() != assessor or fresh != source or current != value:
                raise WorkspaceConflict()
            current.update(assessment=result, assessment_count=current['assessment_count']+1, revision=current['revision']+1)
            self._save(db, current)
            self.access._audit(db, actor, ws, 'reliability.stop.assess', identity, current['revision'])
            return self._assessment_dto(result)

    @staticmethod
    def _assessment_dto(result):
        return {k: result[k] for k in ('outcomes', 'expires', 'assessed', 'confirmed_stop',
            'decision_overhead_ms', 'detection_delay_ms')}

    def comparison_report(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            rows = _rows(db, 'SELECT id FROM reliability_stop_runs WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
            admitted, assessed, valid, provisional = 0, [], [], []
            for row in rows:
                value = self._load(db, ws, row['id'])
                if value.get('pair') is None:
                    continue
                admitted += 1; result = value.get('assessment')
                if not result or result['expires'] <= clock():
                    continue
                try:
                    _, _, _, source = self._comparison_snapshot(db, ws, value['id'], actor)
                    if source != result['source'] or self._assessor_binding() != result['assessor']:
                        continue
                    if result['confirmed_stop'] and result['outcomes'][0] in ('passed', 'failed'):
                        provisional.append(result)
                    if not result['assessed']:
                        continue
                except (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid):
                    continue
                assessed.append(result)
                if result['confirmed_stop']:
                    valid.append(result)
            false_stop = sum(r['outcomes'][0] == 'passed' and r['outcomes'][1] != 'passed' for r in valid)/len(valid) if valid else None
            loss = max(0, sum((r['outcomes'][0] == 'passed')-(r['outcomes'][1] == 'passed') for r in assessed)/len(assessed)) if assessed else None
            overhead = max((r['decision_overhead_ms'] for r in assessed if finite(r['decision_overhead_ms'])), default=None)
            eligible = (self.comparator is not None and self.environment == 'approved_external'
                and admitted == len(assessed) and len(assessed) >= self.minimum_pairs and false_stop is not None
                and false_stop <= self.max_false_stop_rate and loss <= self.max_success_loss
                and overhead is not None and overhead <= self.max_overhead_ms)
            return {'admitted_pairs': admitted, 'assessed_pairs': len(assessed), 'unknown_or_unassessed_pairs': admitted-len(assessed),
                'confirmed_stops_with_baseline': len(valid), 'false_stop_rate': false_stop, 'successful_outcome_loss': loss,
                'maximum_decision_overhead_ms': overhead, 'quality_promotion_eligible': bool(eligible), 'public_activation': False,
                'confirmed_stop_baseline_pass_fraction': (sum(r['outcomes'][0] == 'passed' for r in provisional)/len(provisional) if provisional else None),
                'comparison_scope': 'precommitted_input_version_pair_not_same_task_counterfactual'}

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            policy = self._policy(db, ws)
            rows = _rows(db, 'SELECT id FROM reliability_stop_runs WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
            if len(rows) > 100:
                raise WorkspaceConflict()
            return {'profile': PROFILE, 'configured': self.enabled, 'policy_revision': policy['revision'] if policy else 0,
                    'runs': [self.dto(self._load(db, ws, row['id'])) for row in rows], 'public_activation': False,
                    'running': bool(self._thread and self._thread.is_alive()), 'restart_reactivation_required': True}

    def tick(self):
        if not self.enabled or self._stop.is_set():
            return {'advanced': 0}
        if not self._tick_lock.acquire(blocking=False):
            raise WorkspaceConflict()
        advanced = 0
        try:
            with self._lock:
                active = list(self._watches.items())[:16]
            for key, (actor, identity) in active:
                if self._stop.is_set():
                    break
                ws, _ = key
                try:
                    with self.access._tx(actor) as (db, _):
                        value = self._load(db, ws, identity)
                    result = self.advance(ws, identity, {'revision': value['revision'],
                        'authorized': True, 'notice': NOTICE}, actor)
                    advanced += 1
                    if result['state'] == 'watching':
                        continue
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                    pass
                with self._lock:
                    self._watches.pop(key, None)
            return {'advanced': advanced}
        finally:
            self._tick_lock.release()

    def start(self):
        if not self.enabled or self._stop.is_set():
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._thread = threading.Thread(target=self._run, name='approved-a2a-intervention', daemon=True)
            self._thread.start()
            return True

    def _run(self):
        while not self._stop.wait(5):
            try:
                self.tick()
            except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                self._stop.set()

    def close(self):
        self._stop.set()
        with self._lock:
            self._watches.clear(); thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1)
        return not bool(thread and thread.is_alive())

    def advance(self, ws, identity, body, actor):
        self._authorize(body, ('revision',))
        started = time.monotonic()
        with self.access._tx(actor, write=True) as (db, _):
            value = self._load(db, ws, identity)
            self._current(db, ws, actor, value['policy_revision'])
            if value['revision'] != body['revision']:
                raise WorkspaceConflict()
            # A process death after this durable boundary is never replayed.
            if value['state'] == 'dispatched':
                return self.dto(value) | {'reconciliation_required': True}
            if value['state'] != 'watching':
                return self.dto(value)
            policy = self._current(db, ws, actor, value['policy_revision'])
            task = self.remote._load(db, ws, value['task_id'])
            if task['owner'] != value['owner'] or task['revision'] != value['task_revision']:
                raise WorkspaceConflict()
            if task['state'] in ('completed', 'canceled', 'failed', 'rejected', 'unknown'):
                value.update(state=task['state'], revision=value['revision']+1, observed_at=clock())
                self._save(db, value)
                return self.dto(value)
            elapsed = clock()-task['created']
            reason = ('elapsed_limit' if elapsed >= policy['max_elapsed_seconds'] else
                      'poll_limit' if value['polls'] >= policy['max_polls'] else None)
            action = 'cancel' if reason else 'poll'
            value.update(state='dispatched', revision=value['revision']+1, reason=reason,
                         cancel_attempted=bool(reason), overhead_ms=(time.monotonic()-started)*1000)
            if reason:
                crossing = (task['created']+policy['max_elapsed_seconds'] if reason == 'elapsed_limit' else value['observed_at'])
                value['detection_delay_ms'] = max(0, (clock()-(crossing or clock()))*1000)
            self._save(db, value)
            self.access._audit(db, actor, ws, 'reliability.stop.'+action, identity, value['revision'])

        dispatch_guard_passed = False
        def guard():
            nonlocal dispatch_guard_passed
            with self.access._tx(actor) as (db, _):
                current = self._load(db, ws, identity)
                self._current(db, ws, actor, value['policy_revision'])
                if self._stop.is_set() or current != value or current['state'] != 'dispatched':
                    raise WorkspaceConflict()
                dispatch_guard_passed = True

        try:
            result = self.remote.command(ws, value['task_id'], {'revision': task['revision'], 'action': action,
                'authorized': True, 'notice': TASK_NOTICE}, actor, _guard=guard)
        except Exception:
            result = {'state': 'unknown', 'revision': task['revision']}
        with self.access._tx(actor, write=True) as (db, _):
            current = self._load(db, ws, identity)
            self.scope(ws, actor, write=True, owner=True)
            if current != value:
                raise WorkspaceConflict()
            try:
                self._current(db, ws, actor, value['policy_revision'])
            except (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid):
                # Preserve a no-replay outcome even if a late response arrives
                # after the threshold authority has been withdrawn.
                result = {'state': 'unknown', 'revision': result['revision']}
            state = result['state']
            current.update(revision=current['revision']+1, task_revision=result['revision'], observed_at=clock(),
                polls=current['polls']+int(action == 'poll'),
                cancel_dispatched=action == 'cancel' and dispatch_guard_passed,
                remote_cancel_confirmed=action == 'cancel' and state == 'canceled',
                late_result=action == 'cancel' and state == 'completed',
                state=('stopped' if state == 'canceled' else state if state in
                       ('completed', 'failed', 'rejected', 'unknown') else 'unknown' if action == 'cancel' else 'watching'))
            self._save(db, current)
            return self.dto(current)
