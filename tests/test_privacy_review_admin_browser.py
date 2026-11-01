"""Private desktop review uses real APIs, CSP and an isolated SQLite database."""
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser  # noqa: F401

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def privacy_page(browser, tmp_path):
    store = Store(str(tmp_path / 'privacy-review.db'))
    identity = store.record_privacy_request('data_access', email='privacy@example.test',
        details='Synthetic access request\nReview only after identity verification.')
    attack = '<img src=x onerror="window.__privacyXss=1"><script>window.__privacyXss=1</script>'
    store.update_privacy_request(identity, 'pending_verification', notes=attack)
    app = FastAPI()
    app.include_router(dashboard_router(store, str(tmp_path / 'privacy-review.db'),
        'isolated-privacy-system-token', None, ssl_manager=Mock(get_status=lambda: {})))
    client = TestClient(app, base_url='https://admin.test')
    context = browser.new_context(viewport={'width': 1440, 'height': 950})
    world = SimpleNamespace(store=store, identity=identity, client=client, calls=[], errors=[], external=[],
        fail_after_patch=False, fail_patch=False)

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'admin.test':
            world.external.append(request.url)
            return route.abort()
        world.calls.append((request.method, url.path, request.post_data_json if request.post_data else None))
        if request.method == 'PATCH' and world.fail_patch:
            return route.fulfill(status=503, content_type='application/json', body='{"detail":"Synthetic unavailable review"}')
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
            content=request.post_data, headers=request.headers)
        if request.method == 'PATCH' and world.fail_after_patch:
            return route.fulfill(status=503, content_type='application/json', body='{"detail":"Synthetic response loss"}')
        route.fulfill(status=response.status_code, body=response.content,
            headers={k: v for k, v in response.headers.items()
                if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    page = context.new_page()
    world.page = page
    page.on('pageerror', lambda error: world.errors.append(str(error)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin')
    page.locator('#adminLoginPassword').fill('sadmin')
    page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="needs"]').click()
    page.locator('[data-subtab="privacy"]').click()
    expect(page.locator(f'[data-privacy-review-id="{identity}"]')).to_be_visible()
    yield world
    context.close()
    client.close()
    store._db.close()
    assert not world.errors
    assert not world.external


def open_review(world):
    world.page.locator(f'[data-privacy-review-id="{world.identity}"]').click()
    dialog = world.page.locator('#privacyReviewDialog')
    expect(dialog).to_be_visible()
    expect(world.page.locator('#privacyReviewStatus')).to_have_value('pending_verification')
    return dialog


def test_review_is_centered_text_only_and_survives_real_auto_refresh(privacy_page):
    w = privacy_page
    page = w.page
    dialog = open_review(w)
    assert dialog.evaluate('(el) => el.matches(":modal") && el.parentElement === document.body')
    box = dialog.bounding_box()
    assert abs(box['x'] + box['width'] / 2 - 720) < 2
    assert abs(box['y'] + box['height'] / 2 - 475) < 2
    expect(dialog).to_contain_text('Receipt reference (not completion evidence)')
    expect(page.locator('#privacyReviewProof')).to_have_value('')
    assert dialog.locator('img,script').count() == 0
    assert page.evaluate('window.__privacyXss || 0') == 0
    expect(page.locator('#privacyReviewSave')).to_be_disabled()
    assert not [c for c in w.calls if c[0] == 'PATCH']
    page.wait_for_function('() => !refreshInFlight')
    page.clock.install()
    page.evaluate('schedule()')
    before = dialog.inner_html()
    previous = len([c for c in w.calls if c[0] == 'GET' and c[1] == '/admin/api/needs/privacy'])
    for _ in range(2):
        page.clock.run_for(31000)
        page.wait_for_function('() => !refreshInFlight')
        expect(dialog).to_be_visible()
        assert dialog.inner_html() == before
    assert len([c for c in w.calls if c[0] == 'GET' and c[1] == '/admin/api/needs/privacy']) >= previous + 2
    assert not [c for c in w.calls if c[0] == 'PATCH']
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)


def test_actual_review_requires_completion_note_and_distinct_evidence_then_reloads(privacy_page):
    w = privacy_page
    page = w.page
    dialog = open_review(w)
    receipt = w.store.list_privacy_requests()[0][0]['proof_hash']
    assert len(receipt) == 24
    page.locator('#privacyReviewStatus').select_option('completed')
    page.locator('#privacyReviewNotes').fill('short')
    page.locator('#privacyReviewProof').fill(receipt)
    expect(page.locator('#privacyReviewSave')).to_be_disabled()
    expect(page.locator('#privacyReviewValidation')).to_contain_text('An intake receipt is insufficient')
    assert not [c for c in w.calls if c[0] == 'PATCH']
    page.locator('#privacyReviewNotes').fill('Synthetic independent completion evidence was reviewed.')
    page.locator('#privacyReviewProof').fill('d' * 64)
    expect(page.locator('#privacyReviewSave')).to_be_enabled()
    page.locator('#privacyReviewSave').click()
    expect(page.locator('#privacyReviewMessage')).to_contain_text('Reviewed status recorded')
    expect(page.locator('#privacyReviewStatus')).to_have_value('completed')
    expect(dialog).to_contain_text('Reviewed evidence reference (SHA-256)')
    expect(page.locator('#privacyTable')).to_contain_text('completed')
    calls = [c for c in w.calls if c[0] == 'PATCH']
    assert len(calls) == 1
    assert calls[0][2] == {'status': 'completed', 'notes': 'Synthetic independent completion evidence was reviewed.', 'proof_hash': 'd' * 64}
    current = w.store.list_privacy_requests()[0][0]
    assert current['status'] == 'completed' and current['proof_hash'] == 'd' * 64
    assert current['completed_at']
    expect(page.locator('#privacyReviewStatus option[value="received"]')).to_have_attribute('disabled', '')
    expect(page.locator('#privacyReviewSave')).to_be_disabled()
    page.get_by_role('button', name='Close privacy review', exact=True).click()
    page.locator(f'[data-privacy-review-id="{w.identity}"]').click()
    expect(page.locator('#privacyReviewStatus')).to_have_value('completed')
    assert len([c for c in w.calls if c[0] == 'PATCH']) == 1


def test_unconfirmed_patch_is_never_retried_and_explicit_current_read_recovers(privacy_page):
    w = privacy_page
    page = w.page
    open_review(w)
    w.fail_after_patch = True
    page.locator('#privacyReviewStatus').select_option('processing')
    page.locator('#privacyReviewNotes').fill('Synthetic reviewed identity, processing begins.')
    page.locator('#privacyReviewSave').click()
    expect(page.locator('#privacyReviewMessage')).to_contain_text('response could not be confirmed')
    expect(page.locator('#privacyReviewSave')).to_be_disabled()
    assert len([c for c in w.calls if c[0] == 'PATCH']) == 1
    assert w.store.list_privacy_requests()[0][0]['status'] == 'processing'
    w.fail_after_patch = False
    page.get_by_role('button', name='Read current request', exact=True).click()
    expect(page.locator('#privacyReviewStatus')).to_have_value('processing')
    assert len([c for c in w.calls if c[0] == 'PATCH']) == 1


def test_session_change_closes_review_and_discards_late_response(privacy_page):
    w = privacy_page
    page = w.page
    held = []
    page.route('**/admin/api/needs/privacy?q=*&limit=50', lambda route: held.append(route))
    page.locator(f'[data-privacy-review-id="{w.identity}"]').click()
    expect(page.locator('#privacyReviewDialog')).to_be_visible()
    page.wait_for_function('() => document.querySelector("#privacyReviewMessage").textContent.includes("Reading")')
    assert held
    page.evaluate('''() => { token = ''; currentUser = null; updateUserUI(null, false); }''')
    expect(page.locator('#privacyReviewDialog')).to_have_count(0)
    held.pop().fulfill(status=200, content_type='application/json', body='{"items":[]}')
    expect(page.locator('#privacyReviewDialog')).to_have_count(0)
    assert not [c for c in w.calls if c[0] == 'PATCH']
