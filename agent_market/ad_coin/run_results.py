"""Settle an AI AD Coin execution from the workflow runs that actually happened.

The person (or the operator) names the run ids. Each run must belong to the
quoted workflow, start after the coins or voucher were committed and settle at
most one execution. Per line, the provider is paid for the calls that
succeeded across those runs; the rest returns to whoever funded it. Run inputs
and outputs are never read here, only run and step status.
"""
import hashlib
import re

from .db import now
from .receipts import canonical

# Exact statements already registered for the production PostgreSQL store.
SQL_RUN = 'SELECT * FROM workflow_runs WHERE id=?'
SQL_STEPS = 'SELECT node_id,status,started,finished FROM workflow_node_runs WHERE run_id=? ORDER BY node_id LIMIT 50'
OPEN = frozenset(('queued', 'running', 'pending'))
RUN_ID = re.compile(r'[A-Za-z0-9_-]{6,80}\Z')
TASK_REF = re.compile(r'(workflow|private|product)-(.+?)(?:-([0-9a-f]{12}))?-x(\d{1,3})\Z')
MAX_RUNS = 100


class RunMismatch(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_task_ref(task_ref):
    match = TASK_REF.fullmatch(task_ref or '')
    if not match:
        return None
    kind = {'workflow': 'workflow', 'private': 'private_workflow', 'product': 'test_product'}[match.group(1)]
    ident = match.group(2)
    if kind == 'workflow':
        if not ident.isdigit():
            return None
        ident = int(ident)
    return {'kind': kind, 'id': ident, 'runs': int(match.group(4))}


def public_run(store, run_id):
    """{'workflow_id', 'status', 'created', 'steps': [{'node_id', 'status'}]} or None."""
    rows = store.query(SQL_RUN, (run_id,))
    if not rows:
        return None
    run = dict(rows[0])
    steps = [dict(r) for r in store.query(SQL_STEPS, (run_id,))]
    return {'workflow_id': run.get('workflow_id'), 'status': run.get('status'), 'created': run.get('created'),
            'steps': [{'node_id': s['node_id'], 'status': s['status']} for s in steps]}


def node_resources(definition):
    """node id -> catalog resource id, for agent nodes that are not disabled."""
    mapping = {}
    for node in (definition or {}).get('nodes') or []:
        if not isinstance(node, dict) or node.get('type', 'agent') != 'agent':
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        rid = node.get('resource_id') or data.get('resource_id')
        if type(rid) is int and not (node.get('disabled') or data.get('disabled')):
            mapping[str(node.get('id'))] = rid
    return mapping


def successful_calls(lines, mapping, runs):
    """Per execution line, how many calls succeeded across the runs (capped at the line)."""
    counts = {}
    for run in runs:
        for step in run['steps']:
            rid = mapping.get(str(step['node_id']))
            if rid is not None and step['status'] == 'succeeded':
                counts[rid] = counts.get(rid, 0) + 1
    result = []
    for line in lines:
        rid = int(line['provider'][1:]) if re.fullmatch(r'r\d+', line['provider']) else None
        result.append(min(counts.get(rid, 0), line['calls']))
    return result


def reconcile(service, *, execution_id, user_ref, run_ids, load_run, definition, admin=False):
    """`load_run(run_id)` returns the run dict above (or None); `definition` is the
    quoted workflow's current definition (nodes with resource ids)."""
    row = service.db.one('SELECT * FROM ad_coin_executions WHERE id=?', (execution_id,))
    if not row or (not admin and row['user_ref'] != user_ref):
        raise RunMismatch('unknown_execution', 'No such execution for you.')
    if row['status'] != 'running':
        raise RunMismatch('execution_closed', 'This execution is already settled.')
    target = parse_task_ref(row['task_ref'])
    if not target or target['kind'] == 'test_product':
        raise RunMismatch('not_a_workflow_execution', 'Only workflow executions settle from runs; '
                          'test products stay simulated.')
    if not isinstance(run_ids, list) or len(run_ids) != target['runs'] or len(set(run_ids)) != len(run_ids) \
            or any(type(r) is not str or not RUN_ID.fullmatch(r) for r in run_ids):
        raise RunMismatch('invalid_runs', 'Name exactly %d distinct run ids, one per quoted run.' % target['runs'])
    runs = []
    for run_id in run_ids:
        run = load_run(run_id)
        if not run:
            raise RunMismatch('unknown_run', 'Run %s is not available to you.' % run_id)
        if target['kind'] == 'workflow' and run.get('workflow_id') != target['id']:
            raise RunMismatch('run_of_another_workflow', 'Run %s belongs to another workflow.' % run_id)
        if not isinstance(run.get('created'), (int, float)) or run['created'] < row['created_at'] - 1:
            raise RunMismatch('run_before_payment', 'Run %s started before this execution was paid.' % run_id)
        if run.get('status') in OPEN:
            return {'status': 'waiting', 'run': run_id, 'message': 'A run is still in progress; try again later.'}
        runs.append(run)
    lines = service._lines_of(execution_id)
    if not lines:
        raise RunMismatch('no_lines', 'This execution has no bundle lines to settle.')
    results = successful_calls(lines, node_resources(definition), runs)
    keys = [target['kind'] + ':' + str(target['id']) + ':' + r for r in run_ids]
    with service.db.transaction() as db:
        taken = [k for k in keys if db.execute('SELECT 1 FROM ad_coin_run_claims WHERE run_key=?', (k,)).fetchone()]
        if taken:
            raise RunMismatch('run_already_used', 'A run can settle only one execution.')
        for key in keys:
            db.execute('INSERT INTO ad_coin_run_claims VALUES (?,?,?)', (key, execution_id, now()))
        digest = 'sha256:' + hashlib.sha256(canonical({'runs': run_ids, 'steps': [
            [(s['node_id'], s['status']) for s in run['steps']] for run in runs]})).hexdigest()
        settled = service.complete(execution_id=execution_id, ok=any(results), result_digest=digest,
                                   line_results=results)
    return {**settled, 'line_calls_succeeded': results, 'runs': run_ids}
