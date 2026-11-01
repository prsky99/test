"""Write fixed public page content into new/en/test.html and new/en/workflows.html.

Test examples and published workflows open from these snapshots without any API
call (UI policy 11-01: fixed default content is plain HTML/JSON). Run requests are
still checked by the server, so a stale snapshot can only fail at Run time.

    .venv/bin/python -m scripts.build_public_page_snapshots [--origin https://agentconcierge.biz]
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

PAGES = Path(__file__).resolve().parents[1] / 'new/en'
MARK = re.compile(r'<script id="appBootstrapData" type="application/json">.*?</script>', re.S)
# Only what the Test form renders; counters and report history stay on the server.
AGENT_FIELDS = ('id', 'kind', 'name', 'description', 'url', 'category', 'tools', 'auth_method',
                'eval_grade', 'health_status', 'connection_available', 'connection_readiness')


def fetch(origin, path):
    request = urllib.request.Request(origin.rstrip('/') + path, headers={
        'User-Agent': 'AgentConcierge-TestPageBuild/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return json.load(reply)


def workflows(origin):
    templates = fetch(origin, '/api/workflows/templates')['templates']
    if not templates:
        raise SystemExit('No published workflows; keep the current snapshot.')
    return {'workflow_templates': templates}


def snapshot(origin):
    presets = fetch(origin, '/api/test/presets')
    examples = [e for e in presets['live_examples'] if e.get('available') and e.get('resource_id')]
    if not examples:
        raise SystemExit('No available live examples; keep the current snapshot.')
    agents = []
    for example in examples:
        agent = fetch(origin, '/api/agents/%d' % example['resource_id'])['agent']
        agents.append({k: agent[k] for k in AGENT_FIELDS if k in agent})
    for example in examples:
        example.pop('execution_availability', None)
    return {'testbench_examples': examples, 'testbench_presets': presets.get('presets') or [],
            'testbench_agents': agents}


def embed(html, data):
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    block = '<script id="appBootstrapData" type="application/json">' + text + '</script>'
    if MARK.search(html):
        return MARK.sub(lambda _: block, html, count=1)
    return html.replace('</main>', '</main>' + block, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', default='https://agentconcierge.biz')
    args = parser.parse_args()
    data = snapshot(args.origin)
    page = PAGES / 'test.html'
    page.write_text(embed(page.read_text(), data))
    print(len(data['testbench_examples']), 'examples,', len(data['testbench_agents']), 'agents written')
    data = workflows(args.origin)
    page = PAGES / 'workflows.html'
    page.write_text(embed(page.read_text(), data))
    print(len(data['workflow_templates']), 'workflows written')


if __name__ == '__main__':
    main()
