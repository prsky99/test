"""Explore filter intent stays separate from report and execution evidence."""

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent_market.capability_registry import Registry, TTL
from agent_market.concierge.front import clear_front_caches
from tests.report_fixtures import legacy_report_fixture
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip("playwright.sync_api")
ORIGIN = "https://agentconcierge.biz"


def _fulfill(call, status=None):
    response = call["response"]
    # Playwright may dispatch a completed fetch while fulfill is still unwinding.
    # Teardown must not abort a route that has already started fulfillment.
    call["released"] = True
    if status is not None:
        call["route"].fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps({"detail": "Earlier isolated search failed."}),
        )
    else:
        call["route"].fulfill(
            status=response.status_code,
            body=response.content,
            headers={key: value for key, value in response.headers.items()
                     if key not in ("content-length", "content-encoding", "transfer-encoding")},
        )
    call["released"] = True


def _wait_calls(state, count):
    """Pump browser routing while deliberately leaving fetch responses pending."""
    deadline = time.monotonic() + 3
    while len(state.calls) < count and time.monotonic() < deadline:
        state.page.wait_for_timeout(10)
    assert len(state.calls) >= count, (
        f"Expected at least {count} Explore requests; saw "
        f"{[call['params'] for call in state.calls]}"
    )


def _settle(page):
    page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")


def _expect_ids(state, expected):
    playwright.expect(state.page.locator("#xResults .acard[data-id]")).to_have_count(len(expected))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        actual = state.page.locator("#xResults .acard[data-id]").evaluate_all(
            "cards => cards.map(card => Number(card.dataset.id)).sort((a, b) => a - b)"
        )
        if actual == sorted(expected):
            return
        state.page.wait_for_timeout(10)
    assert actual == sorted(expected)


@pytest.fixture
def explore_page(browser, catalog):
    store, front, client, add, now = catalog
    clear_front_caches()
    historical = add("Historical Forecast", report_at=now - TTL * 2, trial_ok=1)
    current_report = add("Current Forecast Report", report_at=now - 60)
    execution_only = add("Execution Only Forecast")
    registry = Registry(store)
    registry.record(registry.current(execution_only), scope="execution", outcome="succeeded",
                    started=now - 30, finished=now - 30)
    neither = add("Unmeasured Forecast")

    context = browser.new_context()
    state = SimpleNamespace(
        page=None, calls=[], details=[], hold=False, hold_details=False, errors=[], blocked=[],
        client=client, store=store, add=add, now=now,
        historical=historical, current_report=current_report,
        execution_only=execution_only, neither=neither,
        all_ids=[historical, current_report, execution_only, neither],
    )

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        # Every public HTTP response comes from the isolated TestClient. Never
        # permit provider execution or fall through to any real network origin.
        if (url.hostname != "agentconcierge.biz" or request.method not in ("GET", "HEAD")
                or url.path.startswith("/api/gateway/")):
            state.blocked.append((request.method, url.hostname, url.path))
            route.abort()
            return
        response = client.request(
            request.method,
            url.path + ("?" + url.query if url.query else ""),
            headers={key: value for key, value in request.headers.items()
                     if key in ("accept", "content-type")},
        )
        call = {"route": route, "response": response, "released": False,
                "params": {key: values[-1] for key, values in parse_qs(url.query, keep_blank_values=True).items()}}
        if url.path == "/api/explore":
            assert response.status_code == 200, response.text
            state.calls.append(call)
            if state.hold:
                return
        elif url.path.startswith('/api/agents/'):
            state.details.append(call)
            if state.hold_details:
                return
        _fulfill(call)

    context.route("**/*", serve)
    page = context.new_page()
    state.page = page
    page.on("pageerror", lambda error: state.errors.append(str(error)))
    try:
        yield state
    finally:
        # Native cancellation may finish fetch before a deliberately held
        # Playwright route is released. Resolve those routes before teardown.
        for call in state.calls + state.details:
            if not call['released']:
                call['route'].abort()
                call['released'] = True
        page.wait_for_timeout(0)
        context.close()


def _open(state):
    state.page.goto(ORIGIN + "/#explore")
    playwright.expect(state.page.locator("#xVerified")).not_to_be_checked()
    playwright.expect(state.page.locator("#xHasReport")).not_to_be_checked()
    _expect_ids(state, state.all_ids)
    _settle(state.page)


def test_report_filter_includes_historical_report_without_current_execution_badge(explore_page):
    state = explore_page
    _open(state)
    state.page.locator("#xHasReport").check()
    _expect_ids(state, [state.historical, state.current_report])
    historical = state.page.locator(f'#xResults .acard[data-id="{state.historical}"]')
    playwright.expect(historical.locator('.chip-report')).to_be_visible()
    playwright.expect(historical).not_to_contain_text("Execution checked")
    current = state.page.locator(f'#xResults .acard[data-id="{state.current_report}"]')
    playwright.expect(current).to_contain_text("Execution checked")
    assert state.calls[-1]["params"].get("has_report") == "true"
    assert state.calls[-1]["params"].get("verified", "false") == "false"
    payload = state.calls[-1]["response"].json()
    item = next(item for item in payload["items"] if item["id"] == state.historical)
    assert item["report_count"] > 0
    assert item["connection_readiness"]["verified_callable"] is False
    assert not state.errors


def test_report_and_execution_checkboxes_apply_independent_and_conditions(explore_page):
    state = explore_page
    _open(state)
    state.page.locator("#xVerified").check()
    _expect_ids(state, [state.current_report, state.execution_only])
    state.page.locator("#xHasReport").check()
    _expect_ids(state, [state.current_report])
    assert state.calls[-1]["params"].get("verified") == "true"
    assert state.calls[-1]["params"].get("has_report") == "true"
    state.page.locator("#xVerified").uncheck()
    _expect_ids(state, [state.historical, state.current_report])
    state.page.locator("#xHasReport").uncheck()
    _expect_ids(state, state.all_ids)
    assert not state.errors


@pytest.mark.parametrize("stale_status", [None, 400], ids=["late-success", "late-failure"])
def test_rapid_filter_changes_force_search_and_late_responses_keep_latest_intent(explore_page, stale_status):
    state = explore_page
    _open(state)
    state.hold = True
    initial = len(state.calls)

    # Start every request before changing intent again. The browser cancels
    # superseded fetches while repeated keys still start their latest request.
    state.page.locator('#xHasReport').evaluate('element => element.click()')
    _wait_calls(state, initial + 1)
    for index in range(6):
        state.page.locator('#xVerified').evaluate('element => element.click()')
        _wait_calls(state, initial + index + 2)
    state.page.evaluate("""() => {
      const query = document.getElementById('xQ');
      query.value = 'Historical';
      query.dispatchEvent(new Event('input', {bubbles: true}));
      query.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    }""")
    _wait_calls(state, initial + 8)
    state.page.locator('#xGo').click()
    _wait_calls(state, initial + 9)
    pending = state.calls[initial:]
    query_calls = [call for call in pending if call["params"].get("q") == "Historical"]
    assert query_calls, "Forced Search must work while older requests are pending."
    assert pending[-1]["params"].get("has_report") == "true"
    assert pending[-1]["params"].get("verified", "false") == "false"

    newest = pending[-1]
    _fulfill(newest)
    _expect_ids(state, [state.historical])
    playwright.expect(state.page.locator("#xTitle")).to_contain_text('"Historical" Search Results')
    title = state.page.locator("#xTitle").inner_text()

    # Release the older HTTP responses after the newest response has rendered.
    # Even an older failed request must not replace the current cards with an error.
    for call in reversed(pending[:-1]):
        _fulfill(call, stale_status)
    _settle(state.page)
    _expect_ids(state, [state.historical])
    assert state.page.locator("#xTitle").inner_text() == title
    assert "Search failed" not in state.page.locator("#xResults").inner_text()
    playwright.expect(state.page.locator("#xHasReport")).to_be_checked()
    playwright.expect(state.page.locator("#xVerified")).not_to_be_checked()
    assert not state.errors


def test_previous_response_cannot_render_during_new_query_debounce(explore_page):
    state = explore_page
    _open(state)
    state.hold = True
    initial = len(state.calls)
    state.page.locator("#xHasReport").evaluate("element => element.click()")
    _wait_calls(state, initial + 1)
    old = state.calls[-1]
    state.page.locator("#xQ").evaluate("""element => {
      element.value = 'Historical';
      element.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    before = state.page.locator("#xResults").inner_text()
    _fulfill(old)
    _settle(state.page)
    assert state.page.locator("#xResults").inner_text() == before
    _wait_calls(state, initial + 2)
    newest = state.calls[-1]
    assert newest["params"].get("q") == "Historical"
    _fulfill(newest)
    _expect_ids(state, [state.historical])
    playwright.expect(state.page.locator("#xTitle")).to_contain_text('"Historical" Search Results')
    assert not state.errors


def _shorten_request_deadline(state, milliseconds=120):
    # Keep native fetch/AbortController behavior. Only shorten the production
    # read deadline so native cancellation remains bounded within the test.
    state.context = state.page.context
    state.context.add_init_script("""(() => {
      const schedule = window.setTimeout.bind(window);
      window.setTimeout = (handler, delay, ...args) =>
        schedule(handler, [8000,30000].includes(delay) ? %d : delay, ...args);
    })();""" % milliseconds)


def test_native_abort_timeout_is_safe_bounded_and_search_can_recover(explore_page):
    state = explore_page
    _shorten_request_deadline(state)
    _open(state)
    state.hold = True
    initial = len(state.calls)
    state.page.locator('#xHasReport').check()
    attempts=1 if state.page.locator('#uxClearSearch').count()else 3
    _wait_calls(state, initial + attempts)
    playwright.expect(state.page.locator('#xResults')).to_contain_text(
        'Search timed out. Please try again.')
    state.page.wait_for_timeout(350)
    assert len(state.calls) == initial + attempts, 'A stalled search must respect its read-attempt bound.'
    assert 'signal is aborted' not in state.page.locator('#xResults').inner_text()
    playwright.expect(state.page.locator('#xHasReport')).to_be_checked()
    state.hold = False
    state.page.locator('#xGo').click()
    _expect_ids(state, [state.historical, state.current_report])
    assert not state.errors and not state.blocked


def test_explicit_retry_after_native_timeouts_recovers_without_extra_requests(explore_page):
    state = explore_page
    _shorten_request_deadline(state, 250)
    _open(state)
    state.hold = True
    initial = len(state.calls)
    attempts=1 if state.page.locator('#uxClearSearch').count()else 3
    for index in range(2):
        if index==0:state.page.locator('#xHasReport').check()
        else:state.page.locator('#xGo').click()
        _wait_calls(state,initial+(index+1)*attempts)
        playwright.expect(state.page.locator('#xResults')).to_contain_text('Search timed out.')
    state.page.locator('#xGo').click()
    _wait_calls(state,initial+2*attempts+1)
    _fulfill(state.calls[-1])
    _expect_ids(state, [state.historical, state.current_report])
    state.page.wait_for_timeout(350)
    assert len(state.calls) == initial + 2*attempts+1
    assert 'Search failed' not in state.page.locator('#xResults').inner_text()
    assert not state.errors and not state.blocked


def test_changed_filter_cancels_stalled_request_without_retry_or_stale_error(explore_page):
    state = explore_page
    _shorten_request_deadline(state)
    _open(state)
    state.hold = True
    initial = len(state.calls)
    state.page.locator('#xHasReport').check()
    _wait_calls(state, initial + 1)
    old = state.calls[-1]
    state.page.locator('#xQ').fill('Historical')
    _wait_calls(state, initial + 2)
    latest = state.calls[-1]
    _fulfill(latest)
    _expect_ids(state, [state.historical])
    _fulfill(old, 400)
    state.page.wait_for_timeout(800)
    assert len(state.calls) == initial + 2, 'Superseded requests must never retry.'
    _expect_ids(state, [state.historical])
    assert 'Search failed' not in state.page.locator('#xResults').inner_text()
    assert not state.errors and not state.blocked


def test_explore_query_protocol_category_auth_and_report_filters_keep_same_intent(explore_page):
    state = explore_page
    _open(state)
    locked = state.add('Locked Forecast', category='dev_tools', auth_observed=1)
    clear_front_caches()
    state.page.locator('#xGo').click()
    _expect_ids(state, state.all_ids + [locked])
    state.page.locator('#xKind').select_option('mcp')
    _expect_ids(state, state.all_ids + [locked])
    state.page.locator('#xCategory').select_option('dev_tools')
    _expect_ids(state, [locked])
    state.page.locator('#xNoAuth').check()
    _expect_ids(state, [])
    state.page.locator('#xCategory').select_option('travel_maps_weather')
    _expect_ids(state, state.all_ids)
    state.page.locator('#xHasReport').check()
    _expect_ids(state, [state.historical, state.current_report])
    state.page.locator('#xQ').fill('Historical')
    state.page.locator('#xGo').click()
    _expect_ids(state, [state.historical])
    params = state.calls[-1]['params']
    assert params == {'q': 'Historical', 'limit': '45', 'offset': '0', 'kind': 'mcp',
                      'category': 'travel_maps_weather', 'no_auth': 'true', 'has_report': 'true'}
    assert not state.errors and not state.blocked


def test_late_load_more_page_cannot_replace_new_report_filter(explore_page):
    state = explore_page
    for number in range(48):
        state.add(f'Pagination Forecast {number}')
    state.page.goto(ORIGIN + '/#explore')
    state.page.locator('#xGo').click()
    playwright.expect(state.page.locator('#xResults .acard[data-id]')).to_have_count(45)
    state.hold = True
    initial = len(state.calls)
    state.page.locator('#xLoadMore').click()
    _wait_calls(state, initial + 1)
    old = state.calls[-1]
    assert old['params']['limit'] == '45' and old['params']['offset'] == '45'
    state.page.locator('#xHasReport').check()
    _wait_calls(state, initial + 2)
    latest = state.calls[-1]
    assert latest['params']['limit'] == '45'
    _fulfill(latest)
    _expect_ids(state, [state.historical, state.current_report])
    _fulfill(old)
    _settle(state.page)
    _expect_ids(state, [state.historical, state.current_report])
    assert not state.errors and not state.blocked


def test_load_more_never_exceeds_api_limit_and_filter_resets_page(explore_page):
    state = explore_page
    for number in range(302):
        state.add(f'Bounded Pagination Forecast {number}')
    state.page.goto(ORIGIN + '/#explore')
    state.page.locator('#xGo').click()
    playwright.expect(state.page.locator('#xResults .acard[data-id]')).to_have_count(45)
    for count in [90, 135, 180, 225, 270, 300]:
        state.page.locator('#xLoadMore').click()
        playwright.expect(state.page.locator('#xResults .acard[data-id]')).to_have_count(count)
    playwright.expect(state.page.locator('#xLoadMoreWrap')).not_to_be_visible()
    assert max(int(call['params']['limit']) for call in state.calls) == 45
    assert max(int(call['params']['offset']) for call in state.calls) == 270
    state.page.locator('#xHasReport').check()
    _expect_ids(state, [state.historical, state.current_report])
    assert state.calls[-1]['params']['limit'] == '45'
    assert not state.errors and not state.blocked


@pytest.mark.parametrize('close', [False, True], ids=['new-selection', 'closed-drawer'])
def test_agent_details_ignore_superseded_or_closed_drawer_response(explore_page, close):
    state = explore_page
    _open(state)
    state.hold_details = True
    state.page.evaluate('id => { void openAgent(id); }', state.historical)
    deadline = time.monotonic() + 3
    while len(state.details) < 1 and time.monotonic() < deadline:
        state.page.wait_for_timeout(10)
    assert len(state.details) == 1
    old = state.details[0]
    if close:
        state.page.locator('#closeDrawer').click()
        _fulfill(old)
        _settle(state.page)
        playwright.expect(state.page.locator('#drawer')).not_to_be_visible()
    else:
        state.page.evaluate('id => { void openAgent(id); }', state.current_report)
        deadline = time.monotonic() + 3
        while len(state.details) < 2 and time.monotonic() < deadline:
            state.page.wait_for_timeout(10)
        assert len(state.details) == 2
        _fulfill(state.details[-1])
        playwright.expect(state.page.locator('#drawerContent h3')).to_have_text('Current Forecast Report')
        _fulfill(old, 400)
        _settle(state.page)
        playwright.expect(state.page.locator('#drawerContent h3')).to_have_text('Current Forecast Report')
    assert not state.errors and not state.blocked


@pytest.mark.parametrize('protocol,handler', [
    ('a2a', '363d5688c432'), ('mcp', '648d4dd5905a'), ('x402', 'b51a990235b8')])
def test_home_protocol_shortcut_starts_valid_explore_request(explore_page, protocol, handler, legacy_public_entry):
    state = explore_page
    state.page.goto(ORIGIN + '/#overview')
    state.page.locator(f'[data-ac-click="{handler}"]').click()
    playwright.expect(state.page.locator('#xKind')).to_have_value(protocol)
    _wait_calls(state, 1)
    deadline = time.monotonic() + 3
    while state.calls[-1]['params'].get('kind') != protocol and time.monotonic() < deadline:
        state.page.wait_for_timeout(10)
    assert state.calls[-1]['params'].get('kind') == protocol
    _expect_ids(state, state.all_ids if protocol == 'mcp' else [])
    assert not state.errors and not state.blocked


def test_report_summary_counts_reports_and_agents_separately_including_historical_entries(explore_page):
    state = explore_page
    _open(state)
    # Preserve a pre-existing copy in this isolated store while leaving the
    # production insertion guard intact after the fixture transaction.
    report = dict(state.store.query('SELECT * FROM agent_test_reports WHERE resource_id=? ORDER BY id LIMIT 1',
                                   (state.current_report,))[0])
    report.pop('id')
    report['slug'] = 'preserved-old-copy'
    for field in ('input_wire', 'output_wire', 'pros', 'cons'):
        report[field] = json.loads(report[field])
    legacy_report_fixture(state.store, report)
    with state.store.tx() as db:
        db.execute("UPDATE resources SET health_status='down' WHERE id=?", (state.historical,))
    clear_front_caches()
    state.page.locator('#xHasReport').check()
    _expect_ids(state, [state.historical, state.current_report])
    playwright.expect(state.page.locator('#xTitle')).to_contain_text('2 agents with recorded reports')
    playwright.expect(state.page.locator('#xTitle')).to_contain_text('3 matching recorded reports')
    historical = state.page.locator(f'#xResults .acard[data-id="{state.historical}"]')
    playwright.expect(historical).to_contain_text('Historical entry · unavailable')
    playwright.expect(historical).not_to_contain_text('Execution checked')
    payload = state.calls[-1]['response'].json()
    assert payload['total'] == 2 and payload['matched_report_count'] == 3
    assert payload['historical_agent_count'] == 1 and payload['report_scope'] == 'history'
    state.page.locator('#xQ').fill('Current')
    state.page.locator('#xGo').click()
    _expect_ids(state, [state.current_report])
    playwright.expect(state.page.locator('#xTitle')).to_contain_text('1 matching agent')
    playwright.expect(state.page.locator('#xTitle')).to_contain_text('2 matching recorded reports')
    with state.page.expect_response(lambda response: 'verified=true' in response.url):
        state.page.locator('#xVerified').check()
    _expect_ids(state, [state.current_report])
    assert state.calls[-1]['response'].json()['report_scope'] == 'live'
    assert not state.errors and not state.blocked


def test_bounded_report_count_is_unknown_instead_of_fabricated_zero(explore_page):
    state = explore_page
    _open(state)
    payload = state.client.get('/api/explore?has_report=true&limit=45').json()
    payload.update(total=100, total_is_estimate=True, candidate_window_limited=True,
                   matched_report_count=None, historical_agent_count=None)
    state.page.route('**/api/explore?*', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps(payload)))
    state.page.locator('#xHasReport').check()
    _expect_ids(state, [state.historical, state.current_report])
    playwright.expect(state.page.locator('#xTitle')).to_contain_text('Showing 2 of up to 100 agents')
    assert '0 matching recorded reports' not in state.page.locator('#xTitle').inner_text()
    assert 'None' not in state.page.locator('#xTitle').inner_text()
    assert not state.errors and not state.blocked


def test_historical_drawer_preserves_actual_health_without_claiming_availability(explore_page):
    state = explore_page
    _open(state)
    for health, active in [('retired', 1), ('unknown', 1), ('healthy', 0), ('future_status', 1)]:
        with state.store.tx() as db:
            db.execute('UPDATE resources SET health_status=?,active=? WHERE id=?',
                       (health, active, state.historical))
        clear_front_caches()
        state.page.evaluate('async id => { await openAgent(id); }', state.historical)
        indicator = state.page.locator('#drawerContent .kv dd > span.font-semibold')
        playwright.expect(indicator).to_contain_text(health)
        playwright.expect(indicator).to_contain_text('Availability unconfirmed')
        if not active:
            playwright.expect(indicator).to_contain_text('inactive')
        classes = indicator.get_attribute('class')
        assert 's-healthy' not in classes and 's-reachable' not in classes
        assert indicator.locator('svg path[d="m9 12 2 2 4-4"]').count() == 0
        playwright.expect(state.page.locator('#drawerBadges')).to_contain_text('Historical entry · unavailable')
        assert state.page.locator('#drawerContent').get_by_text('Recent execution confirmed', exact=True).count() == 0
    assert not state.errors and not state.blocked
