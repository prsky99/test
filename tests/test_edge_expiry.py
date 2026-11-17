"""11-18 (PM 11-17 night, edge plan A): lost attempts close at the time they were lost with their own code, an unclaimed
ticket is closed (not deleted), and only a recent claim holds an in-flight slot."""
from agent_market.edge_gateway.state import execute, rows, transaction
from tests.test_edge_gateway import edge, catalog, proposal, prepare, claim  # noqa: F401  (fixtures and helpers)


def _row(edge, run_id):
    with transaction(edge.store, readonly=True) as db:
        return rows(db, 'run', (run_id,))[0]


def test_a_lost_attempt_closes_at_created_plus_180_with_completion_missing(edge):
    value = proposal(edge); grant = prepare(edge, value); claim(edge, grant, value)
    created = _row(edge, grant['run_id'])['created']
    edge.clock[0] += 5000          # someone looks long after the attempt was lost
    state = edge.service.status(edge.principal, grant['run_id'])
    assert state['state'] == 'outcome_unknown' and state['error_code'] == 'COMPLETION_MISSING'
    assert _row(edge, grant['run_id'])['finished'] == created + 180


def test_the_sweep_closes_lost_attempts_and_unclaimed_tickets_without_deleting(edge):
    lost_value = proposal(edge); lost = prepare(edge, lost_value); claim(edge, lost, lost_value)
    idle = prepare(edge, proposal(edge))
    edge.clock[0] += 200
    assert edge.service.sweep() == {'lost': 1, 'unclaimed': 1}
    assert _row(edge, lost['run_id'])['state'] == 'outcome_unknown'
    closed = _row(edge, idle['run_id'])
    assert closed['state'] == 'expired_unclaimed' and closed['error_code'] == 'EXPIRED_UNCLAIMED' and closed['finished'] == closed['expires']
    assert edge.service.sweep() == {'lost': 0, 'unclaimed': 0}      # idempotent


def test_only_a_recent_claim_holds_an_in_flight_slot(edge):
    value = proposal(edge); grant = prepare(edge, value); claim(edge, grant, value)
    with transaction(edge.store, readonly=True) as db:
        now = edge.clock[0]
        assert rows(db, 'active', (now - 45,))[0]['n'] == 1
        assert rows(db, 'active', (now + 60 - 45,))[0]['n'] == 0     # 60 s later nobody is waiting on it


def test_the_recommendation_count_ignores_runs_whose_completion_never_arrived(edge):
    from agent_market.application_store_selection import __doc__ as _doc  # noqa: F401  (module imports)
    import inspect, agent_market.application_store_selection as selection
    source = inspect.getsource(selection)
    assert "NOT IN ('COMPLETION_MISSING','CALLER_ABORTED')" in source


def _loop_once(edge, outcomes, monkeypatch, clock=None):
    import agent_market.edge_gateway.monitor as monitor_module
    from agent_market.edge_gateway.monitor import Monitor
    monkeypatch.setattr(monitor_module, 'RETRY_SECONDS', 0)
    if clock is not None:
        edge.clock[0] = clock
    watcher = Monitor(edge.service, 'a' * 32, 'synthetic-token', client=object())
    calls, pending = [], list(outcomes)

    def refresh():
        calls.append(1)
        outcome = pending.pop(0)
        if outcome:
            raise outcome
    watcher.refresh = refresh
    watcher.stop.wait = lambda seconds: (watcher.stop.set() if seconds == 60 else None) or False
    watcher.loop()
    return calls


def test_a_refusal_that_cannot_change_in_five_seconds_is_not_retried(edge, monkeypatch):
    from agent_market.edge_gateway.config import EdgeError
    assert len(_loop_once(edge, [EdgeError('CONFIGURATION_INVALID')], monkeypatch)) == 1
    assert len(_loop_once(edge, [EdgeError('OBSERVATION_UNAVAILABLE'), None], monkeypatch)) == 2     # transient: retried
    assert len(_loop_once(edge, [OSError('connect timed out'), None], monkeypatch)) == 2             # connection error: retried


def test_an_analytics_miss_in_the_first_minutes_of_the_utc_day_is_not_retried(edge, monkeypatch):
    err = OSError('slow'); err.edge_leg = 'analytics'
    assert len(_loop_once(edge, [err], monkeypatch, clock=86400 * 20410 + 60)) == 1
    err2 = OSError('slow'); err2.edge_leg = 'analytics'
    assert len(_loop_once(edge, [err2, None], monkeypatch, clock=86400 * 20410 + 4000)) == 2
