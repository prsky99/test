"""Fail-closed alias rejection in configuration and immediately before routing."""
# ruff: noqa: F401,F811
import time
import pytest
from agent_market.fallback_independence import require_distinct, IndependenceDenied
from agent_market.capability_registry import Registry
from agent_market.workflow_fallback import RoutingDenied
from tests.test_workflow_fallback import routing, config, activate, run


def resource(rid, url, **extra):
    return {'id': rid, 'name': 'Different agent name ' + str(rid), 'url': url, **extra}


@pytest.mark.parametrize('alternate', [
    'https://PRIMARY.example:443/mcp/', 'https://primary.example/another',
    'http://primary.example:8080/mcp', 'https://primary.example/mcp?agent=other',
    'https://primary.example./mcp',
])
def test_same_address_or_host_never_becomes_an_alternative(alternate):
    with pytest.raises(IndependenceDenied):
        require_distinct(resource(1, 'https://primary.example/mcp'), resource(2, alternate))


def test_public_different_hosts_are_only_a_negative_guard_not_approval():
    assert require_distinct(resource(1, 'https://primary.example/mcp'), resource(2, 'https://alternate.example/mcp'))


@pytest.mark.parametrize('url', ['https://localhost/mcp', 'https://user:password@public.example/mcp', 'invalid'])
def test_invalid_endpoint_cannot_gain_independence(url):
    with pytest.raises(IndependenceDenied):
        require_distinct(resource(1, 'https://primary.example/mcp'), resource(2, url))


def test_known_shared_crossref_cannot_be_hidden_by_renaming_catalog_metadata():
    a = resource(1, 'https://agentconcierge.biz/api/owned-data-agents/research-papers/mcp', source='renamed')
    b = resource(2, 'https://papers.openkrill.app/mcp')
    with pytest.raises(IndependenceDenied, match='dependency'):
        require_distinct(a, b, 'search_research_papers', 'search_papers')


def test_configure_rechecks_real_registered_address(routing):
    rt, wf, ids, *_ = routing
    alt = ids[1]
    with rt.store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?', ('https://primary.example/alias', alt))
    reg = Registry(rt.store)
    version = reg.current(alt)
    reg.approve(rt.store.resource(alt), 'docs.search.v1', 'search_docs')
    now = time.time()
    reg.record(version, scope='execution', outcome='succeeded', started=now, finished=now)
    reg.record(version, scope='contract', outcome='succeeded', started=now, finished=now,
               contract_id='docs.search.v1')
    with pytest.raises(RoutingDenied, match='host'):
        config(rt, wf, ids)
    assert rt.fallback.inspect(wf['id'])['policy'] is None


def test_legacy_signed_policy_is_blocked_at_runtime_even_when_pin_was_approved(routing, monkeypatch):
    activate(routing, monkeypatch)
    rt, wf, ids, calls, modes, *_ = routing
    original = rt.store.resource
    # A legacy signed pair with an aliased physical destination cannot become
    # eligible merely through a stale pin cache. The live address guard wins.
    def alias(rid):
        value = original(rid)
        if rid == ids[1]: value = {**value, 'url': 'https://primary.example/alias'}
        return value
    pinned = {rid: rt.fallback.pin(rid, 'docs.search.v1') for rid in ids[:2]}
    monkeypatch.setattr(rt.fallback, 'pin', lambda rid, contract, **kwargs: pinned[rid])
    monkeypatch.setattr(rt.store, 'resource', alias)
    modes['primary.example'] = 'error'
    result = run(rt, wf)
    assert result['status'] == 'failed'
    assert 'alternate.example' not in calls


@pytest.mark.parametrize('first,second', [
    ({'registry_name':'io.github.same/service-a'}, {'registry_name':'io.github.same/service-b'}),
    ({'repository':{'url':'https://github.com/same/one'}}, {'repository':{'url':'https://github.com/same/two'}}),
    ({'website':'https://operator.example'}, {'website':'https://www.operator.example/'}),
    ({'remotes':[{'url':'https://alternate.example/mcp'}]}, {}),
])
def test_declared_common_service_or_publisher_is_conservatively_excluded(first,second):
    with pytest.raises(IndependenceDenied, match='dependency'):
        require_distinct(resource(1,'https://primary.example/mcp',details=first),
                         resource(2,'https://alternate.example/mcp',details=second))


def test_malformed_dependency_metadata_cannot_silently_erase_known_dependencies():
    with pytest.raises(IndependenceDenied, match='metadata'):
        require_distinct(resource(1,'https://primary.example/mcp',details='invalid'),
                         resource(2,'https://alternate.example/mcp'))
