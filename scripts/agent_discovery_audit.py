"""Bounded discovery-only interoperability checks; never execute or pay."""
import argparse
import json
import math
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx
from jsonschema import Draft202012Validator, SchemaError


class Audit:
    def __init__(self, client):
        self.client, self.token, self.results, self.timings = client, None, [], []

    def record(self, name, ok, *, optional=False, **detail):
        self.results.append({'scenario': name, 'status': 'PASS' if ok else 'WARN' if optional else 'FAIL', **detail})

    def request(self, method, path, **kwargs):
        headers = {'X-Visitor-Token': self.token} if self.token else {}
        headers.update(kwargs.pop('headers', {}))
        start = time.monotonic()
        response = self.client.request(method, path, headers=headers, **kwargs)
        self.timings.append(time.monotonic() - start)
        return response

    def rpc(self, method, params=None):
        return self.request('POST', '/mcp', json={'jsonrpc': '2.0', 'id': 1,
            'method': method, 'params': params or {}})

    def documents(self):
        paths = ['/robots.txt', '/llms.txt', '/llms-full.txt', '/sitemap.xml',
            '/.well-known/agent-card.json', '/.well-known/mcp.json',
            '/.well-known/agent-entry.json', '/skill.md']
        for path in paths:
            get, head = self.request('GET', path), self.request('HEAD', path)
            self.record('documents:head:' + path, get.status_code == head.status_code == 200 and not head.content,
                get=get.status_code, head=head.status_code)
        sitemap = self.request('GET', '/sitemap.xml')
        if sitemap.status_code != 200:
            self.record('documents:sitemap', False, http=sitemap.status_code)
            return
        # Follow only local category paths, even if the XML advertises another host.
        root = ElementTree.fromstring(sitemap.content)
        paths = sorted({urlsplit(loc.text or '').path for loc in root.iter(
            '{http://www.sitemaps.org/schemas/sitemap/0.9}loc') if loc.text and '/agents/category/' in loc.text})
        for path in [p for p in paths if re.fullmatch(r'/agents/category/[a-z_]+', p)][:30]:
            response = self.request('GET', path)
            self.record('documents:category:' + path, response.status_code == 200, http=response.status_code)

    def mcp(self):
        response = self.rpc('initialize', {'protocolVersion': '2025-11-25',
            'capabilities': {}, 'clientInfo': {'name': 'DiscoveryOnlyQA', 'version': '1'}})
        value = response.json().get('result', {})
        self.record('mcp:initialize', value.get('protocolVersion') == '2025-11-25', http=response.status_code)
        response = self.rpc('tools/list')
        tools = response.json().get('result', {}).get('tools', [])
        self.record('mcp:tools', bool(tools))
        for tool in tools:
            raw_annotations = tool.get('annotations', {})
            annotations = raw_annotations if isinstance(raw_annotations, dict) else {}
            keys = ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint')
            valid_types = isinstance(raw_annotations, dict) and all(type(v) is bool for k,v in annotations.items() if k in keys)
            self.record('mcp:hints:' + tool['name'], valid_types and all(k in annotations for k in keys),
                optional=valid_types)
            try:
                Draft202012Validator.check_schema(tool['outputSchema'])
                valid = True
            except (KeyError, ValueError, SchemaError):
                valid = False
            self.record('mcp:output-schema:' + tool['name'], valid, optional='outputSchema' not in tool)
        # No tools/call for call, adapt_rest, report, credit, or subscriptions.
        self.recommend('mcp')
        origin = str(self.client.base_url).rstrip('/')
        response = self.request('OPTIONS', '/mcp', headers={'Origin': origin,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Content-Type, X-Visitor-Token'})
        self.record('mcp:browser-preflight', response.status_code == 204 and
            response.headers.get('access-control-allow-origin') == origin, http=response.status_code)
        # Any page may use read-only tools anonymously; execution stays with trusted origins.
        response = self.request('POST', '/mcp', headers={'Origin': 'https://untrusted-agent.invalid'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'call', 'arguments': {}}})
        self.record('mcp:origin-denial', response.status_code == 403 and
            response.headers.get('access-control-allow-origin') == '*' and
            'access-control-allow-credentials' not in response.headers, http=response.status_code)
        self.record('mcp:unsupported-sse', self.request('GET', '/mcp').status_code == 405)

    def recommend(self, protocol, *, follow=True):
        task = 'weather forecast for Seoul'
        if protocol == 'rest':
            response = self.request('POST', '/chat', json={'message': task})
            result = response.json()
            payload = result.get('data', {})
            self.token = result.get('visitor', {}).get('token') or self.token
        elif protocol == 'mcp':
            # `search` is a read-only lookup with no visitor; a follow-up needs `chat`, which saves the task.
            tool, arguments = ('chat', {'message': task}) if follow else ('search', {'task': task})
            response = self.rpc('tools/call', {'name': tool, 'arguments': arguments})
            payload = response.json().get('result', {}).get('structuredContent', {})
        else:
            response = self.request('POST', '/a2a', json={'jsonrpc': '2.0', 'id': 1,
                'method': 'message/send', 'params': {'message': {'role': 'user', 'messageId': 'discovery-only-qa',
                    'parts': [{'kind': 'text', 'text': task}]}}})
            result = response.json().get('result', {})
            payload = next((p['data'] for p in result.get('parts', []) if isinstance(p.get('data'), dict)), {})
        self.token = (payload.get('visitor') or {}).get('token') or self.token
        items = payload.get('recommendations', [])
        from agent_market.concierge.task_capability import matches
        relevant = all(any(matches(task, tool, item.get('kind'), item) for tool in item.get('tools_schema', [])) for item in items)
        self.record(protocol + ':seoul-weather', 0 < len(items) <= 3 and relevant,
            http=response.status_code, candidate_ids=[item['id'] for item in items], seconds=round(self.timings[-1], 3))
        if follow and items:
            if protocol == 'a2a':
                context = result.get('contextId')
                response = self.request('POST', '/a2a', json={'jsonrpc': '2.0', 'id': 2, 'method': 'message/send',
                    'params': {'message': {'role': 'user', 'messageId': 'discovery-follow-qa', 'contextId': context,
                        'parts': [{'kind': 'text', 'text': 'details 1'}]}}})
                later = next((p['data'] for p in response.json().get('result', {}).get('parts', []) if 'data' in p), {})
            else:
                response = self.request('POST', '/chat', json={'message': 'details 1'})
                later = response.json().get('data', {})
            selected = later.get('recommendations', [])
            self.record(protocol + ':follow-details', bool(selected) and selected[0]['id'] == items[0]['id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='https://agentconcierge.biz')
    parser.add_argument('--only', default='documents,mcp,a2a,rest')
    parser.add_argument('--benchmark', type=int, default=0, help='Additional sequential searches, at most 16; no execution.')
    parser.add_argument('--out', default='reports/agent-scenarios-latest.json')
    parser.add_argument('--list-scenarios', action='store_true', help='List the 76-scenario plan without network access; not all cases run in the live smoke test.')
    args = parser.parse_args()
    if args.list_scenarios:
        from scripts.agent_scenario_catalog import scenarios
        print(json.dumps(scenarios(), indent=2))
        return 0
    groups = [v.strip() for v in args.only.split(',')]
    if set(groups) - {'documents', 'mcp', 'a2a', 'rest'} or not 0 <= args.benchmark <= 16:
        parser.error('Choose documented groups and a benchmark between 0 and 16.')
    base = urlsplit(args.base)
    if (base.scheme not in ('https', 'http') or not base.hostname or base.username or base.password
            or base.path not in ('', '/') or base.query or base.fragment):
        parser.error('Use an origin without credentials, query, fragment, or path.')
    with httpx.Client(base_url=args.base, timeout=45, follow_redirects=False,
            headers={'User-Agent': 'AgentConcierge-DiscoveryOnlyQA/1.0'}) as client:
        audit = Audit(client)
        for group in groups:
            try:
                audit.documents() if group == 'documents' else audit.mcp() if group == 'mcp' else audit.recommend(group)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                audit.record(group + ':transport', False, error_type=type(exc).__name__)
        for _ in range(args.benchmark):
            audit.recommend('mcp', follow=False)
    timings = sorted(audit.timings)
    report = {'scope': 'Discovery and isolated visitor memory only; no provider execution, payment, feedback, or notifications.',
        'results': audit.results, 'counts': {s: sum(r['status'] == s for r in audit.results) for s in ('PASS', 'WARN', 'FAIL')},
        'http_requests': len(timings), 'http_seconds': {'sum': round(sum(timings), 3),
            'p95': round(timings[max(0, math.ceil(len(timings) * .95) - 1)], 3) if timings else None}}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'counts': report['counts'], 'http_requests': len(timings), 'report': str(output)}))
    return int(bool(report['counts']['FAIL']))


if __name__ == '__main__':
    raise SystemExit(main())
