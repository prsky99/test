"""PM F05 (11-14): an eligible necklace runs end to end through the assembled app on all three public surfaces.

No function is replaced: the app wires necklace_surface.RUN itself, members are called through the real
registered-agent path (execution policy, McpProxy) against loopback MCP servers, and run events land next to the
snapshot. Held, stale and no-consent requests make no member call at all. Only environment settings point the app at
temporary folders.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.collector import usage
from agent_market.concierge import necklace_surface
from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.necklaces import limits, model, service

TOOL = {'name': 'lookup', 'description': 'Look up public security advisories',
        'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 200}},
                        'required': ['query'], 'additionalProperties': False},
        'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}


class McpServer:
    """A loopback MCP server that answers tools/call with fixed text and counts the calls."""

    def __init__(self, answer):
        self.calls = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = body.get('method', '')
                if method.startswith('notifications/'):
                    self.send_response(204)
                    self.end_headers()
                    return
                if method == 'initialize':
                    value = {'protocolVersion': body['params']['protocolVersion'], 'capabilities': {'tools': {}},
                             'serverInfo': {'name': 'loopback', 'version': '1'}}
                elif method == 'tools/list':
                    value = {'tools': [TOOL]}
                elif method == 'tools/call':
                    server.calls.append(body['params']['arguments'])
                    value = {'content': [{'type': 'text', 'text': answer}]}
                else:
                    value = {}
                raw = json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': value}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.http.server_address[1]

    def close(self):
        self.http.shutdown()
        self.http.server_close()


class Loopback(httpx.BaseTransport):
    """Test-only routing of https://pN.example to the loopback servers; the SSRF policy itself is unchanged."""

    def __init__(self, servers):
        self.ports = {'p%d.example' % i: s.port for i, s in enumerate(servers)}
        self.network = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        url = request.url.copy_with(scheme='http', host='127.0.0.1', port=self.ports[request.url.host])
        return self.network.handle_request(httpx.Request(request.method, url, headers=request.headers,
                                                         content=request.content, extensions=request.extensions))

    def close(self):
        self.network.close()


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def member(rid, domain):
    return {'kind': 'external', 'resource_id': rid, 'tool': 'lookup', 'registrable_domain': domain, 'upstream': ['src'],
            'read_only_hint': True, 'destructive_hint': False, 'idempotent_hint': True, 'resend_safe': True,
            'state': 'active', 'input_map': {'query': '{{input.q}}'}}


def definition(slug, ids):
    return {'slug': slug, 'version': 1, 'status': 'live', 'name': 'Advisory brief', 'summary': 'Two sources in one answer.',
            'input_schema': {'type': 'object', 'properties': {'q': {'type': 'string', 'minLength': 1, 'maxLength': 120}},
                             'required': ['q'], 'additionalProperties': False},
            'budget_ms': {'total': 5000, 'slot': 4000},
            'slots': [{'slot': 'advisories', 'contract': 'package.advisories.v1', 'required': True, 'fanout': 1,
                       'chain': [member(ids[0], 'a.example'), member(ids[1], 'b.example')]},
                      {'slot': 'exploited', 'contract': 'cve.exploited.v1', 'required': True, 'fanout': 1,
                       'chain': [member(ids[2], 'c.example'), member(ids[3], 'd.example')]}]}


def entry(defn, ids, now, **extra):
    value = {'slug': defn['slug'], 'name': defn['name'], 'summary': defn['summary'], 'version': 1,
             'definition_digest': model.digest(defn), 'status': 'live', 'held_reason': None,
             'gate_passed_at': iso(now - timedelta(days=1)), 'input_schema': defn['input_schema'],
             'pearls': [{'resource_id': ids[0], 'role': 'advisories', 'tool': 'lookup', 'required': True, 'pearl': True,
                         'alternates': [{'resource_id': ids[1], 'tool': 'lookup', 'kind': 'external'}]},
                        {'resource_id': ids[2], 'role': 'exploited', 'tool': 'lookup', 'required': True, 'pearl': True,
                         'alternates': [{'resource_id': ids[3], 'tool': 'lookup', 'kind': 'external'}]}],
             'completion': {'runs': 60, 'completed': 59, 'completed_external_only': 59, 'since': iso(now - timedelta(days=2)),
                            'retested_at': iso(now - timedelta(hours=2))},
             'quality': {'cases_7d': 60, 'success_rate': 0.98, 'best_single_rate': 0.7, 'delta_pp': 28.0,
                         'tested_at': iso(now - timedelta(hours=2))},
             'cost': {'usdc_per_run': 0, 'p50_ms': 900, 'p95_ms': 1800}, 'replaces_templates': [], 'replaced_at': None}
    value.update(extra)
    return value


@pytest.fixture
def site(tmp_path):
    limits.reset()          # counts and cached answers of earlier tests in this process
    servers = [McpServer('GHSA-29mw-wpgm-hmr9 CVE-2021-23337'), McpServer('CVE-2021-23337'),
               McpServer('CVE-2021-23337 is listed in CISA KEV'), McpServer('listed in CISA KEV')]
    store = Store(str(tmp_path / 'site.sqlite3'))
    ids = []
    for i, server in enumerate(servers):
        rid = store.upsert_resource({'key': 'necklace-loopback-%d' % i, 'kind': 'mcp', 'source': 'isolated-test',
                                     'name': 'Advisories %d' % i, 'description': 'Public security advisories',
                                     'category': 'dev_tools', 'url': 'https://p%d.example/mcp' % i, 'price_usdc': 0})
        tools = [TOOL]
        store.record_usage(rid, usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)), {}, None,
                           {'ok': True}, full_tools=tools)
        with store.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy', last_check_at=1 WHERE id=?", (rid,))
        ids.append(rid)
    now = datetime.now(timezone.utc)
    defs = tmp_path / 'definitions'
    defs.mkdir()
    live, held, stale = (definition(slug, ids) for slug in ('advisory-brief', 'held-brief', 'stale-brief'))
    for defn in (live, held, stale):
        (defs / (defn['slug'] + '.json')).write_text(json.dumps(defn))
    data = tmp_path / 'gateway-data' / 'necklaces'
    data.mkdir(parents=True)
    snapshot = {'schema': necklace_surface.SCHEMA, 'generated_at': iso(now), 'events': [], 'necklaces': [
        entry(live, ids, now),
        entry(held, ids, now, status='held', held_reason='completion_low', held_at=iso(now - timedelta(hours=1))),
        entry(stale, ids, now, quality={'cases_7d': 60, 'success_rate': 0.98, 'best_single_rate': 0.7, 'delta_pp': 28.0,
                                        'tested_at': iso(now - timedelta(hours=49))})]}
    (data / 'necklaces.json').write_text(json.dumps(snapshot))
    saved = {k: os.environ.get(k) for k in ('AGENTCON_PROJECT_ROOT', 'NECKLACE_DEFINITIONS_DIR')}
    os.environ['AGENTCON_PROJECT_ROOT'] = str(tmp_path)
    os.environ['NECKLACE_DEFINITIONS_DIR'] = str(defs)
    clear_front_caches()
    front = Front(store, allow_private=True)
    http = httpx.Client(transport=Loopback(servers))
    front.proxy = front.workflows.proxy = McpProxy(store, allow_private=True, http=http, clearinghouse=front.clearinghouse)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        yield client, servers, data
    finally:
        client.close()
        http.close()
        front.book.close()
        for server in servers:
            server.close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        store._db.close()


def calls(servers):
    return sum(len(s.calls) for s in servers)


def events(data):
    return [json.loads(line) for path in sorted((data / 'runs').glob('*.jsonl')) for line in path.read_text().splitlines()]


def mcp(client, name, arguments, headers=None):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
    return client.post('/mcp', json=body, headers=headers or {}).json()['result']


def a2a(client, text):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'message/send',
            'params': {'message': {'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': text}]}}}
    result = client.post('/a2a', json=body).json()['result']
    return result['parts'][0]['text'], result['parts'][1]['data']


def test_one_eligible_necklace_completes_on_web_mcp_and_a2a(site):
    client, servers, data = site
    assert necklace_surface.RUN is service.run_for_surface

    web = client.post('/api/necklaces/advisory-brief/run', json={'q': 'lodash', 'necklace_notice': 'necklace-v1'}).json()
    assert web['cached'] is False
    assert web['ran'] is True and web['ok'] is True, web
    assert web['stages'] == {'advisories': 1, 'exploited': 1}
    assert web['output']['exploited']['kev'] is True

    tool = mcp(client, 'necklace_advisory_brief', {'q': 'minimist'})
    assert tool['isError'] is False and tool['structuredContent']['ok'] is True

    text, reply = a2a(client, 'run necklace advisory-brief {"q": "express"}')
    assert reply['ok'] is True and text.startswith('Ran necklace advisory-brief.')

    assert [len(s.calls) for s in servers] == [3, 0, 3, 0]          # leads answered; alternates never needed
    assert sorted(c['query'] for c in servers[0].calls) == ['express', 'lodash', 'minimist']

    again = mcp(client, 'necklace_advisory_brief', {'q': 'lodash'})  # same input within 10 minutes: cached, no call
    assert again['structuredContent']['ok'] is True and [len(s.calls) for s in servers] == [3, 0, 3, 0]
    assert again['structuredContent']['cached'] is True and again['structuredContent']['ran_at'] == web['ran_at']
    assert 'Saved answer from ' + web['ran_at'] in again['content'][0]['text']
    runs = events(data)
    assert [e['surface'] for e in runs] == ['web', 'mcp', 'a2a', 'mcp']
    assert [bool(e.get('cached')) for e in runs] == [False, False, False, True]
    assert all(e['outcome'] == 'succeeded' and e['origin'] == 'public' for e in runs)
    assert 'lodash' not in json.dumps(runs)                          # body-free events


def test_our_own_checks_are_internal_runs(site):
    client, servers, data = site
    mcp(client, 'necklace_advisory_brief', {'q': 'lodash'}, headers={'X-Agentcon-QA': 'necklace_retest'})
    [run] = events(data)
    assert run['source'] == 'internal' and run['outcome'] == 'succeeded'


def test_held_stale_and_no_consent_make_no_member_call(site):
    client, servers, data = site
    held = mcp(client, 'necklace_held_brief', {'q': 'lodash'})
    assert held['isError'] is True and held['structuredContent']['ran'] is False
    text, reply = a2a(client, 'run necklace held-brief {"q": "lodash"}')
    assert reply['ok'] is False and reply['ran'] is False
    stale = client.post('/api/necklaces/stale-brief/run', json={'q': 'lodash', 'necklace_notice': 'necklace-v1'}).json()
    assert stale['ran'] is False
    no_consent = client.post('/api/necklaces/advisory-brief/run', json={'q': 'lodash'}).json()
    assert no_consent['ok'] is False and no_consent['error_code'] == 'consent_required'
    bad = mcp(client, 'necklace_advisory_brief', {'q': 'lodash', 'extra': 1})
    assert bad['structuredContent']['error_code'] == 'invalid_input'
    assert calls(servers) == 0
    assert not (data / 'runs').exists()


def test_the_page_form_follows_the_same_rules(site):
    """5d25bec9 review (PM 11-15 11:22): the page form checks consent and input on the server, keeps the limits, calls
    nobody when held, stale or refused, and shows only the visitor's own values."""
    client, servers, data = site
    form = {'q': 'lodash', 'necklace_notice': 'necklace-v1'}
    for slug in ('held-brief', 'stale-brief'):
        r = client.post(f'/necklaces/{slug}/run', data=form)
        assert r.status_code == 200 and 'no-store' in r.headers['cache-control']
    r = client.post('/necklaces/advisory-brief/run', data={'q': 'lodash'})               # no consent box
    assert 'Tick the box' in r.text
    r = client.post('/necklaces/advisory-brief/run', data={'q': '', 'necklace_notice': 'necklace-v1'})   # invalid
    assert 'not in the expected form' in r.text
    r = client.post('/necklaces/advisory-brief/run', data={'q': 'x' * 121, 'necklace_notice': 'necklace-v1'})
    assert 'not in the expected form' in r.text
    assert calls(servers) == 0 and not (data / 'runs').exists()
    first = client.post('/necklaces/advisory-brief/run', data={'q': 'alpha-secret-term', 'necklace_notice': 'necklace-v1'})
    assert 'Finished.' in first.text and calls(servers) == 2
    other = client.post('/necklaces/advisory-brief/run', data={'q': 'beta', 'necklace_notice': 'necklace-v1'})
    assert 'alpha-secret-term' not in other.text and 'beta' in other.text           # no one else's input on the page


def test_a_refused_run_says_when_to_come_back_and_is_counted_apart_from_runs(site):
    # PM 11-17 08:5x: both rate_limited answers carry Retry-After (the window's seconds left) and retry_after_s;
    # the run limit keeps HTTP 200 + ok:false; refusals are counted in refusals/, never in runs/.
    client, servers, data = site
    body = {'q': 'lodash', 'necklace_notice': 'necklace-v1'}
    answers = [client.post('/api/necklaces/advisory-brief/run', json=body) for _ in range(limits.PER_CLIENT_PER_MINUTE + 1)]
    refused = answers[-1]
    assert [a.json().get('error_code') for a in answers[:-1]] == [None] * limits.PER_CLIENT_PER_MINUTE
    assert refused.status_code == 200 and refused.json()['ok'] is False and refused.json()['error_code'] == 'rate_limited'
    wait = refused.json()['retry_after_s']
    assert 1 <= wait <= 60 and refused.headers['retry-after'] == str(wait)
    assert len(events(data)) == limits.PER_CLIENT_PER_MINUTE
    lines = [json.loads(line) for path in (data / 'refusals').glob('*.jsonl') for line in path.read_text().splitlines()]
    assert lines and lines[-1]['code'] == 'rate_limited' and lines[-1]['slug'] == 'advisory-brief'
    assert set(lines[-1]) == {'at', 'slug', 'code', 'surface'}          # no client, address or input


def test_the_address_limit_answers_429_with_retry_after(site, monkeypatch):
    client, servers, data = site
    import gc
    from agent_market.concierge.front import Front
    front = [o for o in gc.get_objects() if isinstance(o, Front)][-1]      # the site's Front: only its run limit
    monkeypatch.setattr(front.limit, 'allow', lambda key: False)
    monkeypatch.setattr(front.limit, 'retry_after', lambda key: 17)
    answer = client.post('/api/necklaces/advisory-brief/run', json={'q': 'lodash', 'necklace_notice': 'necklace-v1'})
    assert answer.status_code == 429 and answer.headers['retry-after'] == '17'
    body = answer.json()                     # the public problem document keeps our fields and adds its own
    assert {k: body[k] for k in ('ran', 'error_code', 'retry_after_s')} == {'ran': False, 'error_code': 'rate_limited',
                                                                           'retry_after_s': 17}
    assert calls(servers) == 0
