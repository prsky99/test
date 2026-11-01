"""Owned handlers execute in process across fresh proxies and standalone workers."""

from types import SimpleNamespace

import pytest

from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.owned_data_agents.activation import install, check_sources, MARKER
from agent_market.owned_data_agents.catalog import SPECS
from agent_market.owned_data_agents.english import translator_for
from agent_market.owned_data_agents.verification import wait
from agent_market.workflow_worker import compose_worker
from tests.test_owned_data_agents import engine  # noqa: F401


@pytest.fixture
def local(tmp_path, engine):  # noqa: F811
    core, calls, state = engine
    store = Store(str(tmp_path / "owned-local.sqlite3"))
    resources = install(store, "https://agentconcierge.biz")
    store._owned_data_engine = core
    check_sources(store, core, resources)
    proxy = McpProxy(store)

    def forbidden(*args, **kwargs):
        raise AssertionError("Owned agents must not issue a public-origin MCP request.")

    proxy._client = forbidden
    yield store, proxy, resources, calls
    store._db.close()


@pytest.mark.parametrize("identity", SPECS)
def test_fresh_proxy_never_calls_the_public_mcp_endpoint(local, identity):
    store, proxy, resources, calls = local
    result = proxy.execute(
        resources[identity],
        SPECS[identity]["tool"],
        SPECS[identity]["example"],
        public=True,
    )
    assert result["ok"], result
    assert result["result"]["structuredContent"]["agent"] == identity
    assert not any(request.url.host == "agentconcierge.biz" for request in calls)
    assert proxy._owned_data_dispatch.engine is store._owned_data_engine


def test_standalone_worker_runs_all_three_templates_locally(local):
    store, proxy, _, calls = local
    runtime = compose_worker(store, proxy=proxy)
    templates, _ = store.list_workflows(is_template=1, active_only=True)
    assert len(templates) == 3
    for template in templates:
        result = wait(runtime, runtime.submit(template, public=True, source="public"))
        assert result["status"] == "succeeded", result
        assert (
            sum(
                n["type"] == "agent" and n["status"] == "succeeded"
                for n in result["node_results"]
            )
            == 2
        )
    assert not any(request.url.host == "agentconcierge.biz" for request in calls)


def test_missing_profile_cannot_fall_back_to_remote_execution(local):
    store, proxy, resources, _ = local
    with store.tx() as db:
        db.execute("DELETE FROM meta WHERE key=?", (MARKER,))
    identity = "country-profile"
    result = proxy.execute(
        resources[identity],
        SPECS[identity]["tool"],
        SPECS[identity]["example"],
        public=True,
    )
    assert not result["ok"] and result["error_code"] == "POLICY_DENIED"


def test_changed_owned_identity_cannot_escape_to_a_remote_proxy(local):
    store, proxy, resources, _ = local
    rid = resources["country-profile"]
    with store.tx() as db:
        db.execute(
            "UPDATE resources SET source='other',url='https://remote.example/mcp' WHERE id=?",
            (rid,),
        )
    result = proxy.execute(
        rid, "get_country_profile", {"country_code": "US"}, public=True
    )
    assert not result["ok"] and result["error_code"] == "SCHEMA_CHANGED"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://model.example",
        "http://192.168.1.5:11434",
        "http://localhost.example:11434",
    ],
)
def test_translation_never_runs_on_another_system(endpoint):
    assert translator_for(SimpleNamespace(url=endpoint, model="local-model")) is None


def test_source_request_timeout_fits_inside_the_gateway_budget(engine):  # noqa: F811
    core, calls, _ = engine
    result = core.execute("country-profile", {"country_code": "US"})
    assert result["data"]["country_code"] == "US"
    assert max(calls[-1].extensions["timeout"].values()) <= 4


def test_newer_duplicate_url_cannot_replace_local_examples_or_workflow_nodes(local):
    from agent_market.concierge.testbench_examples import live_examples
    from agent_market.owned_data_agents.catalog import tool_spec
    from agent_market.collector import usage

    store, _, resources, _ = local
    for identity, rid in resources.items():
        source = store.resource(rid)
        duplicate = store.upsert_resource(
            {
                "key": "duplicate:" + identity,
                "kind": "mcp",
                "source": "external-registry",
                "name": source["name"],
                "description": source["description"],
                "url": source["url"],
                "category": "data_utility",
                "price_usdc": 0,
            }
        )
        tools = [tool_spec(identity)]
        compact = usage.compact_tools(tools)
        store.record_usage(
            duplicate,
            compact,
            usage.tools_hash(compact),
            {},
            None,
            None,
            full_tools=tools,
        )
        with store.tx() as db:
            db.execute(
                "UPDATE resources SET health_status='healthy' WHERE id=?", (duplicate,)
            )
        assert duplicate > rid
    assert all(
        row["resource_id"] == resources[row["id"]] for row in live_examples(store)
    )
    templates, _ = store.list_workflows(is_template=1, active_only=True)
    for template in templates:
        assert all(
            node["resource_id"] in resources.values()
            for node in template["nodes"]
            if node["type"] == "agent"
        )


def test_completed_local_read_does_not_wait_for_optional_catalog_writes(local):
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store, proxy, resources, _ = local
    identity = "country-profile"
    rid = resources[identity]

    def execute():
        return proxy.execute(
            rid, SPECS[identity]["tool"], SPECS[identity]["example"], public=True
        )

    assert execute()["ok"]  # Warm the data cache and immutable connection version.
    before = store.resource(rid)["calls_30d"]
    evidence = len(store.query("SELECT id FROM capability_evidence"))
    timeout = store._db.execute("PRAGMA busy_timeout").fetchone()[0]
    held, release = threading.Event(), threading.Event()

    def writer():
        db = sqlite3.connect(store._path, timeout=1)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value=value WHERE key=?", (MARKER,))
            held.set()
            assert release.wait(5)
            db.commit()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer_job = pool.submit(writer)
        assert held.wait(2)
        try:
            result = pool.submit(execute).result(timeout=2)
            assert result["ok"], result
            assert proxy._owned_data_dispatch.bookkeeping_skipped == 1
            assert store.resource(rid)["calls_30d"] == before
            assert len(store.query("SELECT id FROM capability_evidence")) == evidence
            assert store._db.execute("PRAGMA busy_timeout").fetchone()[0] == timeout
        finally:
            release.set()
        writer_job.result(timeout=2)
    assert execute()["ok"]
    assert store.resource(rid)["calls_30d"] == before + 1
    assert len(store.query("SELECT id FROM capability_evidence")) == evidence + 1


def test_optional_bookkeeping_preserves_a_callers_transaction(local):
    store, proxy, resources, _ = local
    identity = "country-profile"
    rid = resources[identity]
    assert proxy.execute(
        rid, SPECS[identity]["tool"], SPECS[identity]["example"], public=True
    )["ok"]
    dispatcher = proxy._owned_data_dispatch
    called = []
    store._db.execute("BEGIN")
    try:
        assert not dispatcher.bookkeep(rid, {"ok": True}, lambda: called.append(1))
        assert store._db.in_transaction
        assert not called
    finally:
        store._db.rollback()


def test_periodic_check_keeps_first_party_execution_evidence_fresh(local):
    from agent_market.capability_registry import Registry
    from agent_market.model_contract_reverify import ContractReverifier
    store, proxy, resources, calls = local
    clock = [__import__('time').time()]
    reverify = ContractReverifier(store, proxy, clock=lambda: clock[0], limit=len(SPECS) + 1)
    report = reverify.run()
    assert report['checked'] == len(SPECS) and report['succeeded'] == len(SPECS)
    for identity, rid in resources.items():
        assert Registry(store).projection(store.resource(rid))['connection_readiness']['verified_callable'], identity
    sent = len(calls)
    assert reverify.run()['checked'] == 0 and len(calls) == sent  # fresh evidence is not re-read within the interval
    assert not any(request.url.host == "agentconcierge.biz" for request in calls)
