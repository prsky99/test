"""WebMCP tools in panels-bootstrap.js: registered only when the browser offers navigator.modelContext (11-04)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'new' / 'en' / 'assets' / 'panels-bootstrap.js'
HARNESS = r'''
const ctx = {registered: [], registerTool(t) { this.registered.push(t) }};
Object.defineProperty(globalThis, 'navigator', {value: {modelContext: ctx}, configurable: true, writable: true});
globalThis.document = {querySelectorAll: () => []};
const calls = [];
globalThis.fetch = async (path, init) => { calls.push([path, init && init.method, init && init.body]);
  return {ok: true, json: async () => ({total: 1, items: [{id: 7, name: 'W', kind: 'mcp', health_status: 'healthy'}]})}; };
eval(require('fs').readFileSync(process.argv[1], 'utf8'));
(async () => {
  const [search, recommend] = ctx.registered;
  const found = JSON.parse((await search.execute({query: 'weather', protocol: 'mcp', limit: 99})).content[0].text);
  await recommend.execute({task: 'weather forecast', protocol: 'nope'});
  navigator.modelContext = undefined; eval(require('fs').readFileSync(process.argv[1], 'utf8'));
  console.log(JSON.stringify({names: ctx.registered.map(t => t.name), readOnly: ctx.registered.map(t => t.annotations.readOnlyHint), found, calls}));
})();
'''


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_two_read_only_tools_call_public_read_endpoints():
    out = json.loads(subprocess.run(['node', '-e', HARNESS, str(SCRIPT)], capture_output=True, text=True, check=True).stdout)
    assert out['names'] == ['search_agent_catalog', 'recommend_agents_for_task'] and out['readOnly'] == [True, True]
    assert out['found']['items'][0] == {'id': 7, 'name': 'W', 'protocol': 'mcp', 'health': 'healthy'}
    (search_path, _, _), (discover_path, method, body) = out['calls']
    assert search_path.startswith('/api/explore?') and 'limit=20' in search_path and 'kind=mcp' in search_path
    assert discover_path == '/api/agent/v1/discover' and method == 'POST' and json.loads(body) == {'task': 'weather forecast'}
