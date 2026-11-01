"""Daily health summaries (design 5.3): bounded steps, exact aggregates, idle until migrated."""
# ruff: noqa: F811 -- shared isolated fixtures
from agent_market import workspace_admin_summaries as module
from agent_market.workspace_admin_events import migrate
from agent_market.workspace_admin_summaries import DAY, HealthSummaries, day_key
from tests.test_admin_next import login
from tests.test_dashboard import dash  # noqa: F401

NOW = 1_800_000_000.0 + 12 * 3600  # midday UTC, fixed


def seed(store, rid, start, outcomes):
    with store.tx() as db:
        for i, (outcome, latency) in enumerate(outcomes):
            db.execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(?,?,?,?,?)',
                       (rid, start + 60 * i, outcome, 200, latency))


def test_worker_is_idle_until_migrated_and_endpoints_say_so(dash):
    world, client = dash
    assert HealthSummaries(world.store, clock=lambda: NOW).run_due(force=True) == {'ready': False}
    staff = login(client)
    assert client.get('/admin/api/v2/system/summaries', headers=staff).json()['available'] is False
    assert client.get('/admin/api/v2/catalog/agents/1/daily', headers=staff).json()['available'] is False


def test_backfill_steps_one_day_then_refreshes_today(dash, monkeypatch):
    world, client = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    today = int(NOW // DAY) * DAY
    seed(world.store, 7, today - 2 * DAY, [('healthy', 100), ('healthy', 300), ('down', None), ('reachable', 200)])
    seed(world.store, 7, today, [('failing', 900), ('healthy', 100)])
    seed(world.store, 8, today - DAY, [('healthy', 50)] * 3)
    clock = [NOW]
    worker = HealthSummaries(world.store, clock=lambda: clock[0])
    steps = [worker.run_due(force=True) for _ in range(9)]
    days = [step.get('day') for step in steps if step.get('agents') is not None]
    assert days[:7] == [day_key(today - n * DAY) for n in range(7, 0, -1)]  # oldest first, one per step
    assert days[7] == day_key(today) and steps[7]['partial'] and steps[8] == {'ready': True, 'idle': True}
    rows = {(row['day'], row['checks']): row for row in worker.agent(7, days=30)}
    two_days = rows[(day_key(today - 2 * DAY), 4)]
    assert two_days['ok'] == 3 and two_days['latency_p50'] == 200 and two_days['latency_p95'] == 300
    assert rows[(day_key(today), 2)]['ok'] == 1
    assert [row['checks'] for row in worker.agent(8)] == [3]
    # Re-running a day replaces, never duplicates.
    worker.summarize_day(today - 2 * DAY)
    assert len(worker.agent(7)) == 2
    assert worker.span()['n'] == 3
    # The current day refreshes at most hourly.
    clock[0] += 1800
    assert worker.run_due(force=True) == {'ready': True, 'idle': True}
    clock[0] += 1801
    assert worker.run_due(force=True)['partial'] is True
    assert worker.run_due() is None  # within the call interval
    staff = login(client)
    daily = client.get('/admin/api/v2/catalog/agents/7/daily?days=30', headers=staff).json()
    assert daily['available'] and [row['checks'] for row in daily['days']] == [4, 2]
    assert client.get('/admin/api/v2/catalog/agents/7/daily?days=5', headers=staff).status_code == 400
    assert client.get('/admin/api/v2/system/summaries', headers=staff).json()['health_daily']['n'] == 3


def test_large_days_are_written_in_short_batches(dash, monkeypatch):
    world, _ = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    today = int(NOW // DAY) * DAY
    for rid in range(100, 112):
        seed(world.store, rid, today - DAY, [('healthy', rid)])
    transactions = []
    original = module.transaction
    def counted(store, readonly=False):
        if not readonly:
            transactions.append(1)
        return original(store, readonly)
    monkeypatch.setattr(module, 'BATCH', 5)
    monkeypatch.setattr(module, 'transaction', counted)
    assert HealthSummaries(world.store, clock=lambda: NOW).summarize_day(today - DAY) == 12
    assert len(transactions) == 3  # 12 agents in batches of 5


def test_failures_are_logged_and_do_not_stop_the_scheduler(dash, monkeypatch):
    world, _ = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    worker = HealthSummaries(world.store, clock=lambda: NOW)
    monkeypatch.setattr(worker, 'aggregate', lambda start: (_ for _ in ()).throw(RuntimeError('synthetic')))
    assert worker.run_due(force=True) == {'ready': True, 'failed': True}


def test_days_are_read_in_agent_pages(dash, monkeypatch):
    world, _ = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    today = int(NOW // DAY) * DAY
    for rid in range(200, 205):
        seed(world.store, rid, today - DAY, [('healthy', rid), ('down', None)])
    monkeypatch.setattr(module, 'PAGE', 2)
    worker = HealthSummaries(world.store, clock=lambda: NOW)
    assert [len(page) for page in worker.aggregate(today - DAY)] == [2, 2, 1]
    assert worker.summarize_day(today - DAY) == 5
    assert [row['ok'] for rid in range(200, 205) for row in worker.agent(rid)] == [1] * 5
