"""Opt-in visual audit against isolated data, with before/after evidence per view."""

# ruff: noqa: F401,F811
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console, sign_in, ORIGIN
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_admin_browser import browser_context

ROOT = Path("reports/admin-ux-audit-2026-10-24")
VIEWS = [
    ("home", "운영 홈", "#/home"),
    ("catalog", "카탈로그 목록", "#/catalog"),
    *[
        (f"catalog-{key}", "카탈로그 · " + label, "#/catalog/tools?view=" + key)
        for key, label in [
            ("test", "에이전트 테스트"),
            ("register", "직접 등록"),
            ("reports", "테스트 보고서"),
            ("collector", "수집 진행·실행"),
            ("credentials", "자격증명"),
        ]
    ],
    (
        "catalog-contract",
        "카탈로그 · 의미 계약 검토",
        "#/catalog/tools?view=contract&agent=1",
    ),
    ("gateway", "게이트웨이·실행", "#/gateway"),
    *[
        (f"customers-{key}", "고객 · " + label, "#/customers/" + key)
        for key, label in [
            ("overview", "개요"),
            ("customers", "고객"),
            ("requests", "고객 요청"),
            ("organizations", "조직"),
            ("staff", "직원 작업공간"),
            ("specialists", "전문 관리"),
            ("assignments", "케이스 배정"),
            ("cases", "지원 케이스"),
            ("commands", "승인 명령"),
            ("credits", "크레딧 정산"),
            ("events", "AI·실행 이력"),
        ]
    ],
    ("workflow-search", "워크플로 검색", "#/customers/workflow-search?q=Research"),
    ("public", "공개 서비스 개요", "#/public"),
    *[
        (f"public-{key}", "공개 서비스 · " + label, "#/public/" + key)
        for key, label in [
            ("visitors", "방문 에이전트·연락 동의"),
            ("notifications", "알림 설정·이력"),
            ("sns", "SNS 운영"),
            ("templates", "템플릿 편집·게시"),
        ]
    ],
    *[
        (f"security-{key}", "보안 · " + label, "#/security/" + key)
        for key, label in [
            ("audit", "관리자 감사"),
            ("access", "접속 보안"),
            ("rules", "보안 규칙·승인"),
            ("incidents", "사고·운영 감사"),
        ]
    ],
    ("system", "시스템·저장소", "#/system"),
    ("system-accounts", "관리자 계정·역할", "#/system/accounts"),
]


def baseline_assets(context, phase):
    if phase != "before":
        return

    def asset(route):
        name = route.request.url.split("/admin/next/assets/", 1)[1].split("?", 1)[0]
        path = (ROOT / "baseline-assets" / name).resolve()
        assert (ROOT / "baseline-assets").resolve() in path.parents
        route.fulfill(
            body=path.read_bytes(),
            content_type="text/css" if path.suffix == ".css" else "text/javascript",
        )

    context.route("**/admin/next/assets/**", asset)


def seed_reports(world):
    for i in range(51):
        rid = world.store.upsert_resource(
            {
                "key": f"audit-report-{i}",
                "kind": "mcp",
                "source": "isolated-fixture",
                "name": f"Report fixture agent {i:02}",
                "url": f"https://audit-report-{i}.example/mcp",
                "description": "Isolated visual report fixture",
                "category": "science",
                "networks": [],
                "price_usdc": 0,
            }
        )
        with world.store.tx() as db:
            db.execute("UPDATE resources SET active=0 WHERE id=?", (rid,))
        world.store.create_test_report(
            {
                "resource_id": rid,
                "title": f"UI review report {i:02}",
                "summary": "Synthetic saved document for layout verification",
                "eval_grade": "B",
            }
        )


def save_interaction(page, folder, records, key, label, action):
    page.wait_for_timeout(100)
    page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
    device = "mobile" if page.viewport_size["width"] < 900 else "desktop"
    theme = page.locator("body").get_attribute("data-theme") or "light"
    file = f"{key}-{device}-{theme}.png"
    page.screenshot(path=str(folder / file), full_page=True, caret="initial")
    panel = page.locator("dialog[open],.adm-drawer").last
    panel_metrics = (
        panel.evaluate("(e)=>({width:e.clientWidth,scroll:e.scrollWidth})")
        if panel.count()
        else None
    )
    records.append(
        {
            "id": key,
            "label": label,
            "route": page.url.split("/admin/next")[-1],
            "device": device,
            "theme": theme,
            "file": file,
            "action": action,
            "panel": panel_metrics,
            **diagnostics(page),
        }
    )
    (folder / "interactions.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    )


@pytest.mark.skipif(
    not os.getenv("ADMIN_UX_ACTION_PHASE"), reason="Explicit interaction evidence run"
)
def test_admin_interaction_evidence(dash, browser):
    phase = os.environ["ADMIN_UX_ACTION_PHASE"]
    folder = ROOT / phase
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    seed_reports(dash[0])
    context, page, errors, external = open_console(dash, browser, width=1440)
    baseline_assets(context, phase)
    try:
        page.reload()
        sign_in(page)
        page.locator('#adm-nav a[href="#/catalog"]').click()
        expect(page.locator(".adm-table tbody tr").first).to_be_visible()
        page.locator(".adm-column-choice summary").first.click()
        page.get_by_label("출처 열 표시", exact=True).uncheck()
        expect(page.locator(".adm-table th").filter(has_text="출처")).to_have_count(0)
        save_interaction(
            page,
            folder,
            records,
            "catalog-columns",
            "카탈로그 표시할 열",
            "표시할 열 열기 → 출처 숨김",
        )
        page.get_by_label("출처 열 표시", exact=True).check()
        page.locator(".adm-column-choice summary").first.click()
        page.locator(".adm-sort").first.click()
        save_interaction(
            page, folder, records, "catalog-sort", "카탈로그 정렬", "이름 열 정렬 클릭"
        )
        page.locator(".adm-table tbody tr").first.click()
        expect(page.locator(".adm-drawer")).to_be_visible()
        save_interaction(
            page, folder, records, "catalog-detail", "에이전트 상세", "목록 첫 행 클릭"
        )
        tabs = page.locator(".adm-drawer .adm-tabs .adm-tab")
        labels = tabs.all_text_contents()
        for index, name in enumerate(labels):
            tabs.nth(index).click()
            save_interaction(
                page,
                folder,
                records,
                "catalog-detail-tab-" + str(index),
                "에이전트 상세 · " + name,
                "상세 탭 클릭",
            )
        page.get_by_role("button", name="비활성화", exact=True).click()
        expect(page.locator("dialog.adm-dialog")).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "catalog-confirm",
            "상태 변경 확인",
            "비활성화 클릭 → 확인창 표시, 실행하지 않음",
        )
        page.get_by_role("button", name="취소", exact=True).click()
        page.keyboard.press("Escape")
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=credentials")
        page.get_by_role("button", name="현재 키 목록 조회", exact=True).click()
        expect(page.locator("#adm-main pre.adm-message")).to_contain_text(
            "credentials"
        ) if phase == "before" else expect(
            page.locator(".adm-data-view")
        ).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "credentials-read",
            "자격증명 조회 결과",
            "현재 키 목록 조회 클릭",
        )
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=collector")
        page.get_by_role("button", name="현재 수집 상태 조회", exact=True).click()
        expect(page.locator("#adm-main")).to_contain_text(
            "crawl"
        ) if phase == "before" else expect(
            page.locator(".adm-data-view")
        ).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "collector-read",
            "수집 상태 조회 결과",
            "현재 수집 상태 조회 클릭",
        )
        page.goto(ORIGIN + "/admin/next#/catalog/tools?view=reports")
        page.get_by_role("button", name="현재 보고서 조회", exact=True).click()
        if phase == "after":
            expect(
                page.locator("[data-report-list] .adm-table tbody tr")
            ).to_have_count(50)
            page.get_by_role("button", name="다음 50개", exact=True).click()
            expect(
                page.locator("[data-report-list] .adm-table tbody tr")
            ).to_have_count(1)
            save_interaction(
                page,
                folder,
                records,
                "report-pagination",
                "테스트 보고서 추가 조회",
                "다음 50개 클릭 → 마지막 보고서 1개 확인",
            )
            page.locator("[data-report-list] .adm-table tbody tr").first.click()
            expect(page.locator(".adm-drawer")).to_be_visible()
        else:
            expect(page.locator("[data-report-list] button")).to_have_count(50)
            save_interaction(
                page,
                folder,
                records,
                "report-pagination",
                "테스트 보고서 추가 조회",
                "현재 보고서 조회 → 첫 50개만 표시, 추가 조회 제어 없음",
            )
            page.locator("[data-report-list] button").first.click()
        save_interaction(
            page,
            folder,
            records,
            "report-detail",
            "테스트 보고서 상세",
            "저장된 보고서 항목 클릭",
        )
        page.keyboard.press("Escape")
        page.goto(ORIGIN + "/admin/next#/public/sns")
        page.get_by_role("button", name="공식 글 작성", exact=True).click()
        expect(page.locator(".adm-drawer")).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "sns-compose",
            "SNS 작성 폼",
            "공식 글 작성 클릭, 전송하지 않음",
        )
        page.keyboard.press("Escape")
        page.goto(ORIGIN + "/admin/next#/public/templates")
        page.get_by_role("button", name="새 공개용 초안", exact=True).click()
        expect(page.locator(".adm-drawer")).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "template-editor",
            "템플릿 편집·진주 미리보기",
            "새 공개용 초안 클릭, 저장하지 않음",
        )
        page.keyboard.press("Escape")
        page.goto(ORIGIN + "/admin/next#/system/accounts")
        page.get_by_role("button", name="관리자 생성 요청", exact=True).click()
        expect(page.locator(".adm-drawer")).to_be_visible()
        save_interaction(
            page,
            folder,
            records,
            "account-create",
            "관리자 생성 폼",
            "관리자 생성 요청 클릭, 승인 요청하지 않음",
        )
        page.set_viewport_size({"width": 390, "height": 900})
        save_interaction(
            page,
            folder,
            records,
            "account-create",
            "관리자 생성 폼",
            "모바일에서 입력·확인 영역 점검",
        )
        page.keyboard.press("Escape")
        page.goto(ORIGIN + "/admin/next#/catalog")
        expect(page.locator(".adm-table tbody tr").first).to_be_visible()
        page.locator(".adm-table tbody tr").first.click()
        save_interaction(
            page,
            folder,
            records,
            "catalog-detail",
            "에이전트 상세",
            "모바일에서 목록 첫 행 클릭",
        )
        if phase == "after":
            assert not errors, errors
        assert not external
    finally:
        context.close()


@pytest.mark.skipif(
    not os.getenv("ADMIN_UX_ACTION_PHASE"), reason="Explicit specialist evidence run"
)
def test_specialist_dialog_evidence(private_api, browser):
    phase = os.environ["ADMIN_UX_ACTION_PHASE"]
    folder = ROOT / (phase + "-specialists")
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    w = private_api
    client, context, page, errors, external = browser_context(browser, w.app, ORIGIN)
    baseline_assets(context, phase)
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.headers["owner"]["Authorization"][7:])
        + ");"
    )
    try:
        page.goto(ORIGIN + "/admin/next#/customers/specialists")
        select = page.get_by_label("직원 워크스페이스", exact=True)
        expect(select).to_be_enabled()
        select.select_option(w.ws["id"])
        buttons = page.locator(".adm-specialist-cards button")
        expect(buttons).to_have_count(18)
        labels = buttons.all_text_contents()
        for index, name in enumerate(labels):
            buttons.nth(index).click()
            expect(page.locator("dialog[open]")).to_be_visible()
            page.wait_for_function(
                "() => !document.querySelector('dialog[open][aria-busy=true]')"
            )
            save_interaction(
                page,
                folder,
                records,
                "specialist-" + str(index + 1),
                name,
                "직원 작업공간 선택 → 전문 패널 열기",
            )
            if index in (0, 7, 17):
                page.set_viewport_size({"width": 390, "height": 900})
                save_interaction(
                    page,
                    folder,
                    records,
                    "specialist-" + str(index + 1),
                    name,
                    "모바일 전문 패널 배치 점검",
                )
                page.set_viewport_size({"width": 1500, "height": 1000})
            page.keyboard.press("Escape")
            expect(page.locator("dialog[open]")).to_have_count(0)
        if phase == "after":
            assert not errors, errors
        assert not external
    finally:
        context.close()
        client.close()


def diagnostics(page):
    return page.evaluate("""() => {
      const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
      const main=document.querySelector('#adm-main');
      const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};};
      return {
        page_overflow:document.documentElement.scrollWidth>innerWidth+1,
        headings:[...main.querySelectorAll('h1,h2')].filter(visible).map(e=>e.textContent),
        active_menu:[...document.querySelectorAll('#adm-nav [aria-current=page]')].map(e=>e.textContent.trim()),
        tables:[...main.querySelectorAll('.adm-table-wrap')].filter(visible).map(e=>({...rect(e),scroll:e.scrollWidth,client:e.clientWidth})),
        controls:[...main.querySelectorAll('input:not([type=hidden]),select,textarea,button')].filter(visible).map(e=>({
          label:e.getAttribute('aria-label')||e.textContent.trim().slice(0,60),tag:e.tagName,
          height:Math.round(e.getBoundingClientRect().height),...rect(e),disabled:e.disabled})),
        raw_buttons:[...main.querySelectorAll('button')].filter(e=>visible(e)&&!e.className).map(e=>e.textContent),
        text:main.innerText.slice(0,16000),
        errors:main.innerText.includes('화면을 불러오지 못했습니다')
      };
    }""")


@pytest.mark.skipif(
    not os.getenv("ADMIN_UX_PHASE"), reason="Explicit visual evidence run"
)
def test_all_admin_views_before_after(dash, browser):
    from agent_market.workspace_admin_events import migrate

    world, client = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    seed_reports(world)
    # A long provider-owned name and endpoint reproduce real catalog layout pressure.
    with world.store.tx() as db:
        db.execute(
            "UPDATE resources SET name=?,description=? WHERE id=(SELECT MIN(id) FROM resources)",
            (
                "Research Agent " + "very-long-provider-and-capability-name-" * 6,
                "Synthetic public documentation lookup. " * 15,
            ),
        )
    phase = os.environ["ADMIN_UX_PHASE"]
    dest = ROOT / phase
    dest.mkdir(parents=True, exist_ok=True)
    records = []
    context, page, errors, external = open_console(dash, browser, width=1440)
    baseline_assets(context, phase)
    if phase == "before":
        page.reload()
    error_locations = []
    page.on(
        "console",
        lambda message: error_locations.append(
            {"url": page.url, "text": message.text, "location": message.location}
        )
        if message.type == "error"
        else None,
    )
    page.set_default_timeout(10000)
    try:
        page.screenshot(
            path=str(dest / "login-desktop-light.png"), full_page=True, caret="initial"
        )
        sign_in(page)
        for width, device, theme in [
            (1440, "desktop", "light"),
            (390, "mobile", "light"),
            (1440, "desktop", "dark"),
        ]:
            page.set_viewport_size({"width": width, "height": 900})
            if page.locator("body").get_attribute("data-theme") != theme:
                page.locator("#adm-theme").click()
            for key, label, route in VIEWS:
                if os.getenv("ADMIN_UX_VIEWS") and key not in os.environ[
                    "ADMIN_UX_VIEWS"
                ].split(","):
                    continue
                action = "direct route"
                if page.url != ORIGIN + "/admin/next" + route:
                    link = page.locator('a[href="' + route + '"]:visible').first
                    if not link.count():
                        area = route.split("/")[1].split("?")[0]
                        page.locator('#adm-nav a[href="#/' + area + '"]').click()
                        page.wait_for_function(
                            "() => !document.querySelector('#adm-main .adm-skeleton')"
                        )
                        link = page.locator('a[href="' + route + '"]:visible').first
                    if link.count():
                        link.click()
                        action = "link click"
                    else:
                        page.goto(ORIGIN + "/admin/next" + route)
                expect(page.locator("#adm-main h1")).to_be_visible()
                if phase != "before":
                    page.wait_for_function(
                        "() => document.querySelector('#adm-main').dataset.route===(location.hash||'#/home') && document.querySelector('#adm-main').getAttribute('aria-busy')==='false'"
                    )
                page.wait_for_function(
                    "() => !document.querySelector('#adm-main .adm-skeleton')"
                )
                page.wait_for_timeout(80)
                page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
                shot = f"{key}-{device}-{theme}.png"
                page.screenshot(path=str(dest / shot), full_page=True, caret="initial")
                record = {
                    "id": key,
                    "label": label,
                    "route": route,
                    "device": device,
                    "width": width,
                    "theme": theme,
                    "entry_action": action,
                    "file": shot,
                    **diagnostics(page),
                }
                records.append(record)
                (dest / "screens.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2) + "\n"
                )
                print(
                    json.dumps(
                        {
                            "phase": phase,
                            "view": key,
                            "device": device,
                            "overflow": record["page_overflow"],
                            "raw_buttons": len(record["raw_buttons"]),
                            "error": record["errors"],
                        }
                    ),
                    flush=True,
                )
        (dest / "browser-errors.json").write_text(
            json.dumps(
                {"errors": errors, "external": external, "locations": error_locations},
                indent=2,
            )
            + "\n"
        )
        assert not external
        if phase != "before":
            assert not errors, errors
            assert not [
                r["id"] + ":" + r["device"]
                for r in records
                if r["page_overflow"] or r["errors"]
            ]
            assert all(len(r["active_menu"]) == 1 for r in records)
    finally:
        context.close()
