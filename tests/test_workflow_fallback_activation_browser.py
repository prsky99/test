"""Actual Chromium rendering of the private activation guard, isolated API only."""
# ruff: noqa: F401,F811
from pathlib import Path

from playwright.sync_api import expect
from tests.test_admin_next_browser import dash, browser, open_console


def test_admin_shows_missing_policy_and_disables_activation(dash,browser):
    from agent_market.collector import usage
    from tests.test_workflow_fallback import tool
    world,_=dash
    rid=world.store.upsert_resource({'key':'fixture:io-browser','kind':'mcp','source':'fixture','name':'Documentation mapping',
        'url':'https://mapping.example/mcp','description':'Isolated mapping preview','category':'research','details':{},'price_usdc':0})
    tools=[tool()];world.store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,{'ok':True},full_tools=tools)
    with world.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    context,page,errors,external=open_console(dash,browser)
    try:
        # Use the actual login/mandatory password-change flow. The historical
        # helper also asserts a retired Home heading unrelated to this panel.
        page.locator('#adm-user').fill('sadmin');page.locator('#adm-pass').fill('sadmin')
        page.get_by_role('button',name='로그인',exact=True).click()
        expect(page.locator('#adm-password')).to_be_visible()
        page.locator('#adm-current-password').fill('sadmin')
        page.locator('#adm-new-password').fill('Activation-browser-password')
        page.locator('#adm-confirm-password').fill('Activation-browser-password')
        page.get_by_role('button',name='변경 후 다시 로그인',exact=True).click()
        expect(page.locator('#adm-login')).to_be_visible()
        page.locator('#adm-pass').fill('Activation-browser-password')
        page.get_by_role('button',name='로그인',exact=True).click()
        expect(page.locator('#adm-nav')).to_be_visible()
        page.evaluate("location.hash='/system/t05'")
        status=page.get_by_label('대체 실행 활성화 준비 상태',exact=True)
        expect(status).to_contain_text('승인된 폴백 정책이 없습니다.')
        expect(status).to_contain_text('주소가 다르다는 사실만으로')
        expect(page.get_by_role('button',name='대체 실행 켜기',exact=True)).to_be_disabled()
        expect(page.get_by_role('button',name='에이전트 호출 끄기',exact=True)).to_be_enabled()
        page.get_by_role('button',name='입출력 변환 검토',exact=True).click()
        dialog=page.get_by_role('dialog',name='범용 입출력 변환',exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_label('에이전트 ID',exact=True).fill(str(rid))
        dialog.get_by_label('등록된 읽기 전용 도구',exact=True).fill('search_docs')
        dialog.get_by_role('button',name='1. 현재 스키마 불러오기',exact=True).click()
        expect(dialog.get_by_role('status')).to_contain_text('필드·배열 매핑')
        dialog.get_by_label('입력 변환식 (JSON)',exact=True).fill('{"op":"get","path":""}')
        dialog.get_by_role('button',name='2. 입력 변환 미리보기',exact=True).click()
        expect(dialog.get_by_role('status')).to_contain_text('제공자 호출 0회')
        expect(dialog.get_by_role('status')).to_contain_text('public documentation')
        expect(dialog.get_by_role('checkbox')).not_to_be_checked()
        dialog.get_by_role('button',name='3. 실제 실행 검증·프로필 저장',exact=True).click()
        expect(dialog.get_by_role('status')).to_contain_text('전달 동의')
        assert not world.store.query('SELECT * FROM workflow_io_profiles')
        page.screenshot(path=str(Path('reports/agent-fallback-validation-2026-10-24/activation-admin.png')),full_page=True)
        # A modal intentionally blocks pointer access to the underlying shell;
        # dispatch the shell logout event to verify immediate private-data cleanup.
        page.locator('#adm-logout').dispatch_event('click')
        expect(dialog).to_have_count(0)
        assert not errors and not external
    finally:context.close()
