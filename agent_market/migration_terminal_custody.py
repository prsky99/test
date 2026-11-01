"""Explicit offline handoff of terminal uncertainty, without rewriting outcomes.

The ordinary migration profile remains strictly quiescent. This opt-in profile
admits only expired, terminal executions protected by existing no-replay guards
and never-attempted manual-poll events. Active or outbound work stays blocked.
Every historical row is still included in the whole-application copy digest.
"""
import hashlib
import hmac
import json
import math
import time

PROFILE = 'preserve-terminal-history-no-replay-v1'
MAX_ROWS = 10000


def _rows(store, statement):
    cursor = store._execute(statement)
    names = [item[0] for item in cursor.description]
    try:
        values = cursor.fetchmany(MAX_ROWS + 1)
        if len(values) > MAX_ROWS:
            raise ValueError('terminal_history_limit')
        return [dict(zip(names, row)) for row in values]
    finally:
        cursor.close()


def _timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def inspect(store):
    """Inspect inside the caller's source/target writer fences; never mutate."""
    from .application_store_migration import _signed_effects_quiescent
    from .private_artifact_keys import ArtifactSigner
    from .workspace_access import PROFILE as ACCESS_PROFILE, _hash, _tree
    from .workspace_typed_flows import PROFILE as TYPED_PROFILE

    now = time.time()
    # These queues must be fully drained even with explicit history custody.
    for statement in (
        "SELECT COUNT(*) FROM public.workflow_runs WHERE status IN ('queued','running')",
        "SELECT COUNT(*) FROM public.workflow_result_outbox WHERE status IN ('pending','claimed','dispatched','unknown')",
        "SELECT COUNT(*) FROM public.workspace_private_runs WHERE status IN ('prepared','dispatched','unknown')",
        "SELECT COUNT(*) FROM public.workspace_typed_flow_runs WHERE status='running'",
        "SELECT COUNT(*) FROM public.workspace_meter_operations WHERE status='admitted'",
        "SELECT COUNT(*) FROM public.agent_task_events WHERE status IN ('pending','sending')",
        "SELECT COUNT(*) FROM public.clearing_ledger WHERE status='held'",
        "SELECT COUNT(*) FROM public.workflow_manual_deliveries WHERE status IN ('pending','claimed','dispatched','unknown')",
    ):
        if store._execute(statement).fetchone()[0]:
            raise ValueError('active_or_outbound_effects_remain')
    if not _signed_effects_quiescent(store):
        raise ValueError('signed_external_effects_remain')

    runs = _rows(store, "SELECT * FROM public.workflow_runs WHERE execution_outcome='unknown'")
    for run in runs:
        if (run['status'] not in ('failed', 'cancelled')
                or not _timestamp(run['finished']) or run['finished'] > now
                or type(run['lease_until']) not in (int, float)
                or not math.isfinite(run['lease_until']) or run['lease_until'] > 0):
            raise ValueError('nonterminal_execution_history')

    attempts = _rows(store, """SELECT a.*,r.status AS parent_status,
        r.finished AS parent_finished,r.lease_until AS parent_lease
        FROM public.workflow_execution_attempts a LEFT JOIN public.workflow_runs r ON r.id=a.run_id
        WHERE a.status IN ('prepared','dispatched','unknown')""")
    for attempt in attempts:
        if (attempt['status'] == 'dispatched' or attempt['parent_status'] not in ('failed', 'cancelled')
                or not _timestamp(attempt['parent_finished']) or attempt['parent_finished'] > now
                or type(attempt['parent_lease']) not in (int, float)
                or not math.isfinite(attempt['parent_lease']) or attempt['parent_lease'] > 0
                or attempt['status'] == 'prepared' and attempt['dispatched'] is not None):
            raise ValueError('resumable_or_dispatched_attempt')

    runtime_key = hmac.new(store.workflow_key, b'workflow-results-v1', hashlib.sha256).digest()
    access_key = hmac.new(runtime_key, ACCESS_PROFILE.encode('ascii'), hashlib.sha256).digest()
    signer = ArtifactSigner(hmac.new(access_key, TYPED_PROFILE.encode(), hashlib.sha256).digest(), TYPED_PROFILE)

    def opened(row, fields):
        if type(row['payload']) is not str or len(row['payload']) > 200000:
            raise ValueError('invalid_terminal_signature')
        # Reject duplicate keys rather than silently selecting a locator.
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('invalid_terminal_signature')
                value[key] = item
            return value
        value = json.loads(row['payload'], object_pairs_hook=unique)
        _tree({name: item for name, item in value.items() if name != 'encrypted_output'})
        if (type(value) is not dict or value.get('profile') != TYPED_PROFILE
                or not signer.verify(value, row['signature'])
                or any(value.get(name) != row[name] for name in fields)):
            raise ValueError('invalid_terminal_signature')
        return value

    typed = _rows(store, "SELECT * FROM public.workspace_typed_flow_runs WHERE status='unknown'")
    tickets = {row['id']: row for row in _rows(store, """SELECT t.* FROM public.workspace_typed_flow_tickets t
        JOIN public.workspace_typed_flow_runs r ON r.ticket_id=t.id WHERE r.status='unknown'""")}
    steps = _rows(store, """SELECT s.* FROM public.workspace_typed_flow_steps s
        JOIN public.workspace_typed_flow_runs r ON r.id=s.run_id WHERE r.status='unknown'""")
    versions = {}
    for row in typed:
        value = opened(row, ('id', 'ticket_id', 'workspace_id', 'flow_id', 'status', 'created', 'deadline'))
        if (not _timestamp(value.get('deadline')) or value['deadline'] > now
                or not _timestamp(value.get('finished')) or value['finished'] > now):
            raise ValueError('unexpired_typed_execution')
        ticket = tickets.get(row['ticket_id'])
        if ticket is None:
            raise ValueError('unconsumed_typed_ticket')
        claims = opened(ticket, ('id', 'workspace_id', 'flow_id', 'version_id', 'expires'))
        if (ticket['run_id'] != row['id'] or ticket['workspace_id'] != row['workspace_id']
                or ticket['flow_id'] != row['flow_id'] or value.get('ticket_hash') != _hash(claims)):
            raise ValueError('unconsumed_typed_ticket')
        versions[row['id']] = ticket['version_id']
    for step in steps:
        value = opened(step, ('run_id', 'node_id', 'status'))
        if value.get('version_id') != versions[step['run_id']]:
            raise ValueError('changed_typed_step_version')

    polls = _rows(store, """SELECT e.*,w.channel FROM public.agent_task_events e
        LEFT JOIN public.agent_task_watches w ON w.id=e.watch_id WHERE e.status='ready'""")
    if any(row['channel'] != 'poll' or type(row['attempts']) is not int or row['attempts'] != 0 for row in polls):
        raise ValueError('outbound_event_not_manual_poll')

    return {'profile': PROFILE, 'unknown_workflow_runs': len(runs),
            'terminal_execution_attempts': len(attempts), 'unknown_typed_runs': len(typed),
            'manual_poll_events': len(polls), 'outcomes_rewritten': False,
            'automatic_replay_enabled': False, 'outbound_delivery_performed': False}


def quiescent(store, policy):
    """Unknown policy names and failed custody validation always fail closed."""
    if policy != PROFILE:
        return False
    try:
        inspect(store)
        return True
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return False
