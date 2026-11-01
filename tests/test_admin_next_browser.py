"""Chromium walks the renewed console against an isolated gateway app (no operating server)."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_dashboard import dash  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
ORIGIN = 'https://admin.test'
SHOTS = Path('reports/admin-renewal-design-2026-10-21/screenshots')


def open_console(dash, browser, width=1280, theme='light'):
    from fastapi.testclient import TestClient
    world, _ = dash
    client = TestClient(world.app, base_url=ORIGIN)  # same host as the browser, so origin checks apply as in production
    context = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=theme, reduced_motion='reduce')
    page = context.new_page(); errors = []; external = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test':
            external.append(request.url); route.abort(); return
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''), content=request.post_data,
                                  headers={k: v for k, v in request.headers.items() if k.lower() in ('content-type', 'authorization', 'x-dashboard', 'x-admin-refresh', 'x-admin-reason', 'origin')})
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    page.goto(ORIGIN + '/admin/next')
    return context, page, errors, external


def sign_in(page):
    expect = playwright.expect
    expect(page.locator('#adm-login')).to_be_visible()
    rotated = getattr(page, '_renewal_rotated', False)
    page.locator('#adm-user').fill('sadmin')
    page.locator('#adm-pass').fill('Renewal-browser-password' if rotated else 'sadmin')
    page.get_by_role('button', name='로그인', exact=True).click()
    if not rotated:
        expect(page.locator('#adm-password')).to_be_visible()
        page.locator('#adm-current-password').fill('sadmin')
        page.locator('#adm-new-password').fill('Renewal-browser-password')
        page.locator('#adm-confirm-password').fill('Renewal-browser-password')
        page.get_by_role('button', name='변경 후 다시 로그인').click()
        expect(page.locator('#adm-login')).to_be_visible()
        page.locator('#adm-pass').fill('Renewal-browser-password')
        page.get_by_role('button', name='로그인', exact=True).click()
        page._renewal_rotated = True
    expect(page.locator('#adm-layout')).to_be_visible()


def test_login_home_necklace_areas_and_logout(dash, browser):
    expect = playwright.expect
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        expect(page.locator('#adm-nav>li>a')).to_have_count(8)
        expect(page.locator('#adm-nav a[aria-current=page]')).to_have_text('운영 요약')
        expect(page.locator('.adm-flow button')).to_have_count(5)
        expect(page.locator('.adm-kpis .adm-kpi').filter(has_text='기본 헬스체크 주기')).to_contain_text('6시간')
        expect(page.locator('.adm-flow svg.adm-thread path')).to_have_count(1)
        expect(page.locator('.adm-fresh').first).to_contain_text('기준')
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / 'next-home-light.png'), full_page=True)
        # Catalog: table, remembered filter, detail drawer with recent checks.
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        expect(page.locator('.adm-table tbody tr').first).to_be_visible()
        page.locator('.adm-table tbody tr').first.click()
        expect(page.locator('.adm-drawer')).to_be_visible()
        page.keyboard.press('Escape'); expect(page.locator('.adm-drawer')).to_have_count(0)
        page.locator('.adm-filters select').first.select_option('mcp')
        page.goto(ORIGIN + '/admin/next#/system/t05')
        expect(page.get_by_role('heading', name='서비스 설정', exact=True)).to_be_visible()
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        expect(page.locator('.adm-filters select').first).to_have_value('mcp')
        # Global search routes to the catalog.
        page.locator('#adm-search-input').fill('weather'); page.keyboard.press('Enter')
        expect(page).to_have_url(ORIGIN + '/admin/next#/catalog?q=weather')
        page.goto(ORIGIN + '/admin/next#/system/t03')
        expect(page.get_by_role('heading', name='로그·데이터 보존', exact=True)).to_be_visible()
        page.locator('#adm-nav>li>a', has_text='고객·지원').click()
        expect(page.locator('#adm-main')).to_have_attribute('data-screen', 'U01')
        expect(page.locator('a[href^="/admin/ui"]')).to_have_count(0)
        page.locator('#adm-theme').click()
        expect(page.locator('body')).to_have_attribute('data-theme', 'dark')
        page.locator('#adm-nav>li>a', has_text='운영 홈').click()
        expect(page.locator('.adm-flow svg.adm-thread')).to_have_count(1)
        page.screenshot(path=str(SHOTS / 'next-home-dark.png'), full_page=True)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.locator('#adm-logout').click()
        expect(page.locator('#adm-login')).to_be_visible()
        assert page.evaluate("sessionStorage.getItem('adminToken')") is None
        assert not errors and not external
    finally:
        context.close()


def test_mobile_console_has_no_horizontal_overflow(dash, browser):
    expect = playwright.expect
    context, page, errors, external = open_console(dash, browser, width=390)
    try:
        sign_in(page)
        expect(page.locator('.adm-flow button')).to_have_count(5)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(SHOTS / 'next-home-390.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_shared_machine_token_cannot_open_the_console(dash, browser):
    expect = playwright.expect
    context, page, errors, _ = open_console(dash, browser)
    try:
        page.evaluate("sessionStorage.setItem('adminToken','secret')"); page.reload()
        expect(page.locator('#adm-login')).to_be_visible()
        expect(page.locator('#adm-login-status')).to_contain_text('개인 관리자')
    finally:
        context.close()


def test_agent_change_asks_reason_and_updates_the_list(dash, browser):
    expect = playwright.expect
    world, _ = dash
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.locator('#adm-nav>li>a', has_text='에이전트 관리').click()
        row = page.locator('.adm-table tbody tr').first
        name = row.locator('td').first.inner_text().strip()
        row.click()
        page.get_by_role('button', name='비활성화', exact=True).click()
        dialog = page.locator('dialog.adm-dialog')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='비활성화', exact=True).click()
        expect(dialog.locator('.adm-status')).to_contain_text('4자 이상')
        dialog.locator('textarea').fill('브라우저 검증용 비활성화')
        dialog.get_by_role('button', name='비활성화', exact=True).click()
        expect(page.locator('.adm-toast')).to_contain_text('비활성화 완료')
        expect(page.get_by_role('button', name='활성화', exact=True)).to_be_visible()
        expect(page.locator('.adm-table')).not_to_contain_text(name)
        page.get_by_role('button', name='활성화', exact=True).click()
        page.locator('dialog.adm-dialog textarea').fill('검증 후 복구')
        page.locator('dialog.adm-dialog').get_by_role('button', name='활성화', exact=True).click()
        expect(page.locator('.adm-toast').last).to_contain_text('활성화 완료')
        page.keyboard.press('Escape')
        page.goto(ORIGIN + '/admin/next#/system/t05')
        expect(page.locator('.adm-switch')).to_have_count(4)
        page.goto(ORIGIN + '/admin/next#/system/t03')
        expect(page.get_by_role('heading', name='보존 현황', exact=True)).to_be_visible()
        assert not errors and not external
    finally:
        context.close()


def test_customers_and_security_areas_show_reasons_and_tabs(dash, browser):
    expect = playwright.expect
    from fastapi.testclient import TestClient
    world, _ = dash
    api = TestClient(world.app, base_url=ORIGIN)
    from tests.test_dashboard import H
    staff = dict(H)
    rid = api.get('/admin/api/v2/catalog/agents?limit=1', headers=staff).json()['items'][0]['id']
    api.post('/admin/api/v2/catalog/agents/%d/actions' % rid, json={'action': 'deactivate', 'reason': '감사 화면 확인용', 'expected_active': True}, headers=staff)
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + '/admin/next#/security/s02')
        expect(page.locator('.adm-subnav a[aria-current=page]')).to_have_text('관리자 작업 이력')
        expect(page.locator('.adm-table')).to_contain_text('사유: 감사 화면 확인용')
        page.locator('.adm-subnav a', has_text='접속 보안').click()
        expect(page.get_by_role('heading', name='최근 보안 이벤트', exact=True)).to_be_visible()
        page.locator('#adm-nav>li>a', has_text='고객·지원').click()
        expect(page.locator('.adm-subnav a', has_text='담당 배정')).to_be_visible()
        expect(page.locator('#adm-main')).not_to_contain_text('화면을 불러오지 못했습니다')
        page.goto(ORIGIN + '/admin/next#/system/t03')
        expect(page.get_by_role('heading', name='보존 기간 미리보기', exact=True)).to_be_visible()
        assert not [e for e in errors if 'status of 404' not in e] and not external
    finally:
        context.close()


def test_kill_switch_release_is_a_reviewed_command(dash, browser):
    expect = playwright.expect
    world, _ = dash
    from agent_market.workspace_admin_events import migrate
    migrate(world.store, b'synthetic-reviewed-command-key-32')
    with world.store.tx() as db:  # the sole active superadmin path
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + '/admin/next#/system/t05')
        dialog = page.locator('dialog.adm-dialog')
        page.get_by_role('button', name='에이전트 호출 끄기').click()
        dialog.locator('textarea').fill('브라우저 검증용 일시 중지')
        dialog.get_by_role('button', name='끄기', exact=True).click()
        expect(page.get_by_role('button', name='에이전트 호출 켜기')).to_be_visible()
        page.get_by_role('button', name='에이전트 호출 켜기').click()
        expect(dialog).to_contain_text('승인 요청으로 등록')
        dialog.locator('textarea').fill('점검 완료 후 재개 요청')
        dialog.get_by_role('button', name='승인 요청', exact=True).click()
        expect(page.get_by_role('button', name='에이전트 호출 켜기')).to_be_visible()
        page.goto(ORIGIN + '/admin/next#/security/s01')
        review = page.locator('.adm-reviews li').first
        expect(review).to_contain_text('승인 대기')
        expect(review).to_contain_text('분 남음')
        review.get_by_role('button', name='검토 후 적용').click()
        dialog.locator('textarea').fill('본인 단독 검토 후 적용')
        dialog.get_by_role('button', name='적용', exact=True).click()
        expect(dialog.locator('.adm-status')).to_contain_text('확인 항목')
        dialog.locator('#adm-ack').check()
        dialog.get_by_role('button', name='적용', exact=True).click()
        expect(page.locator('.adm-reviews li').first).to_contain_text('적용됨')
        page.goto(ORIGIN + '/admin/next#/system/t05')
        expect(page.get_by_role('button', name='에이전트 호출 끄기')).to_be_visible()
        page.screenshot(path=str(SHOTS / 'next-gateway-reviewed-release.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_agent_drawer_strings_daily_summaries_as_pearls(dash, browser):
    expect = playwright.expect
    world, _ = dash
    import time
    from agent_market.workspace_admin_events import migrate
    from agent_market.workspace_admin_summaries import DAY, HealthSummaries
    migrate(world.store, world.store._workspace_admin_identity_key)
    rid = world.store.query('SELECT id FROM resources WHERE active=1 ORDER BY id DESC LIMIT 1')[0][0]
    today = int(time.time() // DAY) * DAY
    with world.store.tx() as db:
        for days_ago, outcome in ((3, 'healthy'), (2, 'down'), (1, 'healthy')):
            db.execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(?,?,?,?,?)',
                       (rid, today - days_ago * DAY + 60, outcome, 200, 120))
    worker = HealthSummaries(world.store)
    for days_ago in (3, 2, 1):
        worker.summarize_day(today - days_ago * DAY)
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + '/admin/next#/catalog?agent=' + str(rid))
        drawer = page.locator('.adm-drawer')
        expect(drawer).to_contain_text('최근 30일')
        strand = drawer.locator('[aria-label^="일별 상태"] .adm-pearl')
        expect(strand).to_have_count(3)
        expect(drawer).to_contain_text('3일 · 성공률')
        expect(drawer.locator('h2')).not_to_have_text('에이전트 ' + str(rid))
        expect(page.locator('main')).not_to_contain_text('null')
        page.screenshot(path=str(SHOTS / 'next-agent-daily.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_retention_change_is_requested_then_applied_through_review(dash, browser):
    expect = playwright.expect
    world, _ = dash
    from agent_market.workspace_admin_events import migrate
    migrate(world.store, world.store._workspace_admin_identity_key)
    with world.store.tx() as db:
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + '/admin/next#/system/t03')
        card = page.locator('section', has=page.get_by_role('heading', name='보존 기간 설정'))
        row = card.locator('.adm-switch', has_text='security_events')
        expect(row).to_contain_text('자동 정리 안 함')
        expect(row.locator('select option')).to_have_count(5)  # 30-day floor: off, 30, 90, 180, 365
        row.locator('select').select_option('90')
        row.get_by_role('button', name='변경 요청').click()
        dialog = page.locator('dialog.adm-dialog')
        dialog.locator('textarea').fill('보안 이벤트 90일 보존')
        dialog.get_by_role('button', name='승인 요청', exact=True).click()
        expect(dialog.locator('.adm-status')).to_contain_text('확인 항목')
        dialog.locator('#adm-ack').check()
        dialog.get_by_role('button', name='승인 요청', exact=True).click()
        expect(page.locator('.adm-toast')).to_contain_text('보존 기간 변경 요청')
        expect(row).to_contain_text('자동 정리 안 함')  # not applied yet
        page.goto(ORIGIN + '/admin/next#/security/s01')
        review = page.locator('.adm-reviews li').first
        expect(review).to_contain_text('security_events → 90일 보존')
        review.get_by_role('button', name='검토 후 적용').click()
        dialog.locator('textarea').fill('백업 확인 후 단독 검토')
        dialog.locator('#adm-ack').check()
        dialog.get_by_role('button', name='적용', exact=True).click()
        expect(page.locator('.adm-reviews li').first).to_contain_text('적용됨')
        page.goto(ORIGIN + '/admin/next#/system/t03')
        expect(page.locator('.adm-switch', has_text='security_events')).to_contain_text('90일 보존')
        page.screenshot(path=str(SHOTS / 'next-retention-policy.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_customer_inquiry_is_answered_from_the_requests_tab(dash, browser):
    expect = playwright.expect
    world, _ = dash
    inquiry = world.store.record_customer_inquiry('general', 'Synthetic Person', 'person@example.invalid', 'Workflow question',
                                                  '<img src=x onerror="window.hostile=1"> How do I share?')
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + '/admin/next#/customers/requests')
        expect(page.locator('.adm-kpi').first).to_contain_text('미해결 문의')
        page.locator('.adm-table tbody tr', has_text='Workflow question').click()
        drawer = page.locator('.adm-drawer')
        expect(drawer).to_contain_text('person@example.invalid')
        drawer.get_by_label('처리 상태').select_option('resolved')
        drawer.get_by_label('고객 답변').fill('Use the Share button in the workflow menu.')
        drawer.get_by_role('button', name='저장').click()
        expect(drawer.locator('.adm-status')).to_contain_text('4자 이상')
        drawer.get_by_label('변경 사유').fill('고객 문의 답변')
        drawer.get_by_role('button', name='저장').click()
        expect(page.locator('.adm-toast')).to_contain_text('처리 내용을 저장했습니다')
        expect(page.locator('.adm-table tbody tr', has_text='Workflow question')).to_contain_text('해결')
        expect(page.locator('.adm-kpi').first).to_contain_text('0')
        stored = world.store.get_customer_inquiry(inquiry)
        assert stored['status'] == 'resolved' and stored['resolved_by'] == 'sadmin'
        assert not page.evaluate('Boolean(window.hostile)')
        page.screenshot(path=str(SHOTS / 'next-customer-requests.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()


def test_staff_role_review_displays_changes_and_applies(dash, browser):
    from agent_market.gateway import admin_auth
    from agent_market.workspace_admin_events import migrate
    expect = playwright.expect
    world, client = dash
    migrate(world.store, getattr(world.store, '_workspace_admin_identity_key', b'synthetic-reviewed-command-key-32'))
    with world.store.tx() as db:
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
        target = admin_auth.create_admin_user(db, 'browser-operator', 'Browser-operator-password', 'Fixture operator', 'operator')
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        # Use the actual legacy role selector, then the shared renewal approval screen.
        page.goto(ORIGIN + '/admin/ui#users')
        expect(page.locator('#staffRole-' + str(target['id']))).to_be_visible()
        page.locator('#staffRole-' + str(target['id'])).select_option('viewer')
        page.once('dialog', lambda dialog: dialog.accept('Synthetic browser role review'))
        page.locator('[data-adm-click="staffRoleReview"][data-id="' + str(target['id']) + '"]').click()
        expect(page.get_by_text('승인 요청을 등록했습니다.', exact=False)).to_be_visible()
        page.locator('#staffReviewLink').click()
        expect(page.get_by_role('heading', name='승인 대기', exact=True).first).to_be_visible()
        review = page.locator('.adm-reviews li').first
        expect(review).to_contain_text('browser-operator')
        expect(review).to_contain_text('operator → viewer')
        review.get_by_role('button', name='검토 후 적용').click()
        dialog = page.locator('dialog.adm-dialog')
        expect(dialog).to_contain_text('기존 세션을 종료')
        dialog.locator('textarea').fill('Synthetic sole administrator review')
        dialog.locator('#adm-ack').check()
        dialog.get_by_role('button', name='적용', exact=True).click()
        expect(page.locator('.adm-reviews li').first).to_contain_text('적용됨')
        with world.store.tx() as db:
            assert next(u for u in admin_auth.list_admin_users(db) if u['id'] == target['id'])['role'] == 'viewer'
        assert not errors and not external
    finally:
        context.close()
