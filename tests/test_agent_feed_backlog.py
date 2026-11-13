"""The change feed settles its backlog faster without changing what it publishes (PM 11-13 23:0x, plan A).

On 11-13 the feed was 97 hours behind: rounds evaluate 32 rows every ~30 s (about 92k a day) while about 125k rows a day
arrive, and 96% of the 508k pending rows were empty repeats of a resource. A round now reads a wider window and marks a
repeat ignored when this round already evaluated its resource. Evaluating one row per round with a window of one is
exactly the earlier way, so the two are compared on the same input.
"""
import json
import time

from agent_market.agent_access import events as events_module
from agent_market.agent_access.storage import enqueue, transaction
from agent_market.capability_registry import Registry
from tests.test_agent_adoption import adoption  # noqa: F401
from tests.test_workflow_fallback import routing  # noqa: F401

TABLES = ('adoption_changes', 'adoption_publications')


def snapshot(store):
    with store.tx() as db:
        rows = {t: [dict(r) for r in db.execute(f'SELECT * FROM {t}').fetchall()] for t in TABLES}
        rows['meta'] = [dict(r) for r in db.execute("SELECT * FROM meta WHERE key='adoption_published_sequence'").fetchall()]
    return rows


def restore(store, rows):
    with store.tx() as db:
        for table in TABLES:
            db.execute(f'DELETE FROM {table}')
            for row in rows[table]:
                names = list(row)
                db.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
                           [row[n] for n in names])
        db.execute("DELETE FROM meta WHERE key='adoption_published_sequence'")
        for row in rows['meta']:
            db.execute('INSERT INTO meta(key,value) VALUES (?,?)', (row['key'], row['value']))


def outcome(store):
    """Everything a reader or a later round can see, without the wall-clock times of this run."""
    with store.tx() as db:
        changes = []
        for r in db.execute('SELECT id,status,published_seq,payload FROM adoption_changes ORDER BY created,id').fetchall():
            payload = json.loads(r['payload']) if r['payload'] and r['status'] == 'published' else r['payload']
            if isinstance(payload, dict):
                payload.pop('observed_at', None)
            changes.append((r['id'], r['status'], r['published_seq'], json.dumps(payload, sort_keys=True)))
        publications = [tuple(r) for r in db.execute(
            'SELECT resource_id,signature,version_id,verified,state FROM adoption_publications ORDER BY resource_id').fetchall()]
        seq = db.execute("SELECT value FROM meta WHERE key='adoption_published_sequence'").fetchone()
    return changes, publications, seq['value'] if seq else None


def drain(events, **kw):
    rounds = 0
    while events.store.query("SELECT 1 FROM adoption_changes WHERE status='pending' LIMIT 1"):
        events.publish(**kw)
        rounds += 1
        assert rounds < 10000
    return rounds


def backlog(core, ids):
    """A verified baseline, then a backlog like 11-13's: empty repeats, health observations and real changes."""
    store = core.front.store
    registry = Registry(store)
    for rid in ids[:2]:
        version = registry.current(store.resource(rid))
        registry.record(version, scope='execution', outcome='succeeded', started=time.time() - 1, finished=time.time() - 1)
    drain(core.events, limit=1, window=1)
    with transaction(store) as db:
        for n in range(6):
            for rid in ids[:3]:
                enqueue(store, db, rid, 'catalog_changed', evidence=['capability', 1000 + n])
                enqueue(store, db, rid, 'recheck', store.resource(rid).get('version_id'), 2000 + n)
            if n == 2:   # a health observation between the repeats (published as health_changed)
                enqueue(store, db, ids[0], 'catalog_changed', evidence=['health', 3000],
                        observation={'scope': 'health', 'status': 'degraded', 'finished': time.time()})
        db.execute("UPDATE resources SET active=0 WHERE id=?", (ids[1],))        # withdrawn
        db.execute("UPDATE resources SET eval_grade='B' WHERE id=?", (ids[0],))   # quality changed


def test_the_wide_window_publishes_exactly_what_one_row_at_a_time_publishes(adoption):
    core, visitor, ids, *_ = adoption
    store = core.front.store
    backlog(core, ids)
    start = snapshot(store)
    pending = len(store.query("SELECT 1 FROM adoption_changes WHERE status='pending'"))
    assert pending >= 30

    one_by_one = drain(core.events, limit=1, window=1)          # the earlier way: one evaluation per round
    before = outcome(store)
    restore(store, start)
    wide = drain(core.events, limit=2, window=200)               # few evaluations, wide window
    after = outcome(store)

    assert after == before
    published = [c for c in before[0] if c[1] == 'published']
    assert published and {json.loads(c[3])['event_type'] for c in published} >= {'withdrawn', 'health_changed'}
    assert wide < one_by_one / 3, (wide, one_by_one)


def test_a_round_evaluates_at_most_its_limit_and_marks_only_repeats_of_what_it_evaluated(adoption):
    core, visitor, ids, *_ = adoption
    store = core.front.store
    backlog(core, ids)
    pending = {r['id'] for r in store.query("SELECT id FROM adoption_changes WHERE status='pending'")}
    core.events.publish(limit=1, window=200)
    rows = [r for r in store.query("SELECT id,resource_id,status,payload FROM adoption_changes "
                                   "WHERE status!='pending' ORDER BY created,id") if r['id'] in pending]
    evaluated = {r['resource_id'] for r in rows}
    assert len(evaluated) == 1 and len(rows) > 1, rows          # one resource evaluated, its empty repeats settled
    assert all(r['payload'] is None for r in rows[1:])          # observations are never settled as repeats
    assert store.query("SELECT 1 FROM adoption_changes WHERE status='pending' AND payload IS NOT NULL")


def test_the_window_grows_while_rounds_are_quick_and_shrinks_when_slow(adoption, monkeypatch):
    core, *_ = adoption
    events = core.events
    assert events.window == events_module.WINDOW_START == 200
    for _ in range(30):
        events._paced(0.1, events.window, 1, 0, 0)
    assert events.window == events_module.WINDOW_MAX == 2000    # 11-14 plan A2 (was 500)
    events._paced(3.5, events.window, 1, 0, 0)
    assert events.window == 1000
    for _ in range(3):
        events._paced(3.5, events.window, 1, 0, 0)
    assert events.window == 200                                 # never below the start


def test_time_budgeted_rounds_and_tick_catch_up_publish_exactly_what_one_row_at_a_time_publishes(adoption, monkeypatch):
    """11-14 (PM 03:1x, plan A2): a round evaluates until its time budget or EVAL_MAX, and the tick runs more rounds while
    a round fills its window. The published events, ids, sequence and publications equal the one-by-one way."""
    core, visitor, ids, *_ = adoption
    store = core.front.store
    backlog(core, ids)
    start = snapshot(store)
    drain(core.events, limit=1, window=1)
    before = outcome(store)
    for budget in (0.0, 10.0):                     # one evaluation a round (budget spent at once) and no time limit
        restore(store, start)
        drain(core.events, budget=budget)
        assert outcome(store) == before, budget
    restore(store, start)
    monkeypatch.setattr(events_module, 'WINDOW_START', 4)
    events = core.events
    events.window = 4                              # a small window, so the backlog fills it and the tick goes on
    ticks = 0
    while store.query("SELECT 1 FROM adoption_changes WHERE status='pending' LIMIT 1"):
        events.catch_up(rounds=8, budget=10.0)
        ticks += 1
        assert ticks < 100
    assert outcome(store) == before
    assert ticks == 1                              # one tick settled the whole backlog in several rounds


def test_a_round_stops_evaluating_when_its_time_budget_is_spent(adoption, monkeypatch):
    core, visitor, ids, *_ = adoption
    store = core.front.store
    backlog(core, ids)
    clock = iter(range(0, 10_000, 5))              # every reading of the clock is 5 s later
    monkeypatch.setattr(events_module.time, 'monotonic', lambda: next(clock))
    core.events.publish(budget=1.0)
    evaluated = {r['resource_id'] for r in store.query(
        "SELECT resource_id FROM adoption_changes WHERE status IN ('published','ignored') AND payload IS NULL")}
    assert len(evaluated) == 1                      # the first evaluation always runs; the budget stops the rest
