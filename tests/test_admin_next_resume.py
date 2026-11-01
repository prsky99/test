"""Renewal continuation: private cache, single-flight, session and aggregate contracts."""
# ruff: noqa: F401, F811 -- shared isolated fixtures
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from playwright.sync_api import expect

from agent_market.admin_next import TimedCache
from tests.test_admin_next import D, dash, login
from tests.test_admin_next_browser import browser, open_console, sign_in


def test_server_cache_cold_requests_have_one_loader_and_refresh_does_not_resurrect():
    cache = TimedCache(5, 30)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def loader():
        calls.append(1); entered.set()
        assert release.wait(5)
        return {'value': 'old'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(cache.get, 'one', loader) for _ in range(4)]
        assert entered.wait(5)
        release.set()
        assert all(task.result()['value'] == 'old' for task in tasks)
    assert len(calls) == 1
    cache.invalidate()
    entered.clear(); release.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(cache.get, 'two', loader)
        assert entered.wait(5)
        cache.invalidate(); release.set(); task.result()
    assert 'two' not in cache.values


def test_public_summary_is_individual_staff_only_and_has_no_private_rows(dash):
    _, client = dash
    path = '/admin/api/v2/public/summary'
    assert client.get(path, headers=D).status_code == 401
    assert client.get(path, headers={**D, 'Authorization': 'Bearer secret'}).status_code == 401
    headers = login(client)
    result = client.get(path, headers=headers)
    assert result.status_code == 200
    body = result.json()
    assert {'visitors', 'requests', 'templates', 'captured_at'} <= set(body)
    assert not body['advertising_delivery_enabled']
    assert body['visitors']['active_task_watches'] == 0
    assert all(set(row) <= {'id', 'name', 'category', 'runs_count', 'updated_at'} for row in body['templates'])
    assert 'items' not in body['visitors'] and 'llm' not in body
    assert client.get(path, headers={**headers, 'If-None-Match': result.headers['etag']}).status_code == 304
    assert client.get(path, headers={**headers, 'Origin': 'https://untrusted.test'}).status_code == 403


def test_duplicate_and_nonfinite_mutation_fields_are_refused(dash):
    _, client = dash
    headers = {**login(client), 'Content-Type': 'application/json'}
    url = '/admin/api/v2/catalog/collector/actions'
    for body in ('{"action":"pause","action":"resume","reason":"synthetic reason"}',
                 '{"action":"pause","reason":"synthetic reason","value":NaN}'):
        assert client.post(url, headers=headers, content=body).status_code == 400


def test_private_reads_are_not_cached_and_session_switch_discards_inflight(dash, browser):
    context, page, _, _ = open_console(dash, browser)
    try:
        result = page.evaluate("""async()=>{
          const api=await import('/admin/next/assets/core/api.js');
          api.session.set('synthetic-session-a');
          let calls=0, release;
          window.fetch=async()=>{calls++;return new Response(JSON.stringify({secret:calls}),{headers:{'Content-Type':'application/json'}})};
          await api.read('/admin/api/workspace-operations/customers');
          await api.read('/admin/api/workspace-operations/customers');
          const privateCalls=calls;
          window.fetch=()=>new Promise(resolve=>release=resolve);
          const old=api.read('/admin/api/v2/catalog/agents').catch(error=>({blocked:error.status}));
          api.session.set('synthetic-session-b');
          release(new Response(JSON.stringify({oldOwner:true}),{headers:{'Content-Type':'application/json'}}));
          return {privateCalls,late:await old};
        }""")
        assert result == {'privateCalls': 2, 'late': {'blocked': 409}}
    finally:
        context.close()


def test_tag_invalidation_blocks_pending_repopulation_but_preserves_other_cache(dash, browser):
    context, page, _, _ = open_console(dash, browser)
    try:
        result = page.evaluate("""async()=>{
          const api=await import('/admin/next/assets/core/api.js');api.session.set('synthetic-session');
          let calls=0,release;
          window.fetch=async()=>{calls++;return new Response(JSON.stringify({serial:calls}),{headers:{'Content-Type':'application/json'}})};
          await api.read('/admin/api/v2/system/storage',{tags:['system']});
          window.fetch=()=>new Promise(resolve=>release=resolve);
          const old=api.read('/admin/api/v2/catalog/agents',{tags:['catalog']}).catch(error=>({blocked:error.status}));
          api.invalidate('catalog');
          release(new Response(JSON.stringify({old:true}),{headers:{'Content-Type':'application/json'}}));
          const late=await old;
          const other=await api.read('/admin/api/v2/system/storage',{tags:['system']});
          window.fetch=async()=>{calls++;return new Response('{}',{headers:{'Content-Type':'application/json'}})};
          await api.read('/admin/api/v2/catalog/agents',{tags:['catalog']});
          return {late,other:other.state,calls};
        }""")
        assert result == {'late': {'blocked': 409}, 'other': 'hit', 'calls': 2}
    finally:
        context.close()


def test_logout_hides_private_view_and_dialog_before_slow_response(dash, browser):
    context, page, errors, _ = open_console(dash, browser)
    held = []
    try:
        sign_in(page)
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        page.locator('.adm-table tbody tr').first.click()
        page.get_by_role('button', name='비활성화', exact=True).click()
        expect(page.locator('dialog.adm-dialog')).to_be_visible()
        page.keyboard.press('Escape')
        page.route('**/admin/api/v2/auth/logout', lambda route: held.append(route))
        page.locator('#adm-logout').click()
        expect(page.locator('#adm-login')).to_be_visible()
        expect(page.locator('.adm-drawer, dialog.adm-dialog')).to_have_count(0)
        expect(page.locator('#adm-main')).to_be_empty()
        assert page.evaluate("sessionStorage.getItem('adminToken')") is None
        page.wait_for_function("document.getElementById('adm-login-status').textContent.includes('로그아웃')")
        assert len(held) == 1  # The real v2 logout is pending while the private UI is cleared.
        for route in held:
            route.fulfill(status=200, json={'ok': True})
        assert not errors
    finally:
        context.close()


def test_credit_incomplete_and_corrupt_states_never_show_matched(dash, browser):
    context, page, errors, _ = open_console(dash, browser)
    try:
        sign_in(page)
        page.route('**/admin/api/v2/customers/operations/options', lambda route: route.fulfill(json={'migration_required': False}))
        page.route('**/admin/api/v2/customers/operations/credits/reconciliation?*', lambda route: route.fulfill(json={
            'accounts': [{'customer_id': 'synthetic-' + status, 'status': status} for status in
                         ('incomplete', 'integrity_review_required', 'unexpected')], 'next_cursor': None}))
        page.goto('https://admin.test/admin/next#/customers/credits')
        expect(page.locator('.adm-table')).to_contain_text('검증 범위 초과')
        expect(page.locator('.adm-table')).to_contain_text('무결성 검토 필요')
        expect(page.locator('.adm-table .adm-pearl[data-status=ok]')).to_have_count(0)
        page.screenshot(path='reports/admin-renewal-design-2026-10-21/resume/credit-review.png', full_page=True)
        assert not errors
    finally:
        context.close()


def test_public_area_uses_real_aggregate_and_safe_text(dash, browser):
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.locator('#adm-nav a', has_text='공개 서비스').click()
        # The area opens on search quality (P07); service status (P01) holds the aggregate.
        page.locator('#adm-nav').get_by_role('link', name='공개 서비스 상태', exact=True).click()
        expect(page.get_by_role('heading', name='공개 워크플로 템플릿', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='서비스 운영 연결', exact=True)).to_be_visible()
        expect(page.locator('#adm-main')).not_to_contain_text('P4에서 옮깁니다')
        page.screenshot(path='reports/admin-renewal-design-2026-10-21/resume/public-service.png', full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_expired_staff_session_clears_private_dom_and_filters(dash, browser):
    context, page, _, _ = open_console(dash, browser)
    try:
        sign_in(page)
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        page.get_by_role('searchbox', name='이름·주소 검색', exact=True).fill('private-session-filter')
        expect(page.locator('.adm-table')).to_have_count(0)
        page.route('**/admin/api/v2/public/summary', lambda route: route.fulfill(status=401, json={'detail': 'Expired'}))
        page.locator('#adm-nav a', has_text='공개 서비스').click()
        page.locator('#adm-nav').get_by_role('link', name='공개 서비스 상태', exact=True).click()
        expect(page.locator('#adm-login')).to_be_visible()
        expect(page.locator('#adm-main')).to_be_empty()
        assert page.evaluate("sessionStorage.getItem('adminToken')") is None
        page.unroute('**/admin/api/v2/public/summary')
        sign_in(page)
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        expect(page.get_by_role('searchbox', name='이름·주소 검색', exact=True)).to_have_value('')
    finally:
        context.close()


def test_global_id_search_opens_authorized_metadata_destinations(dash, browser):
    context, page, errors, _ = open_console(dash, browser)
    customer, workspace, operation = 'cu_' + '1' * 32, 'ws_' + '2' * 32, 'op_' + '3' * 32
    def wac(route):
        path = urlsplit(route.request.url).path
        if path.endswith('/options'):
            data = {'migration_required': False}
        elif path.endswith('/customers/' + customer):
            data = {'customer': {'id': customer, 'issuer': 'synthetic'}, 'links': [], 'active_sessions': 0}
        elif path.endswith('/organizations/' + workspace + '/operations'):
            data = {}
        elif path.endswith('/operations/' + operation):
            data = {'authoritative_state': {'status': 'unknown'}, 'events': []}
        else:
            data = {'customers': [], 'organizations': [], 'events': [], 'next_cursor': None}
        route.fulfill(json=data)
    try:
        sign_in(page)
        page.route('**/admin/api/v2/customers/operations/**', wac)
        page.route('**/admin/api/v2/console/executions/'+operation, lambda route:route.fulfill(json={'operation':{'id':operation,'status':'unknown'},'attempts':[]}))
        for identity, area in ((customer, 'customers/customers?customer='),
                               (workspace, 'customers/organizations?workspace='),
                               (operation, 'workflows/w05?operation=')):
            page.locator('#adm-search-input').fill(identity)
            page.locator('#adm-search-input').press('Enter')
            expect(page).to_have_url('https://admin.test/admin/next#/' + area + identity)
            if identity==operation:expect(page.locator('#adm-main')).to_contain_text(identity)
            else:
                expect(page.locator('.adm-drawer')).to_contain_text(identity)
                page.keyboard.press('Escape')
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        rid = page.locator('.adm-table tbody tr').first.locator('td').first.inner_text()
        assert rid  # Existing catalog fixture still loads after all metadata lookups.
        assert not errors
    finally:
        context.close()
