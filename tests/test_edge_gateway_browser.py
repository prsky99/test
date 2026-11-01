"""Browser SDK fallback and private transport boundaries with no live Providers."""
from urllib.parse import urlsplit

import pytest

from tests.test_edge_gateway import edge, ORIGIN
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser


@pytest.fixture
def edge_page(browser, edge):
    context = browser.new_context()
    page = context.new_page()
    seen, external, errors = [], [], []
    mode = {'value': 'origin'}
    def serve(route):
        req = route.request; u = urlsplit(req.url)
        if u.hostname != 'agentconcierge.biz':
            external.append(req.url); route.abort(); return
        seen.append((req.method, u.path))
        if u.path == '/__edge-fixture':
            route.fulfill(body='<div id="output"></div><script src="/sdk/agentconcierge-edge-v1.js"></script>',
                headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'"})
            return
        if u.path.startswith('/api/edge-gateway/v1/runs/') and mode['value'] == 'before-claim':
            route.fulfill(status=503, body='{"error_code":"UNAVAILABLE"}', headers={'Content-Type': 'application/json'})
            return
        if u.path.startswith('/api/edge-gateway/v1/runs/') and mode['value'] == 'after-claim':
            import json
            run_id = u.path.split('/')[5]
            token = req.headers['authorization'][7:]
            edge.service.claim(token, ORIGIN, run_id, json.loads(req.post_data), 'worker')
            route.abort(); return
        if u.path.startswith('/api/edge-gateway/v1/runs/') and mode['value'].startswith('normalized-json'):
            import json
            run_id = u.path.split('/')[5]
            binding = edge.service.claim(req.headers['authorization'][7:], ORIGIN, run_id, json.loads(req.post_data), 'worker')
            failed = mode['value'] == 'normalized-json-error'
            state, code = ('failed', 'PROVIDER_METHOD_UNSUPPORTED') if failed else ('succeeded', None)
            edge.service.finish(run_id, binding['attempt_id'], state, outcome_code=code)
            delta = '' if failed else 'event: delta\ndata: ' + json.dumps({'text': '<img src=x onerror="window.injected=true"> Ready'}) + '\n\n'
            route.fulfill(body=delta + 'event: result\ndata: ' + json.dumps({'state': state, 'error_code': code, 'output': None}) + '\n\n',
                          headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'private, no-store'})
            return
        response = edge.client.request(req.method, u.path, content=req.post_data,
            headers={k: v for k, v in req.headers.items() if k in ('content-type', 'authorization', 'origin', 'x-visitor-token')})
        route.fulfill(status=response.status_code, body=response.content,
            headers={k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(ORIGIN + '/__edge-fixture')
    yield page, seen, external, errors, mode
    context.close()


def run(page, edge, idempotency):
    return page.evaluate('''async ({token, rid, idempotency}) => {
      const client = AgentConciergeEdge.createClient({visitorToken: token});
      const handle = await client.prepare({resourceId: rid, message: 'What is the weather in Tokyo?',
        idempotencyKey: idempotency, runAuthority: true, sharingAuthority: true});
      const result = await client.run(handle, {onDelta: text => document.getElementById('output').append(document.createTextNode(text))});
      const parts = result.output?.parts || [];
      document.getElementById('output').textContent = parts.map(p => p.text || '').join('');
      return {state: result.state, output: document.getElementById('output').textContent};
    }''', {'token': edge.token, 'rid': edge.rid, 'idempotency': idempotency})


def test_free_limit_still_tries_edge_before_origin_under_real_browser_csp(edge_page, edge):
    page, seen, external, errors, mode = edge_page
    mode['value']='before-claim'
    edge.service.observe(100000, edge.clock[0], healthy=False)
    result = run(page, edge, 'browser-origin-01')
    assert result['state'] == 'succeeded'
    assert edge.endpoint not in result['output'] and 'https://news.example/article' in result['output']
    assert any('/api/origin-gateway/' in path for _, path in seen)
    attempts=[path for _,path in seen if '/api/edge-gateway/v1/runs/' in path or '/api/origin-gateway/v1/runs/' in path]
    assert '/api/edge-gateway/' in attempts[0] and '/api/origin-gateway/' in attempts[1]
    assert not external and not errors and len(edge.calls) == 1


def test_sdk_confirms_prepared_before_one_explicit_origin_attempt(edge_page, edge):
    page, seen, external, errors, mode = edge_page
    mode['value'] = 'before-claim'
    result = run(page, edge, 'browser-safe-fallback')
    assert result['state'] == 'succeeded'
    assert sum('/api/edge-gateway/v1/runs/' in p for _, p in seen) == 1
    assert sum('/api/origin-gateway/v1/runs/' in p for _, p in seen) == 1
    assert len(edge.calls) == 1 and not external and not errors


def test_sdk_does_not_rerun_an_uncertain_claim_on_origin(edge_page, edge):
    page, seen, external, errors, mode = edge_page
    mode['value'] = 'after-claim'
    result = run(page, edge, 'browser-unknown-attempt')
    assert result['state'] == 'dispatch_reserved'
    assert not any('/api/origin-gateway/' in path for _, path in seen)
    assert not edge.calls and not external and not errors


@pytest.mark.parametrize('failure', [False, True])
def test_sdk_consumes_normalized_json_results_and_errors_without_redispatch(edge_page, edge, failure):
    page, seen, external, errors, mode = edge_page
    mode['value'] = 'normalized-json-error' if failure else 'normalized-json'
    result = run(page, edge, 'browser-json-' + str(failure))
    assert result['state'] == ('failed' if failure else 'succeeded')
    if not failure:
        assert '<img' in result['output'] and page.locator('#output img').count() == 0
        assert page.evaluate('window.injected === undefined')
    assert not any('/api/origin-gateway/' in path for _, path in seen)
    assert not edge.calls and not external and not errors


def test_sdk_rejects_provider_url_in_a_tampered_grant(edge_page, edge):
    page, seen, external, errors, _ = edge_page
    page.route('**/api/gateway-execution/v1/runs', lambda route: route.fulfill(
        json={'run_id': 'er_' + 'a' * 32, 'stream_path': 'https://provider.example/api', 'access_token': 'forged'}))
    result = page.evaluate('''async token => {
      try {
        const client = AgentConciergeEdge.createClient({visitorToken: token});
        await client.prepare({resourceId: 1, message: 'Weather?', idempotencyKey: 'tampered-grant', runAuthority: true, sharingAuthority: true});
        return 'unexpected';
      } catch { return 'rejected'; }
    }''', edge.token)
    assert result == 'rejected' and not external and not errors and not edge.calls
