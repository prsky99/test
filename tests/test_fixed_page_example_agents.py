"""Test page examples follow the background rebuild, connection details included (11-02).

The page opens without any request (UI policy 11-01). Before 11-02 an example whose agent was not
shipped in test.html kept the old snapshot until someone ran scripts.build_public_page_snapshots.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from agent_market.concierge import front as front_module
from agent_market.concierge.pearl_view import current_fixed_content

ROOT = Path(__file__).resolve().parents[1]


def bootstrap(served):
    return json.loads(served.split('id="appBootstrapData" type="application/json">', 1)[1].split('</script>', 1)[0])


def test_new_example_opens_with_agent_from_the_background_rebuild():
    page = (ROOT / 'new/en/test.html').read_text()
    cache = front_module._bootstrap_snapshot_cache
    with cache['lock']:
        saved = cache.get('data'), cache.pop('example_agents', None)
        cache['data'] = {'testbench_examples': [{'id': 'x', 'available': True, 'resource_id': 999999999}]}
    try:
        assert current_fixed_content(page, 'test.html') == page  # no connection details yet: keep shipped
        with cache['lock']:
            cache['example_agents'] = {999999999: {'id': 999999999, 'name': 'New <agent>', 'kind': 'mcp'}}
        served = current_fixed_content(page, 'test.html')
        value = bootstrap(served)
        assert [e['resource_id'] for e in value['testbench_examples']] == [999999999]
        assert value['testbench_agents'] == [{'id': 999999999, 'name': 'New <agent>', 'kind': 'mcp'}]
        assert '<agent>' not in served.split('id="appBootstrapData"', 1)[1].split('</script>', 1)[0]
    finally:
        with cache['lock']:
            cache['data'] = saved[0]
            cache.pop('example_agents', None)
            if saved[1] is not None:
                cache['example_agents'] = saved[1]


def test_example_agents_are_looked_up_only_when_the_set_changes(monkeypatch):
    calls = []

    def detail(store, rid):
        calls.append(rid)
        if rid == 3:
            raise LookupError(rid)
        return {'agent': {'id': rid, 'name': 'A%d' % rid, 'kind': 'mcp', 'hidden_counter': 9}}

    monkeypatch.setattr(front_module, 'get_safe_agent_detail', detail)
    cache = front_module._bootstrap_snapshot_cache
    me = SimpleNamespace(store=None)
    examples = [{'available': True, 'resource_id': 1}, {'available': True, 'resource_id': 2},
                {'available': False, 'resource_id': 5}, {'available': True, 'resource_id': 1}]
    with cache['lock']:
        saved = cache.pop('example_agents', None)
    try:
        agents = front_module.Front._example_agents(me, examples)
        assert agents == {1: {'id': 1, 'name': 'A1', 'kind': 'mcp'}, 2: {'id': 2, 'name': 'A2', 'kind': 'mcp'}}
        with cache['lock']:
            cache['example_agents'] = agents
        assert front_module.Front._example_agents(me, examples) is agents and calls == [1, 2]
        more = examples + [{'available': True, 'resource_id': 3}]
        assert set(front_module.Front._example_agents(me, more)) == {1, 2}  # a failed lookup is skipped
    finally:
        with cache['lock']:
            cache.pop('example_agents', None)
            if saved is not None:
                cache['example_agents'] = saved
