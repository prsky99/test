"""Bounded evaluation research over existing corpus/jobs and typed lineage.

This module adds no scheduler, provider transport or execution journal. Its goal
oracle is deterministic fixture/approved-corpus validation, not factual quality.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import math
import re

from .capability_contracts import validate
from .reliability_evaluation import NOTICE as EVALUATION_NOTICE, revision_authority
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
                               _canonical, _hash, _identity, _rows)

PROFILE = 'bounded-reliability-research-v1'
NOTICE = 'approved-research-corpus-and-shadow-v1'
MUTATORS = ('outer-whitespace-v1', 'token-spacing-v1')
OUTCOMES = ('goal_pass', 'agent_failure', 'unknown', 'unassessable', 'oracle_error', 'invalid_transform')
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_research_manifests (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,corpus_id TEXT NOT NULL,
       created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_research_restore_blocks (
       manifest_id TEXT PRIMARY KEY)''',
)


def _version(value):
    if type(value) is not str or not re.fullmatch(r'[a-z0-9.-]{1,60}', value):
        raise WorkspaceInvalid()
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorkspaceInvalid()
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise WorkspaceInvalid()
    return value


def _digest(value):
    if type(value) is not str or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise WorkspaceInvalid()
    return value


def _transform(inputs, mutator):
    """Only explicitly reviewed whitespace relations, never paraphrase guessing."""
    query = inputs['query']
    if (mutator not in MUTATORS or type(query) is not str
            or not re.fullmatch(r'[A-Za-z0-9]+(?: [A-Za-z0-9]+){1,15}', query)):
        raise WorkspaceInvalid()
    result = deepcopy(inputs)
    result['query'] = (' ' + query + ' ') if mutator == MUTATORS[0] else query.replace(' ', '  ')
    if ' '.join(result['query'].split()) != query:
        raise WorkspaceInvalid()
    return result


def _wilson(passed, admitted):
    # Missing/unknown observations remain in the conservative admission bound.
    if not admitted:
        return None
    z = 1.959963984540054
    p = passed / admitted
    denominator = 1 + z*z/admitted
    center = (p + z*z/(2*admitted)) / denominator
    radius = z * math.sqrt((p*(1-p)+z*z/(4*admitted))/admitted) / denominator
    return {'low': max(0, center-radius), 'high': min(1, center+radius),
            'method': 'wilson95_admission_bound_not_independent_cluster_inference'}


@dataclass(frozen=True, repr=False)
class ResearchObservation:
    owner: object = field(repr=False)
    value: dict = field(repr=False)
    signature: str = field(repr=False)


class ReliabilityResearch(SignedWorkspaceModule):
    def __init__(self, access, evaluation, *, lineage=None):
        if evaluation.access is not access:
            raise WorkspaceInvalid()
        if lineage is not None and getattr(lineage, 'access', None) is not access:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.evaluation, self.lineage = evaluation, lineage
        evaluation.research = self

    def _manifest(self, db, ws, identity, *, current=True):
        _identity(identity, 'rrm')
        rows = _rows(db, 'SELECT * FROM reliability_research_manifests WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value[k] != rows[0][k] for k in ('id', 'workspace_id', 'corpus_id', 'created')):
            raise WorkspaceConflict()
        restored = bool(db.execute('SELECT 1 FROM reliability_research_restore_blocks WHERE manifest_id=?', (identity,)).fetchone())
        if current and (restored or value['withdrawn'] or value['expires'] <= clock()):
            raise WorkspaceConflict()
        return value | {'restore_quarantined': restored}

    def _current(self, db, ws, identity, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        value = self._manifest(db, ws, identity)
        if value['authority'] != revision_authority(member, user, actor):
            raise WorkspaceConflict()
        corpus = self.evaluation._corpus(db, ws, value['corpus_id'])
        if corpus['corpus_hash'] != value['corpus_hash']:
            raise WorkspaceConflict()
        return value, corpus

    @staticmethod
    def _dto(value):
        return {k: value[k] for k in ('id', 'version', 'corpus_id', 'corpus_hash', 'contract_id',
                                     'created', 'expires', 'withdrawn', 'revision', 'k', 'adaptive_priority')} | {
            'planned_episodes': len(value['episodes']), 'mutators': value['mutators'],
            'restore_quarantined': bool(value.get('restore_quarantined')),
            'independent_quality': 'unassessed', 'public_activation': False}

    def options(self, ws, actor):
        with self.access._tx(actor) as (_, user):
            member, _ = self.scope(ws, actor)
            return {'profile': PROFILE, 'notice': NOTICE, 'mutators': list(MUTATORS),
                    'can_write': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'lineage_configured': callable(getattr(self.lineage, 'current_run', None)),
                    'business_calls': 0, 'independent_quality': 'unassessed', 'public_activation': False}

    def register_manifest(self, ws, body, actor):
        exact(body, ('manifest_id', 'version', 'contract_id', 'cases', 'k', 'mutators', 'seed',
                     'reference_time', 'timezone', 'locale', 'dataset_version', 'oracle_version',
                     'analysis', 'expires', 'adaptive_priority', 'authorized', 'notice', 'semantic_attestation', 'data_attestation'))
        _identity(body['manifest_id'], 'rrm')
        for key in ('version', 'dataset_version', 'oracle_version'):
            _version(body[key])
        _integer(body['k'], 1, 3); _integer(body['seed'], 0, 2**31-1)
        if (body['contract_id'] not in ('docs.search.v1', 'news.search.v1')
                or body['timezone'] != 'UTC' or body['locale'] != 'en-US'
                or body['oracle_version'] != 'exact-approved-item-goal-v1'
                or body['authorized'] is not True or body['notice'] != NOTICE
                or body['semantic_attestation'] != 'reviewed_search_whitespace_preserves_task'
                or body['data_attestation'] != 'synthetic_or_licensed_no_personal_data'
                or type(body['adaptive_priority']) is not bool
                or not clock()-86400 <= _number(body['reference_time']) <= clock()
                or not clock() < _number(body['expires']) <= clock()+86400
                or type(body['mutators']) is not list or not 1 <= len(body['mutators']) <= 2
                or len(set(body['mutators'])) != len(body['mutators'])
                or any(x not in MUTATORS for x in body['mutators'])
                or type(body['cases']) is not list or not 1 <= len(body['cases']) <= 2):
            raise WorkspaceInvalid()
        exact(body['analysis'], ('version', 'minimum_pairs', 'grouping', 'unknown_policy', 'confidence'))
        _version(body['analysis']['version']); _integer(body['analysis']['minimum_pairs'], 1, 20)
        if (body['analysis']['grouping'] != 'resource-version-host-window-case-trials'
                or body['analysis']['unknown_policy'] != 'retain_in_admitted_denominator'
                or body['analysis']['confidence'] != 'conservative-wilson95-and-cluster-count'):
            raise WorkspaceInvalid()
        cases, episodes, goals, names = [], {}, {}, set()
        for base in body['cases']:
            exact(base, ('case_id', 'input', 'expected_items'))
            name = base['case_id']; _version(name)
            if len(name) > 25 or name in names or type(base['expected_items']) is not list or not 1 <= len(base['expected_items']) <= 5:
                raise WorkspaceInvalid()
            names.add(name)
            validate(body['contract_id'], base['input'], now=body['reference_time'])
            # Expected normalized public item hashes come from the approved
            # corpus snapshot. No customer or provider output is copied here.
            expected = sorted({_digest(x) for x in base['expected_items']})
            if len(expected) != len(base['expected_items']):
                raise WorkspaceInvalid()
            goals[name] = expected
            for trial in range(body['k']):
                for index, mutator in enumerate(('original', *body['mutators'])):
                    identity = name+'-'+str(trial)+'-'+str(index)
                    inputs = deepcopy(base['input']) if mutator == 'original' else _transform(base['input'], mutator)
                    validate(body['contract_id'], inputs, now=body['reference_time'])
                    cases.append({'case_id': identity, 'kind': 'repeatability' if not index else 'semantic_variant',
                                  'split': 'evaluation', 'input': inputs})
                    episodes[identity] = {'base_case': name, 'trial': trial, 'mutator': mutator,
                                          'epsilon': 0 if not index else 1, 'lambda': 0,
                                          'input_hash': _hash(inputs)}
        if len(cases) > 10:
            raise WorkspaceInvalid()
        corpus_id = 'rcp_'+body['manifest_id'][4:]
        corpus_body = {'corpus_id': corpus_id, 'version': body['version'], 'contract_id': body['contract_id'],
                       'cases': cases, 'training_hashes': [], 'authorized': True, 'notice': EVALUATION_NOTICE,
                       'data_attestation': 'synthetic_or_licensed_no_personal_data'}
        corpus_result = self.evaluation.register_corpus(ws, corpus_body, actor)
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = _rows(db, 'SELECT id FROM reliability_research_manifests WHERE id=?', (body['manifest_id'],))
            value = {k: deepcopy(body[k]) for k in ('version', 'contract_id', 'k', 'mutators', 'seed',
                'reference_time', 'timezone', 'locale', 'dataset_version', 'oracle_version', 'analysis',
                'expires', 'adaptive_priority')}
            value.update(id=body['manifest_id'], workspace_id=ws, corpus_id=corpus_id,
                         corpus_hash=corpus_result['corpus_hash'], created=clock(), revision=1, withdrawn=False,
                         episodes=episodes, goals=goals, authority=revision_authority(member, user, actor))
            value['definition_hash'] = _hash(body)
            if old:
                existing = self._manifest(db, ws, body['manifest_id'])
                if existing['definition_hash'] != value['definition_hash']:
                    raise WorkspaceConflict()
                return self._dto(existing) | {'replayed': True}
            if db.execute('SELECT COUNT(*) FROM reliability_research_manifests WHERE workspace_id=?', (ws,)).fetchone()[0] >= 20:
                raise WorkspaceConflict()
            db.execute('INSERT INTO reliability_research_manifests VALUES(?,?,?,?,?,?)',
                       (value['id'], ws, corpus_id, value['created'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.research.manifest', value['id'], 1)
            return self._dto(value) | {'provider_calls': 0}

    def withdraw(self, ws, identity, body, actor):
        exact(body, ('revision', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._manifest(db, ws, identity, current=False)
            if type(body['revision']) is not int or body['revision'] != value['revision']:
                raise WorkspaceConflict()
            if not value['withdrawn']:
                value.update(withdrawn=True, revision=value['revision']+1)
                db.execute('UPDATE reliability_research_manifests SET payload=?,signature=? WHERE id=? AND workspace_id=?',
                           (_canonical(value), self.sign(value), identity, ws))
                self.access._audit(db, actor, ws, 'reliability.research.withdraw', identity, value['revision'])
            return self._dto(value)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            rows = _rows(db, 'SELECT id FROM reliability_research_manifests WHERE workspace_id=? ORDER BY created DESC,id LIMIT 21', (ws,))
            if len(rows) > 20:
                raise WorkspaceConflict()
            return {'profile': PROFILE, 'manifests': [self._dto(self._manifest(db, ws, x['id'], current=False)) for x in rows],
                    'public_activation': False, 'business_calls': 0, 'independent_quality': 'unassessed'}

    def _for_corpus(self, db, ws, corpus_hash, corpus_id):
        rows = _rows(db, 'SELECT id FROM reliability_research_manifests WHERE workspace_id=? ORDER BY created DESC,id LIMIT 21', (ws,))
        if len(rows) > 20:
            raise WorkspaceConflict()
        for row in rows:
            value = self._manifest(db, ws, row['id'], current=False)
            if value['corpus_id'] == corpus_id and value['corpus_hash'] == corpus_hash:
                if value['withdrawn'] or value['restore_quarantined'] or value['expires'] <= clock():
                    raise WorkspaceConflict()
                return value
        return None

    def guard_job(self, db, ws, plan, job, actor):
        value = self._for_corpus(db, ws, plan['corpus_hash'], plan['corpus_id'])
        if value is None:
            return
        current, _ = self._current(db, ws, value['id'], actor)
        if job['case_id'] not in current['episodes']:
            raise WorkspaceConflict()

    def observe(self, envelope, output, outcome):
        """Trusted adapter callback; never a route accepting claimed verdicts."""
        with self.store.tx() as db:
            rows = _rows(db, 'SELECT workspace_id FROM reliability_eval_jobs WHERE id=?', (envelope['job_id'],))
            if len(rows) != 1:
                raise WorkspaceConflict()
            ws = rows[0]['workspace_id']
            job = self.evaluation._job(db, ws, envelope['job_id'])
            plan = self.evaluation._plan(db, ws)
            if (not plan or plan['revision'] != job['plan_revision']
                    or plan['corpus_hash'] != envelope['corpus_hash'] or plan.get('restore_quarantined')):
                raise WorkspaceConflict()
            value = self._for_corpus(db, ws, envelope['corpus_hash'], plan['corpus_id'])
            if value is None:
                return None
            episode = value['episodes'].get(envelope['case']['case_id'])
            if episode is None or episode['input_hash'] != _hash(envelope['case']['input']):
                raise WorkspaceConflict()
            state, source_hash = 'unknown' if outcome == 'unknown' else 'agent_failure', None
            if outcome == 'completed':
                try:
                    validate(value['contract_id'], envelope['case']['input'], output, now=clock())
                    source_hash = _hash(output)
                    if output['partial']:
                        state = 'unassessable'
                    else:
                        actual = {item_goal_hash(value['contract_id'], item) for item in output['items']}
                        state = 'goal_pass' if set(value['goals'][episode['base_case']]).issubset(actual) else 'agent_failure'
                except (TypeError, ValueError, KeyError):
                    state = 'oracle_error'
            result = {'manifest_id': value['id'], 'manifest_revision': value['revision'],
                      'job_id': envelope['job_id'], 'case_id': envelope['case']['case_id'],
                      'input_hash': episode['input_hash'], 'source_hash': source_hash, 'outcome': state,
                      'oracle_version': value['oracle_version'], 'independent_quality': 'unassessed'}
            return ResearchObservation(self, result, self.sign(result))

    def accept_observation(self, observation, envelope):
        if (type(observation) is not ResearchObservation or observation.owner is not self
                or not self._artifact_signer.verify(observation.value, observation.signature)
                or observation.value['job_id'] != envelope['job_id']
                or observation.value['case_id'] != envelope['case']['case_id']
                or observation.value['input_hash'] != _hash(envelope['case']['input'])):
            raise WorkspaceConflict()
        return deepcopy(observation.value)

    def prioritize(self, db, ws, plan, corpus, actor, window):
        """Optional coverage-first ordering inside existing admission budgets."""
        value = self._for_corpus(db, ws, corpus['corpus_hash'], corpus['id'])
        if value is None or not value['adaptive_priority']:
            return corpus['cases']
        self._current(db, ws, value['id'], actor)
        rows = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY window_start DESC,id LIMIT 501', (ws,))
        if len(rows) > 500:
            raise WorkspaceConflict()
        history = [self.evaluation._job(db, ws, r['id']) for r in rows]
        counts, latest = {}, {}
        for job in history:
            if job['plan_revision'] != plan['revision'] or job.get('restore_quarantined'):
                continue
            key = job['case_id']; counts[key] = counts.get(key, 0) + int(job['state'] == 'completed')
            latest[key] = max(latest.get(key, 0), job['created'])
        # No risk scores or expiry refresh are manufactured; deterministic tie
        # rotation prevents a low host budget always admitting the same prefix.
        return sorted(corpus['cases'], key=lambda c: (counts.get(c['case_id'], 0), latest.get(c['case_id'], 0),
            _hash([value['seed'], window, c['case_id']])))

    def prioritize_resources(self, db, ws, plan, corpus, actor, window):
        """Use observed change/failure/expiry/usage signals without new budget.

        This is an evaluation queue ordering, not a predicted success score.
        The current immutable pins and normal host quotas still gate every job.
        """
        value = self._for_corpus(db, ws, corpus['corpus_hash'], corpus['id'])
        if value is None or not value['adaptive_priority']:
            return sorted(plan['pins'].items())
        self._current(db, ws, value['id'], actor)
        rows = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY window_start DESC,id LIMIT 501', (ws,))
        if len(rows) > 500:
            raise WorkspaceConflict()
        history = [self.evaluation._job(db, ws, row['id']) for row in rows]
        now = clock()
        usage = {}
        execution = getattr(getattr(self.lineage, 'plane', None), 'execution', None)
        if execution is not None:
            # Use only verified, already-dispatched local work in this workspace.
            # The bounded sample is an ordering signal, never a business-success
            # claim and never permission to increase a provider's quota.
            runs = _rows(db, '''SELECT id,draft_id,snapshot_id FROM workspace_private_runs
                WHERE workspace_id=? AND created>=? ORDER BY created DESC,id LIMIT 200''', (ws, now-86400))
            for row in runs:
                try:
                    _, _, claims, run = execution._load_run(db, row['id'], ws, row['draft_id'],
                                                           row['snapshot_id'], decrypt_output=False)
                    if run['dispatched'] is not None:
                        rid = str(claims['resource_id']); usage[rid] = usage.get(rid, 0)+1
                except (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid):
                    continue
        signals = {}
        for rid, pin in plan['pins'].items():
            version = pin['pin']['version']['id']
            evidence = _rows(db, '''SELECT outcome,expires,finished FROM capability_evidence
                WHERE version_id=? AND scope='execution' ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1''', (version,))
            recent = [j for j in history if j['resource_id'] == int(rid)
                      and j['plan_revision'] == plan['revision'] and not j.get('restore_quarantined')]
            recent.sort(key=lambda j: (j['created'], j['id']), reverse=True)
            latest = next((j for j in recent if j['state'] in ('completed', 'failed', 'unknown')), None)
            failed = bool(latest and latest['state'] in ('failed', 'unknown'))
            expired = not evidence or evidence[0]['expires'] <= now
            changed = not recent
            last = max((j['created'] for j in recent), default=0)
            signals[rid] = (-int(changed), -int(failed), -int(expired), last, -usage.get(rid, 0),
                            _hash([value['seed'], window, rid]))
        return sorted(plan['pins'].items(), key=lambda item: signals[item[0]])

    def analyze(self, ws, identity, actor):
        with self.access._tx(actor) as (db, _):
            value, corpus = self._current(db, ws, identity, actor)
            plan, _, _ = self.evaluation._current(db, ws, actor)
            if (plan['corpus_id'] != value['corpus_id']
                    or plan['corpus_hash'] != corpus['corpus_hash']):
                raise WorkspaceConflict()
            self.evaluation._recover(db, ws, clock())
            rows = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY window_start DESC,id LIMIT 501', (ws,))
            if len(rows) > 500:
                raise WorkspaceConflict()
            jobs = [self.evaluation._job(db, ws, r['id']) for r in rows]
            jobs = [j for j in jobs if j['plan_revision'] == plan['revision'] and not j.get('restore_quarantined')]
            cells, groups = {}, {}
            for job in jobs:
                episode = value['episodes'].get(job['case_id'])
                if episode is None:
                    continue
                key = (job['resource_id'], job['host_key'], job['window_start'], episode['base_case'], episode['mutator'])
                group = groups.setdefault(key, {})
                observation = job.get('research_observation')
                result = observation.get('outcome') if type(observation) is dict else None
                if job['state'] == 'unknown':
                    result = 'unknown'
                elif job['state'] not in ('completed', 'failed'):
                    result = 'unassessable'
                elif (result not in OUTCOMES or observation.get('manifest_id') != identity
                      or observation.get('manifest_revision') != value['revision']):
                    result = 'unassessable'
                group[episode['trial']] = result
            for key, trials in groups.items():
                rid, host, window, base, mutator = key
                cell = cells.setdefault((rid, mutator), {'resource_id': rid, 'mutator': mutator, 'k': value['k'],
                    'epsilon': 0 if mutator == 'original' else 1, 'lambda': 0, 'admitted_groups': 0,
                    'all_k_pass': 0, 'all_k_observed': 0, 'unknown_episodes': 0, 'unassessable_episodes': 0,
                    'failed_episodes': 0, 'missing_episodes': 0, 'cluster_keys': set()})
                cell.setdefault('oracle_error_episodes', 0)
                cell.setdefault('invalid_transform_episodes', 0)
                cell['admitted_groups'] += 1; cell['cluster_keys'].add((host, window))
                cell['missing_episodes'] += value['k']-len(trials)
                outcomes = list(trials.values())
                cell['unknown_episodes'] += outcomes.count('unknown')
                cell['unassessable_episodes'] += sum(x in ('unassessable', 'oracle_error', 'invalid_transform') for x in outcomes)
                cell['failed_episodes'] += outcomes.count('agent_failure')
                cell['oracle_error_episodes'] += outcomes.count('oracle_error')
                cell['invalid_transform_episodes'] += outcomes.count('invalid_transform')
                complete = len(outcomes) == value['k'] and all(x in ('goal_pass', 'agent_failure') for x in outcomes)
                cell['all_k_observed'] += int(complete)
                cell['all_k_pass'] += int(complete and all(x == 'goal_pass' for x in outcomes))
            result = []
            for cell in cells.values():
                cell['independent_host_window_clusters'] = len(cell.pop('cluster_keys'))
                cell['conservative_admitted_all_k_rate'] = cell['all_k_pass']/cell['admitted_groups']
                cell['uncertainty'] = _wilson(cell['all_k_pass'], cell['admitted_groups'])
                cell['minimum_sample_met'] = cell['admitted_groups'] >= value['analysis']['minimum_pairs']
                cell['operating_inference'] = False
                result.append(cell)
            paired = {'both_goal_pass': 0, 'both_failed': 0, 'mr_violation': 0, 'unknown': 0,
                      'unassessable': 0, 'missing': 0, 'admitted_pairs': 0}
            for rid, host, window, base in {key[:4] for key in groups}:
                for mutator in value['mutators']:
                    original = groups.get((rid, host, window, base, 'original'), {})
                    transformed = groups.get((rid, host, window, base, mutator), {})
                    for trial in set(original) | set(transformed):
                        paired['admitted_pairs'] += 1
                        a, b = original.get(trial), transformed.get(trial)
                        if a is None or b is None: label = 'missing'
                        elif 'unknown' in (a, b): label = 'unknown'
                        elif a == b == 'goal_pass': label = 'both_goal_pass'
                        elif a == b == 'agent_failure': label = 'both_failed'
                        elif set((a, b)) == {'goal_pass', 'agent_failure'}: label = 'mr_violation'
                        else: label = 'unassessable'
                        paired[label] += 1
            start = math.floor(plan['created']/plan['interval_seconds'])*plan['interval_seconds']
            end = min(clock(), plan['expires'])
            windows = max(0, math.floor((end-start)/plan['interval_seconds'])+int(end < plan['expires']))
            expected = windows*len(plan['pins'])*len(value['episodes'])
            return {'profile': PROFILE, 'manifest': self._dto(value), 'cells': result, 'paired': paired,
                    'scheduled_episodes': len(jobs), 'expected_episodes': expected,
                    'unscheduled_episodes': max(0, expected-len(jobs)), 'analysis': value['analysis'],
                    'oracle_scope': 'exact_approved_corpus_goal_not_independent_factual_quality',
                    'invalid_transform_policy': 'reject_before_corpus_admission_without_provider_calls',
                    'manifest_definition_hash': value['definition_hash'], 'corpus_hash': value['corpus_hash'],
                    'plan_revision': plan['revision'], 'source_versions_hash': _hash(plan['pins']),
                    'promotion_status': 'pending_paired_intervention_evidence',
                    'false_stop_rate': None, 'successful_outcome_loss': None, 'judge_overhead_seconds': None,
                    'independent_quality': 'unassessed', 'predictive_model': False, 'operating_qualification': False,
                    'business_calls': 0, 'extra_evaluation_calls': 0, 'public_activation': False}

    def shadow(self, ws, identity, body, actor):
        exact(body, ('flow_id', 'run_id', 'authorized', 'notice', 'stagnation_actions'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        _integer(body['stagnation_actions'], 2, 20)
        if not callable(getattr(self.lineage, 'current_run', None)):
            raise WorkspaceConflict()
        with self.access._tx(actor) as (db, _):
            value, _ = self._current(db, ws, identity, actor)
            manifest_revision = value['revision']
        source = self.lineage.current_run(ws, body['flow_id'], body['run_id'], actor)
        # This adapter accepts metadata produced by the trusted current-purpose
        # lineage core, never caller-submitted traces or inferred thoughts.
        with self.access._tx(actor) as (db, _):
            value, _ = self._current(db, ws, identity, actor)
            if value['revision'] != manifest_revision:
                raise WorkspaceConflict()
        current_source = self.lineage.current_run(ws, body['flow_id'], body['run_id'], actor)
        if current_source != source:
            raise WorkspaceConflict()
        if (type(source) is not dict or source.get('current') is not True
                or source.get('evidence_current') is not True
                or source.get('profile') != 'p2-01-typed-evidence-profile-v1'):
            raise WorkspaceConflict()
        nodes = source.get('nodes')
        if type(nodes) is not list or len(nodes) > 6:
            raise WorkspaceConflict()
        events = source.get('events')
        if type(events) is not list or len(events) > 100:
            raise WorkspaceConflict()
        raw, closed, reasons, since_closed, last = [], 0, [], 0, -1
        node_ids = {node['node_id'] for node in nodes if type(node) is dict and type(node.get('node_id')) is str}
        if len(node_ids) != len(nodes):
            raise WorkspaceConflict()
        for event in events:
            if (type(event) is not dict or type(event.get('sequence')) is not int
                    or event['sequence'] <= last or event.get('node_id') not in node_ids
                    or event.get('event_type') not in ('dispatch', 'closed_action', 'terminal_observation')):
                raise WorkspaceConflict()
            _number(event.get('observed_at'))
            last = event['sequence']
            raw.append({'k': len(raw)+1, 'node_id': event['node_id'], 'event_type': event['event_type']})
            if event['event_type'] == 'closed_action':
                if event.get('closed_action_sequence') != closed+1:
                    raise WorkspaceConflict()
                closed += 1; since_closed = 0
            else:
                since_closed += 1
        if since_closed >= body['stagnation_actions']:
            reasons.append('observed_events_without_closed_action')
        return {'profile': PROFILE, 'manifest_revision': manifest_revision,
                'manifest_definition_hash': value['definition_hash'], 'corpus_hash': value['corpus_hash'],
                'analysis_version': value['analysis']['version'],
                'source_revision': source.get('source_revision'), 'raw_events': raw,
                'raw_event_count': len(raw), 'closed_action_count': closed,
                'evaluation_sequence': 1, 'would_stop': bool(reasons), 'reasons': sorted(set(reasons)),
                'observation_scope': 'typed_lineage_events_not_remote_agent_internal_actions',
                'counterfactual_saved_steps': None, 'actual_interventions': 0, 'remote_cancel_confirmed': False,
                'promotion_status': 'pending_paired_intervention_evidence',
                'false_stop_rate': None, 'successful_outcome_loss': None, 'judge_overhead_seconds': None,
                'business_calls': 0, 'extra_evaluation_calls': 0, 'independent_quality': 'unassessed',
                'operating_qualification': False, 'public_activation': False}


def item_goal_hash(contract_id, item):
    fields = ('url', 'title', 'excerpt', 'version') if contract_id == 'docs.search.v1' else ('url', 'title', 'summary', 'source', 'published_at')
    return _hash({key: item[key] for key in fields})


def fixture_fault(response, *, seed, fault, environment):
    """Pure fixture helper; cannot fetch, dispatch or mutate production traffic."""
    _integer(seed, 0, 2**31-1)
    if environment != 'isolated_fixture' or fault not in ('rate_limit', 'response_loss', 'partial', 'schema_drift'):
        raise WorkspaceInvalid()
    if fault == 'rate_limit':
        return {'outcome': 'unknown', 'fixture_fault': fault, 'seed': seed}
    if fault == 'response_loss':
        return {'outcome': 'unknown', 'fixture_fault': fault, 'seed': seed}
    if fault == 'partial':
        return {'output': {'items': [], 'partial': True}, 'fixture_fault': fault, 'seed': seed}
    return {'output': {'schema_drift_fixture': _hash(response)}, 'fixture_fault': fault, 'seed': seed}
