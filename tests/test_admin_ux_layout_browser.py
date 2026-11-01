"""Operational forms, sensitive result rendering and responsive navigation regressions."""

# ruff: noqa: F401,F811
import json

from playwright.sync_api import expect

from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console, sign_in, ORIGIN


def test_register_labels_alignment_and_structured_results_escape_and_mask(
    dash, browser
):
    context, page, errors, external = open_console(dash, browser, width=1440)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=register")
        url = page.get_by_label("에이전트 HTTPS 주소", exact=True)
        kind = page.get_by_label("프로토콜", exact=True)
        expect(url).to_be_visible()
        assert abs(url.bounding_box()["y"] - kind.bounding_box()["y"]) < 2
        assert (
            kind.bounding_box()["x"]
            > url.bounding_box()["x"] + url.bounding_box()["width"]
        )
        page.set_viewport_size({"width": 390, "height": 900})
        assert (
            kind.bounding_box()["y"]
            > url.bounding_box()["y"] + url.bounding_box()["height"]
        )
        assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        page.evaluate("""async()=>{
          const ui=await import('/admin/next/assets/core/ui.js');
          document.querySelector('#adm-main').append(ui.dataView({
            title:'<img src=x onerror=alert(1)>',api_key:'DO-NOT-SHOW',
            nested:{access_token:'NESTED-DO-NOT-SHOW',ok:true},__proto__:'literal'
          }));
        }""")
        result = page.locator(".adm-data-view").last
        expect(result).to_contain_text("<img src=x onerror=alert(1)>")
        result.locator("summary").click()
        expect(result).not_to_contain_text("DO-NOT-SHOW")
        assert result.locator("img,script,a").count() == 0
        page.goto(ORIGIN + "/admin/next#/system/accounts")
        page.get_by_role("button", name="관리자 생성 요청", exact=True).click()
        drawer = page.locator(".adm-drawer")
        expect(drawer).to_be_visible()
        for control in drawer.locator("input:not([type=checkbox]),select").all():
            assert control.bounding_box()["height"] >= 40
        assert not errors and not external
    finally:
        context.close()


def test_staff_template_respects_csp_and_current_mobile_tab_is_visible(dash, browser):
    from agent_market.workspace_admin_events import migrate
    from tests.test_dashboard import H

    migrate(dash[0].store, dash[0].store._workspace_admin_identity_key)
    owner = dash[0].store.query("SELECT id FROM admin_users WHERE username='sadmin'")[
        0
    ]["id"]
    response = dash[1].post(
        "/admin/api/v2/staff-workspaces",
        headers={**H, "X-Admin-Reason": "Synthetic%20UI%20review"},
        json={"name": "Synthetic UI review", "owner_id": owner},
    )
    assert response.status_code == 200, response.text
    context, page, errors, external = open_console(dash, browser, width=390)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/customers/staff")
        expect(page.locator("#workspaceSelect")).to_be_enabled()
        assert not page.locator(".adm-staff-surface #workspacePanel").evaluate(
            "(e)=>getComputedStyle(e).display==='none'"
        )
        page.goto(ORIGIN + "/admin/next#/customers/events")
        expect(
            page.locator(".adm-subnav a[aria-current=page]")
        ).to_have_attribute("aria-current", "page")
        page.wait_for_function(
            "() => document.querySelector('#adm-main').getAttribute('aria-busy')==='false'"
        )
        assert page.locator(".adm-subnav a[aria-current=page]").evaluate("""e=>{
          const a=e.getBoundingClientRect(),b=e.closest('.adm-subnav').getBoundingClientRect();
          return a.left>=b.left-1 && a.right<=b.right+1;
        }""")
        assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        assert not errors and not external
    finally:
        context.close()


def test_calls_detail_selects_one_tab_and_escape_restores_row_focus(dash, browser):
    context, page, errors, external = open_console(dash, browser, width=390)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/catalog")
        row = page.locator(".adm-table tbody tr").first
        row.focus()
        page.keyboard.press("Enter")
        expect(page.locator(".adm-drawer")).to_be_visible()
        page.get_by_role("tab", name="호출·버전·증거·감사", exact=True).click()
        expect(page.locator(".adm-drawer [aria-selected=true]")).to_have_count(1)
        expect(page.locator(".adm-drawer [aria-selected=true]")).to_have_text(
            "호출·버전·증거·감사"
        )
        assert page.locator(".adm-drawer").bounding_box()["width"] >= 380
        page.keyboard.press("Escape")
        expect(row).to_be_focused()
        assert not errors and not external
    finally:
        context.close()


def test_background_change_does_not_erase_registration_input(dash, browser):
    context, page, errors, external = open_console(dash, browser, width=1440)
    current = {"version": 0, "reads": 0}

    def changes(route):
        current["reads"] += 1
        route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "version": current["version"],
                    "tags": ["catalog:agents"] if current["version"] else [],
                }
            ),
        )

    context.route("**/admin/api/v2/home/changes?*", changes)
    context.add_init_script(
        """(()=>{const original=window.setTimeout;window.setTimeout=(fn,ms,...args)=>original(fn,ms===15000?75:ms,...args);})();"""
    )
    try:
        page.reload()
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=register")
        name = page.get_by_label("에이전트 이름", exact=True)
        name.fill("Keep my reviewed registration draft")
        reads = current["reads"]
        current["version"] = 1
        page.wait_for_timeout(350)
        assert current["reads"] > reads
        expect(name).to_have_value("Keep my reviewed registration draft")
        assert not errors and not external
    finally:
        context.close()


def test_reports_load_immediately_paginate_and_open_in_a_drawer(dash, browser):
    from tests.test_admin_ux_audit_browser import seed_reports

    seed_reports(dash[0])
    context, page, errors, external = open_console(dash, browser, width=1440)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=reports")
        expect(page.locator("[data-report-list]")).to_contain_text("전체 51개")
        expect(page.locator(".adm-table tbody tr")).to_have_count(50)
        page.get_by_role("button", name="다음 50개", exact=True).click()
        expect(page.locator(".adm-table tbody tr")).to_have_count(1)
        expect(
            page.get_by_role("button", name="다음 50개", exact=True)
        ).to_be_disabled()
        page.locator(".adm-table tbody tr").first.click()
        expect(page.locator(".adm-drawer")).to_contain_text("Synthetic saved document")
        assert not errors and not external
    finally:
        context.close()


def test_read_button_shows_progress_and_blocks_duplicate_clicks(dash, browser):
    context, page, errors, external = open_console(dash, browser, width=1440)
    pending = []
    context.route(
        "**/admin/api/v2/catalog-tools/credentials", lambda route: pending.append(route)
    )
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=credentials")
        button = page.get_by_role("button", name="연결 새로 확인", exact=True)
        expect(button).to_be_disabled()
        expect(page.locator("#adm-main [role=status]").last).to_be_visible()
        assert len(pending) == 1
        pending.pop().fulfill(content_type="application/json", body='{"credentials":[]}')
        expect(button).to_be_enabled()
        button.click()
        busy = page.get_by_role("button", name="연결 새로 확인 · 처리 중", exact=True)
        expect(busy).to_be_disabled()
        expect(busy).to_have_attribute("aria-busy", "true")
        busy.evaluate("e=>e.click()")
        assert len(pending) == 1
        pending.pop().fulfill(content_type="application/json", body='{"credentials":[]}')
        expect(button).to_be_enabled()
        expect(button).not_to_have_attribute("aria-busy", "true")
        expect(page.locator("#adm-main")).to_contain_text("등록된 API 키 연결이 없습니다.")
        assert not errors and not external
    finally:
        context.close()


def test_mobile_table_scrolls_inside_frame_without_crushing_columns(dash, browser):
    context, page, errors, external = open_console(dash, browser, width=390)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/security/audit")
        table = page.locator(".adm-table").first
        expect(table).to_be_visible()
        frame = page.locator(".adm-table-wrap").first
        assert frame.evaluate("(e)=>e.scrollWidth>e.clientWidth")
        frame.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "() => document.querySelector('.adm-table-wrap').scrollLeft>0"
        )
        assert table.locator("td").nth(2).bounding_box()["width"] > 80
        assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        assert page.locator("#adm-main").bounding_box()["y"] < 180
        assert not errors and not external
    finally:
        context.close()


def test_dark_navigation_alert_counts_keep_readable_contrast(dash, browser):
    context, page, errors, external = open_console(
        dash, browser, width=1440, theme="dark"
    )
    try:
        sign_in(page)
        ratios = page.evaluate("""()=>{
          const ratio=(a,b)=>{
            const luminance=c=>c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);
            const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
          };
          const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
          const rgb=value=>{ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].slice(0,3);};
          return ['danger','warning'].map(level=>{
            const badge=document.createElement('span');badge.className='adm-count';badge.dataset.level=level;badge.textContent='12';
            document.querySelector('#adm-nav a').append(badge);const css=getComputedStyle(badge);
            const result=ratio(rgb(css.color),rgb(css.backgroundColor));badge.remove();return result;
          });
        }""")
        assert all(value >= 4.5 for value in ratios), ratios
        assert not errors and not external
    finally:
        context.close()
