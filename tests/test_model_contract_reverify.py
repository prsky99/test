"""Scheduled re-verification of approved model-proposal search connections (2026-10-27)."""
import time

from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.model_contract_reverify import ContractReverifier, INTERVAL
from tests.test_capability_registry import contract_fixture
from tests.test_fast_single_recommendation import catalog  # noqa: F401  (fixture)
from tests.test_managed_agent_gateway import managed  # noqa: F401  (fixture)

SPEC = {'name': 'search_docs', 'description': 'Search documentation',
        'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'language': {'const': 'en'},
                                                         'limit': {'type': 'integer'}}},
        'annotations': {'readOnlyHint': True}}


def _docs(store, rid, remote):
    remote.tools = [SPEC]
    compact = usage.compact_tools(remote.tools)
    store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, None, full_tools=remote.tools)
    remote.call_result = {'structuredContent': contract_fixture('docs.search.v1')[1]}
    return store.resource(rid)


def test_approved_current_connection_is_checked_once_per_interval(managed):
    store, front, _, _, rid, calls, remote = managed
    resource = _docs(store, rid, remote)
    Registry(store).approve(resource, 'docs.search.v1', 'search_docs')
    clock = [time.time()]
    reverify = ContractReverifier(store, front.proxy, clock=lambda: clock[0])
    assert reverify.due()
    assert reverify.run() == {'checked': 1, 'succeeded': 1, 'skipped': 0}
    projection = Registry(store).projection(store.resource(rid))
    assert projection['connection_readiness']['verified_callable']
    assert projection['capability_contracts'][0]['verified']
    sent = len(calls)
    assert not reverify.due()  # the next look is an hour away
    clock[0] += 3601
    assert reverify.due() and reverify.run()['checked'] == 0 and len(calls) == sent
    clock[0] += INTERVAL
    assert reverify.run()['checked'] == 1 and len(calls) > sent


def test_approval_is_not_created_and_unsafe_connections_are_skipped(managed):
    store, front, _, _, rid, calls, remote = managed
    resource = _docs(store, rid, remote)
    reverify = ContractReverifier(store, front.proxy)
    assert reverify.run()['checked'] == 0 and not calls  # no approval: nothing to verify
    Registry(store).approve(resource, 'docs.search.v1', 'search_docs')
    with store.tx() as db:
        db.execute('UPDATE resources SET price_usdc=0.01 WHERE id=?', (rid,))
    assert ContractReverifier(store, front.proxy).run() == {'checked': 0, 'succeeded': 0, 'skipped': 1} and not calls
    assert store.query('SELECT COUNT(*) FROM capability_approvals')[0][0] == 1


def test_an_outdated_approval_is_left_for_review(managed):
    store, front, _, _, rid, calls, remote = managed
    Registry(store).approve(_docs(store, rid, remote), 'docs.search.v1', 'search_docs')
    changed = [{**SPEC, 'description': 'Search documentation pages'}]
    compact = usage.compact_tools(changed)
    store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, None, full_tools=changed)
    assert ContractReverifier(store, front.proxy).run()['checked'] == 0 and not calls


def test_jobs_worker_runs_a_due_round_only_when_idle_and_not_paused(monkeypatch):
    import threading
    from types import SimpleNamespace
    from agent_market import service_host
    stop, rounds = threading.Event(), []
    class Fake:
        def __init__(self, store, proxy):
            self.store, self.proxy = store, proxy
        def due(self):
            return not rounds
        def run(self):
            rounds.append(1)
            stop.set()
            return {'checked': 0, 'succeeded': 0, 'skipped': 0}
    monkeypatch.setattr('agent_market.model_contract_reverify.ContractReverifier', Fake)
    monkeypatch.setattr('agent_market.workspace_platform.platform_for', lambda _front: SimpleNamespace())
    collector = SimpleNamespace(paused=threading.Event())
    app = SimpleNamespace(state=SimpleNamespace(front=SimpleNamespace(store=object(), proxy=object(), book=SimpleNamespace()),
                                                gateway=SimpleNamespace(state=SimpleNamespace(collector=collector))))
    control = SimpleNamespace(claim=lambda: None, heartbeat=lambda *a: None)
    loop = service_host.BackgroundLoop(app, control, 'jobs', stop)
    monkeypatch.setattr(loop, 'heartbeat', lambda: None)
    loop.run()
    loop.pool.shutdown(wait=True)
    assert rounds == [1]


def test_execution_evidence_skipped_by_an_owned_agent_is_recorded(managed):
    store, front, _, _, rid, calls, remote = managed
    Registry(store).approve(_docs(store, rid, remote), 'docs.search.v1', 'search_docs')
    proxy = front.proxy
    class Skipping:
        bookkeeping_skipped = 0
        def applies(self, resource_id):
            return resource_id == rid
        def execute(self, resource, name, arguments, observed):
            return {'ok': True, 'hash_verified': True, 'result': remote.call_result}
        def bookkeep(self, resource_id, result, record_evidence):
            self.bookkeeping_skipped += 1  # contention: the evidence callback is not run
            return False
    proxy._owned_data_dispatch = Skipping()
    assert ContractReverifier(store, proxy).run()['succeeded'] == 1
    projection = Registry(store).projection(store.resource(rid))
    assert projection['connection_readiness']['verified_callable'] and projection['capability_contracts'][0]['verified']


def test_a_recent_contract_result_without_execution_evidence_is_checked_again(managed):
    store, front, _, _, rid, calls, remote = managed
    resource = _docs(store, rid, remote)
    registry = Registry(store)
    registry.approve(resource, 'docs.search.v1', 'search_docs')
    now = time.time()
    registry.record(registry.current(resource), scope='contract', outcome='succeeded', started=now - 2, finished=now - 1,
                    contract_id='docs.search.v1', dataset='explicit-contract-test-v1')
    assert ContractReverifier(store, front.proxy).run()['checked'] == 1


def test_evidence_for_an_older_implementation_is_checked_again(managed, monkeypatch):
    store, front, _, _, rid, calls, remote = managed
    Registry(store).approve(_docs(store, rid, remote), 'docs.search.v1', 'search_docs')
    assert ContractReverifier(store, front.proxy).run()['checked'] == 1
    real = Registry.projection
    def stale(self, resource, **kwargs):
        value = real(self, resource, **kwargs)
        return {**value, 'capability_contracts': [{**item, 'verified': False} for item in value.get('capability_contracts', [])]}
    monkeypatch.setattr(Registry, 'projection', stale)  # e.g. the adapter implementation hash changed
    assert ContractReverifier(store, front.proxy).run()['checked'] == 1
