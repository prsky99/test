"""Third QA round: follow-up ordinals, phrase typo suggestions, card names, filters, rate-limit wait."""
import re
from pathlib import Path

from agent_market.broker.server import RateLimiter
from agent_market.concierge.chat_guidance import ordinal
from agent_market.concierge.explore_search import suggestions
from tests.test_fast_single_recommendation import catalog  # noqa: F401

HTML = Path(__file__).resolve().parents[1].joinpath('extracted_html.txt').read_text(encoding='utf-8')


def test_ordinal_follow_ups_inside_sentences():
    assert ordinal('the second one') == 2
    assert ordinal('Tell me more about the second one') == 2
    assert ordinal('How do I connect to the second one?') == 2
    assert ordinal('Show me the third') == 3 and ordinal('option 1') == 1 and ordinal('2nd') == 2
    assert ordinal('두 번째 에이전트 자세히') == 2
    for task in ('Find the first weather API', 'weather in 2 cities', 'second-hand car market data'):
        assert ordinal(task) is None


def test_phrase_typos_get_one_explicit_suggestion():
    assert suggestions('github isue') == ['github issue']
    assert suggestions('transalte text') == ['translate text']
    assert suggestions('MCP wether') == ['MCP weather']
    assert suggestions('weather forecast') == []
    assert suggestions('<b>isue</b>') == []


def test_rate_limiter_reports_the_real_wait():
    limiter = RateLimiter(2, 60)
    assert limiter.allow('ip') and limiter.allow('ip') and not limiter.allow('ip')
    assert 1 <= limiter.retry_after('ip') <= 60
    assert limiter.retry_after('other') == 1


def test_frontend_keeps_names_filters_and_wait_time():
    assert 'CHAT_PROMOTION_ALL' in HTML and 'drop price or billing fragments' in HTML
    from pathlib import Path
    runtime = Path('new/en/assets/operating.js').read_text()
    handlers = runtime[runtime.index('let exploreFilterTimer'):runtime.index('const xLoadMoreBtn')]
    assert handlers.count('addEventListener("change"') == 1 and 'click' not in handlers
    assert 'retryAfter' in HTML and 'Your question is kept; try again in' in HTML


def test_registry_name_alone_gets_registry_guidance():
    from agent_market.concierge.hybrid_explore import ERC8004_QUERY
    import re as _re
    pattern = (r'(?:(?:find|show|list|search|browse|give)\s+(?:me\s+)?(?:the\s+|all\s+)?)?(?:'
               + ERC8004_QUERY.pattern + r')\s*[?.!]*')
    for task in ('8004', 'Find ERC-8004 agents', 'show me erc8004 registry?'):
        assert _re.fullmatch(pattern, task, _re.I)
    assert not _re.fullmatch(pattern, 'ERC-8004 agents for token swaps', _re.I)
    source = Path(__file__).resolve().parents[1].joinpath('agent_market/concierge/fast_chat.py').read_text()
    assert 'ERC-8004 is an on-chain agent registry, not a task.' in source


def test_protocol_version_headers_and_empty_parts_are_rejected(catalog):
    store, _, client, _, _ = catalog
    ping = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
    bad = client.post('/mcp', json=ping, headers={'MCP-Protocol-Version': '1999-01-01'})
    assert bad.status_code == 400 and bad.json()['error']['code'] == -32600
    assert client.post('/mcp', json=ping, headers={'MCP-Protocol-Version': '2025-11-25'}).status_code == 200
    message = {'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': 'weather forecast'}]}
    send = {'jsonrpc': '2.0', 'id': 2, 'method': 'message/send', 'params': {'message': message}}
    assert client.post('/a2a', json=send, headers={'A2A-Version': '9.9'}).json()['error']['code'] == -32009
    empty = {**send, 'params': {'message': {**message, 'parts': []}}}
    assert client.post('/a2a', json=empty).json()['error']['code'] == -32602
    assert store.query('SELECT COUNT(*) FROM agent_visitors')[0][0] == 0


def test_public_catalog_reads_allow_any_origin_without_credentials(catalog):
    _, _, client, _, _ = catalog
    preflight = {'Origin': 'https://any-agent.example', 'Access-Control-Request-Method': 'GET'}
    allowed = client.options('/api/explore', headers=preflight)
    assert allowed.status_code == 204 and allowed.headers['access-control-allow-origin'] == '*'
    assert 'access-control-allow-credentials' not in allowed.headers
    read = client.get('/api/explore?limit=1', headers={'Origin': 'https://any-agent.example'})
    assert read.headers['access-control-allow-origin'] == '*'
    post = client.options('/api/explore', headers={**preflight, 'Access-Control-Request-Method': 'POST'})
    assert post.status_code == 403 and 'access-control-allow-origin' not in post.headers
    for path in ('/api/customer-organizations', '/admin'):
        assert client.options(path, headers=preflight).headers.get('access-control-allow-origin') != '*'


def test_llms_documents_use_the_dated_daily_snapshot():
    from agent_market.concierge.front import llms_txt, llms_full_txt
    daily = {'day': '2026-10-28', 'cataloged': 187757, 'reachable': 183167, 'with_status_check': 187548,
             'a2a': 1000, 'mcp': 2000, 'x402': 184757}
    counts = {'a2a': 1, 'mcp': 2, 'x402': 3}
    for render in (llms_txt, llms_full_txt):
        text = render('https://agentconcierge.biz', counts, daily)
        assert 'Catalog snapshot 2026-10-28 KST: 187,757 agents cataloged, 183,167 reachable' in text
        assert 'temporarily unavailable' in render('https://agentconcierge.biz', counts, None)


def test_adapt_rest_names_blocked_internal_addresses(catalog):
    _, front, client, _, _ = catalog
    if front.proxy.allow_private:
        import pytest
        pytest.skip('fixture allows private destinations')
    for url in ('http://127.0.0.1/openapi.json', 'http://169.254.169.254/openapi.json'):
        reply = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'adapt_rest', 'arguments': {'spec_url': url}}}).json()
        assert reply['error'] == {'code': -32602, 'message': 'Private or internal addresses are not allowed.'}


def test_attached_payment_proof_gets_a_reason_and_is_never_processed(catalog):
    import base64 as b64
    import json as js
    _, front, client, add, _ = catalog
    rid = add('Reason probe', kind='x402', price=100)
    front.security.allow_probe = lambda *a, **kw: True
    cases = {'not-base64!!': 'invalid_payload',
             b64.b64encode(js.dumps({'x402Version': 9}).encode()).decode(): 'invalid_x402_version',
             b64.b64encode(js.dumps({'x402Version': 2, 'network': 'eip155:1', 'payload': {}}).encode()).decode(): 'invalid_network'}
    for proof, reason in cases.items():
        response = client.get(f'/api/gateway/x402/{rid}', headers={'PAYMENT-SIGNATURE': proof})
        body = response.json()
        assert response.status_code == 501 and body['payment_processed'] is False
        assert body['reason'] == reason and proof not in response.text


def test_requirements_never_invent_a_recipient_or_amount():
    from agent_market.concierge.payment_validator import payment_requirements_for
    assert payment_requirements_for({'id': 7})['accepts'] == []
    terms = payment_requirements_for({'id': 7, 'price_usdc': 100, 'pay_to': '0x' + 'a' * 40})['accepts'][0]
    assert terms['amount'] == '100' and terms['payTo'] == '0x' + 'a' * 40


def test_chat_searches_a_corrected_spelling_and_says_so(catalog):
    from agent_market.concierge.explore_search import corrected_task
    assert corrected_task('github isue search') == 'github issue search'
    assert corrected_task('tissue sample analysis') is None and corrected_task('weather forecast') is None
    _, _, client, add, _ = catalog
    add('Forecast Service')
    reply = client.post('/chat', json={'message': 'forcasst for Seoul'}).json()
    assert reply['reply'].startswith('Searched for "forecast for Seoul".')


def test_static_assets_are_cacheable_by_content_and_pages_stay_private(catalog):
    import re as _re
    _, _, client, _, _ = catalog
    page = client.get('/new/en/explore.html')
    assert page.headers['cache-control'] == 'public, max-age=0, s-maxage=300, stale-while-revalidate=600'  # 11-11 PM decision A: same bytes for everyone, edge 60 s
    # 11-11: pages load operating.js inside one content-addressed bundle; a single file keeps its own pinned URL.
    bundle = _re.search(r'src="(/new/en/assets/bundle\.js\?f=[^"]*operating[^"]*&amp;v=[0-9a-f]{16})"', page.text)
    assert bundle and client.get(bundle[1].replace('&amp;', '&')).headers['cache-control'] == 'public, max-age=31536000, immutable'
    from pathlib import Path as _Path
    from agent_market.concierge.pearl_view import asset_version
    refs = {'operating.js': asset_version(_Path('new/en/assets/operating.js').read_bytes())}
    pinned = client.get('/new/en/assets/operating.js?v=' + refs['operating.js'])
    assert pinned.headers['cache-control'] == 'public, max-age=31536000, immutable'
    plain = client.get('/new/en/assets/operating.js')
    assert plain.headers['cache-control'].startswith('public, max-age=300')
    assert client.get('/new/en/assets/operating.js', headers={'If-None-Match': plain.headers['etag']}).status_code == 304
    stale = client.get('/new/en/assets/operating.js?v=0000000000000000')
    assert 'immutable' not in stale.headers['cache-control']
    assert client.get('/api/explore?limit=1').headers['cache-control'] != 'public, max-age=31536000, immutable'


def test_static_assets_do_not_count_toward_the_read_limit(catalog):
    _, front, client, _, _ = catalog
    reads = []
    front.security.allow_read = lambda ip, *a, **kw: reads.append(ip) or True
    for _ in range(5):
        client.get('/new/en/assets/styles.css')
    assert reads == []
    client.get('/api/explore?limit=1')
    assert len(reads) == 1


def test_rest_errors_are_readable_and_declared_json_must_parse(catalog):
    _, _, client, _, _ = catalog
    bad = client.get('/api/explore?limit=1000')
    body = bad.json()
    assert bad.status_code == 422 and bad.headers['content-type'].startswith('application/problem+json')
    assert body['field'] == 'limit' and body['error_code'] == 'INVALID_PARAMETER' and 'loc' not in bad.text
    broken = client.post('/chat', content='{"message": ', headers={'Content-Type': 'application/json'})
    assert broken.status_code == 400 and 'not valid JSON' in broken.text
    assert client.post('/chat', content='weather forecast', headers={'Content-Type': 'text/plain'}).status_code == 200
    assert client.get('/.well-known/mcp/server.json').json() == client.get('/.well-known/mcp.json').json()


def test_public_reads_publish_rate_limit_headers(catalog):
    _, _, client, _, _ = catalog
    headers = client.get('/api/agents/999999').headers
    assert headers['ratelimit-policy'].startswith('"read";q=')  # remaining is shown only when exact


def test_alternatives_to_a_listed_agent_recommend_other_agents(catalog):
    _, _, client, add, _ = catalog
    for n in range(5):
        add(f'Forecast Service {n}', description='Weather forecast API')
    first = client.post('/chat', json={'message': 'weather forecast'}).json()
    token = first['visitor']['token']
    shown = {item['id'] for item in first['data']['recommendations']}
    other = client.post('/chat', json={'message': 'Show me alternatives to the first one'},
                        headers={'X-Visitor-Token': token}).json()
    ids = {item['id'] for item in other['data'].get('recommendations', [])}
    assert other['intent'] == 'alternatives' and ids and not ids & shown


def test_public_status_json_has_only_public_facts(catalog):
    _, _, client, _, _ = catalog
    value = client.get('/status.json').json()
    assert value['status'] == 'unknown' and value['availability']['observation_count'] == 0
    assert value['availability']['availability_percent'] is None and value['limits_per_minute']['read'] == 120
    assert set(value) == {'service', 'status', 'checked_at', 'catalog_snapshot', 'interfaces', 'limits_per_minute', 'availability', 'recent_incidents'}
    assert '/status.json' in client.get('/llms.txt').text


def test_explore_pages_by_cursor(catalog):
    _, _, client, add, _ = catalog
    for n in range(6):
        add(f'Forecast Cursor {n}', description='Weather forecast API')
    first = client.get('/api/explore?q=weather&limit=2').json()
    assert first['next_cursor'] == 'o2'
    second = client.get('/api/explore?q=weather&limit=2&cursor=' + first['next_cursor']).json()
    assert second['offset'] == 2 and not {i['id'] for i in first['items']} & {i['id'] for i in second['items']}
    assert client.get('/api/explore?cursor=zz').status_code == 422


def test_problem_details_are_negotiated_without_changing_the_default(catalog):
    _, _, client, _, _ = catalog
    default = client.post('/chat', content='{"message": ', headers={'Content-Type': 'application/json'})
    assert default.status_code == 400 and default.json()['status'] == 400 and 'detail' in default.json()
    assert default.headers['content-type'].startswith('application/problem+json')
    asked = client.post('/chat', content='{"message": ', headers={'Content-Type': 'application/json',
                                                                  'Accept': 'application/problem+json'})
    body = asked.json()
    assert asked.headers['content-type'].startswith('application/problem+json')
    assert body['status'] == 400 and body['title'] == 'Bad request' and 'not valid JSON' in body['detail']


def test_later_pages_never_repeat_or_skip_served_listings():
    from agent_market.concierge import front as fr
    fr._page_snapshots.values.clear()
    key = ('data', None, None, False, False, False)
    first = {'items': [{'id': n} for n in range(1, 47)]}
    assert fr._continue_snapshot(key, first, 0, 45) is first
    # A larger window ranks a new listing (99) ahead of the last served one (45).
    wider = {'items': [{'id': n} for n in range(1, 45)] + [{'id': 99}, {'id': 45}] + [{'id': n} for n in range(46, 92)]}
    page2 = fr._continue_snapshot(key, wider, 45, 45)['items'][45:90]
    ids = [item['id'] for item in page2]
    assert 45 not in ids and ids[0] == 99 and len(ids) == 45
