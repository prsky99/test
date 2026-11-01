"""Private offline product inspection uses synthetic samples and no provider calls."""
from tests.browser_wait import pending_request
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from agent_market.workflow_product_semantics import ProductSemantics
from tests.test_admin_security_browser import browser
from tests.test_workflow_runtime_browser import studio, login
from tests.test_workflow_product_semantics import product_fixture

REPORT = Path('reports/advancement-product-semantics-2026-10-18')


def enter_product(page):
    login(page)
    page.evaluate('loadWorkflows()')
    expect(page.locator('#productSemanticsOpen')).to_be_enabled()
    page.locator('#productSemanticsOpen').click()
    expect(page.locator('#productSemanticsDialog')).to_be_visible()
    expect(page.locator('#productSemanticsValidate')).to_be_enabled()


def fill_sample(page, inputs=None, output=None):
    default_input, default_output, _ = product_fixture()
    inputs = inputs if inputs is not None else default_input
    output = output if output is not None else default_output
    page.locator('#productSemanticsInput').fill(json.dumps(inputs))
    page.locator('#productSemanticsOutput').fill(json.dumps(output))
    return {'input': inputs, 'output': output}


def validate_sample(page):
    page.locator('#productSemanticsValidate').click()
    expect(page.locator('#productSemanticsStatus')).to_contain_text('Offline sample structure is valid')


def evidence_counts(front):
    return {name: front.store.query('SELECT COUNT(*) FROM ' + name)[0][0] for name in
            ('workflow_runs', 'capability_evidence', 'capability_approvals')}


def test_empty_inspector_validates_only_supplied_sample_without_execution_or_evidence(studio):
    page, _, front, errors, requests = studio
    enter_product(page)
    page.set_viewport_size({'width': 1280, 'height': 1100})
    expect(page.locator('#productSemanticsInput')).to_have_value('')
    expect(page.locator('#productSemanticsOutput')).to_have_value('')
    expect(page.locator('#productSemanticsAvailability')).to_contain_text('readiness is not evaluated')
    before = evidence_counts(front)
    builder = page.evaluate('JSON.stringify(canvasGraph)')
    storage = page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).sort()')
    sample = fill_sample(page)
    validate_sample(page)
    rendered = page.locator('#productSemanticsResult').inner_text()
    assert 'Original quantity' in rendered and 'Normalized quantity' in rendered
    assert 'weight · mass' in rendered and 'capacity · storage' in rendered and 'undefined' not in rendered
    assert sample['output']['items'][0]['retrieved_at'] in rendered
    assert sample['output']['items'][0]['price']['amount'] in rendered
    assert 'sources and live provider behavior were not verified' in page.locator('#productSemanticsStatus').inner_text()
    assert evidence_counts(front) == before and page.evaluate('JSON.stringify(canvasGraph)') == builder
    assert page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).sort()') == storage
    posts = [path for method, path, _ in requests if method == 'POST' and path.startswith('/admin/api/workflow-product-semantics')]
    assert posts == ['/admin/api/workflow-product-semantics/validate']
    rect = page.locator('#productSemanticsDialog').bounding_box()
    assert rect and abs(rect['x'] + rect['width'] / 2 - page.viewport_size['width'] / 2) < 3
    page.locator('#productSemanticsDialog').evaluate('(dialog)=>{dialog.scrollTop=0;}')
    REPORT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(REPORT / 'admin-product-inspector.png'))
    page.locator('#productSemanticsResult section').first.scroll_into_view_if_needed()
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    expect(page.locator('#productSemanticsClose')).to_be_in_viewport()
    assert page.locator('#productSemanticsClose').evaluate('(button)=>{const r=button.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===button;}')
    page.screenshot(path=str(REPORT / 'admin-product-normalized-sample.png'))
    assert not errors


@pytest.mark.parametrize('difference', ['currency', 'basis', 'missing', 'measurement_time', 'price_time'])
def test_incompatible_or_missing_price_evidence_is_explicit_and_not_converted(studio, difference):
    page, _, _, errors, _ = studio
    enter_product(page)
    inputs, output, _ = product_fixture()
    output = copy.deepcopy(output)
    if difference == 'currency':
        output['items'][1]['price']['currency'] = 'EUR' if output['items'][0]['price']['currency'] != 'EUR' else 'USD'
    elif difference == 'basis':
        output['items'][1]['price']['basis'] = {'unit': 'pack', 'quantity': '1', 'pack_count': 2}
    elif difference == 'missing':
        output['items'][1]['price'] = {'status': 'missing', 'amount': None, 'currency': None, 'basis': None, 'source_url': None, 'observed_at': None}
        measurement = output['items'][1]['measurements'][0]
        measurement.update(status='missing', quantity=None, source_url=None, observed_at=None)
        output['partial'] = True
    else:
        evidence = output['items'][1]['measurements'][0] if difference == 'measurement_time' else output['items'][1]['price']
        evidence['observed_at'] = (datetime.fromisoformat(evidence['observed_at'].replace('Z', '+00:00')) - timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')
    fill_sample(page, inputs, output)
    validate_sample(page)
    if difference == 'currency': expect(page.locator('#productSemanticsResult')).to_contain_text('Incompatible currencies')
    elif difference == 'basis': expect(page.locator('#productSemanticsResult')).to_contain_text('Incompatible price bases')
    elif difference == 'missing':
        expect(page.locator('#productSemanticsResult')).to_contain_text('Partial sample')
        expect(page.locator('#productSemanticsResult')).to_contain_text('Missing price evidence')
        expect(page.locator('#productSemanticsResult')).to_contain_text('Missing evidence; no compatible value pair')
    else:
        expect(page.locator('#productSemanticsResult')).to_contain_text('Incompatible observation times')
        expect(page.locator('#productSemanticsResult')).to_contain_text('Different reported observation instants')
    assert 'winner' not in page.locator('#productSemanticsResult').inner_text().lower()
    assert not errors


@pytest.mark.parametrize('raw', ['', '[]', '{"value":1e999}', '{invalid'])
def test_invalid_local_json_is_never_submitted(studio, raw):
    page, _, _, errors, requests = studio
    enter_product(page)
    page.locator('#productSemanticsInput').fill(raw)
    page.locator('#productSemanticsOutput').fill('{}')
    page.locator('#productSemanticsValidate').click()
    expect(page.locator('#productSemanticsStatus')).to_contain_text('sample was not submitted')
    assert not [path for method, path, _ in requests if method == 'POST' and path.endswith('/workflow-product-semantics/validate')]
    assert not errors


@pytest.mark.parametrize('escaped', [False, True])
def test_nested_duplicate_keys_reach_strict_json_reader_without_lossy_reserialization(studio, escaped):
    page, _, _, errors, requests = studio
    enter_product(page)
    inputs, output, _ = product_fixture()
    amount = output['items'][0]['price']['amount']
    repeated = '"\\u0061mount"' if escaped else '"amount"'
    duplicate = '"amount": "999.00", ' + repeated + ': ' + json.dumps(amount)
    raw_output = json.dumps(output).replace('"amount": ' + json.dumps(amount), duplicate, 1)
    page.locator('#productSemanticsInput').fill(json.dumps(inputs))
    page.locator('#productSemanticsOutput').fill(raw_output)
    with page.expect_response('**/workflow-product-semantics/validate') as response:
        page.locator('#productSemanticsValidate').click()
    assert response.value.status == 400, response.value.text()
    expect(page.locator('#productSemanticsStatus')).to_contain_text('sample could not be validated')
    submitted = [body for method, path, body in requests if method == 'POST' and path.endswith('/workflow-product-semantics/validate')]
    assert len(submitted) == 1 and duplicate in submitted[0]
    assert page.locator('#productSemanticsResult').inner_text() == '' and not errors


@pytest.mark.parametrize('change', ['input', 'output', 'close', 'escape', 'role', 'token'])
def test_sample_result_is_cleared_when_data_or_private_context_changes(studio, change):
    page, _, _, errors, _ = studio
    enter_product(page); fill_sample(page); validate_sample(page)
    if change in ('input', 'output'):
        page.locator('#productSemantics' + change.title()).fill('{}')
    elif change == 'close': page.locator('#productSemanticsClose').click()
    elif change == 'escape': page.keyboard.press('Escape')
    elif change == 'role': page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    else: page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    assert page.locator('#productSemanticsResult').inner_text() == ''
    if change not in ('input', 'output'):
        expect(page.locator('#productSemanticsInput')).to_have_value('')
        expect(page.locator('#productSemanticsOutput')).to_have_value('')
        expect(page.locator('#productSemanticsDialog')).to_be_hidden()
    assert not errors


@pytest.mark.parametrize('change', ['input', 'close', 'logout'])
def test_late_sample_reply_cannot_restore_result_after_edits_close_or_confirmed_logout(studio, change):
    page, _, _, errors, _ = studio
    enter_product(page); body = fill_sample(page)
    pending, logouts = [], []
    page.route('**/workflow-product-semantics/validate', lambda route: pending.append(route))
    def hold_logout(route):
        logouts.append(route)
        page.evaluate('globalThis.__productLogoutHeld=true')
    page.route('**/admin/api/auth/logout', hold_logout)
    page.evaluate('''()=>{
      globalThis.__productValidationSettled=false;
      const button=document.getElementById('productSemanticsValidate'), original=button.onclick;
      button.onclick=async(...args)=>{try{return await original(...args);}finally{globalThis.__productValidationSettled=true;}};
    }''')
    page.locator('#productSemanticsValidate').click(); pending_request(page,pending)
    if change == 'input': page.locator('#productSemanticsInput').fill('{}')
    elif change == 'close': page.locator('#productSemanticsClose').click()
    else:
        page.on('dialog', lambda dialog: dialog.accept())
        page.evaluate('document.getElementById("logoutBtn").click()')
        page.wait_for_function('()=>globalThis.__productLogoutHeld===true')
    pending[0].fulfill(status=200, content_type='application/json', body=json.dumps(ProductSemantics().validate(body)))
    page.wait_for_function('()=>globalThis.__productValidationSettled===true')
    assert page.locator('#productSemanticsResult').inner_text() == ''
    if change == 'input': expect(page.locator('#productSemanticsValidate')).to_be_enabled()
    if logouts:
        logouts[0].fulfill(status=200, content_type='application/json', body='{"ok":true}')
        expect(page.locator('#adminLoginModal')).to_be_visible()
        expect(page.locator('#productSemanticsInput')).to_have_value('')
    assert not errors


def test_old_backend_marker_keeps_inspection_disabled_without_new_requests(studio):
    page, identity, front, errors, requests = studio
    page.route('**/admin/api/workflows?limit=100', lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'workflows': [front.store.get_workflow(identity)]})))
    login(page); page.evaluate('loadWorkflows()')
    expect(page.locator('#productSemanticsOpen')).to_be_disabled()
    expect(page.locator('#capabilityProductV2Option')).to_have_js_property('disabled', True)
    page.evaluate('openProductSemantics()')
    assert not [path for _, path, _ in requests if '/workflow-product-semantics/' in path]
    expect(page.locator('#wfActiveSelect')).to_be_visible()
    assert not errors


def test_v2_private_contract_selection_is_explicit_and_never_approves_or_calls_a_provider(studio):
    page, _, front, errors, requests = studio
    login(page); page.evaluate('loadWorkflows()')
    expect(page.locator('#productSemanticsOpen')).to_be_enabled()
    before = evidence_counts(front)
    original = page.locator('#capabilityInput').input_value()
    page.locator('[data-tab="errors"]').click()
    page.locator('#capabilityContract').evaluate('(select)=>{select.closest("details").open=true;}')
    page.locator('#capabilityContract').select_option('products.compare.v2')
    expect(page.locator('#capabilityProductV2Notice')).to_be_visible()
    expect(page.locator('#capabilityProductV2Notice')).to_contain_text('real contract test calls that provider')
    assert page.locator('#capabilityInput').input_value() == original
    assert evidence_counts(front) == before
    assert not [path for method, path, _ in requests if method == 'POST' and '/contracts/' in path]
    assert not errors


@pytest.mark.parametrize('escaped', [False, True])
def test_explicit_v2_test_preserves_duplicate_input_keys_for_server_rejection_before_provider_call(studio, monkeypatch, escaped):
    page, _, front, errors, requests = studio
    calls = []
    async def refuse_provider(*args, **kwargs):
        calls.append(True)
        raise AssertionError('No provider call is permitted for duplicate JSON input')
    monkeypatch.setattr(front.proxy, 'execute', refuse_provider)
    login(page); page.evaluate('loadWorkflows()')
    expect(page.locator('#productSemanticsOpen')).to_be_enabled()
    before = evidence_counts(front)
    inputs, _, _ = product_fixture()
    identifier = inputs['criteria'][0]['criterion_id']
    repeated = '"criterion_\\u0069d"' if escaped else '"criterion_id"'
    duplicate = '"criterion_id": "discarded", ' + repeated + ': ' + json.dumps(identifier)
    original = json.dumps(inputs).replace('"criterion_id": ' + json.dumps(identifier), duplicate, 1)
    resource = front.store.query("SELECT id FROM resources WHERE kind='mcp' ORDER BY id LIMIT 1")[0]['id']
    page.locator('[data-tab="errors"]').click()
    page.locator('#capabilityContract').evaluate('(select)=>{select.closest("details").open=true;}')
    page.locator('#capabilityContract').select_option('products.compare.v2')
    page.locator('#connectionResourceId').fill(str(resource))
    page.locator('#capabilityInput').fill(original)
    with page.expect_response('**/contracts/products.compare.v2/test') as response:
        page.locator('#capabilityTest').click()
    assert response.value.status == 400, response.value.text()
    submitted = [body for method, path, body in requests if method == 'POST' and path.endswith('/contracts/products.compare.v2/test')]
    assert len(submitted) == 1 and duplicate in submitted[0]
    assert not calls and evidence_counts(front) == before and not errors


def test_product_markup_is_text_and_sources_are_not_fetched(studio):
    page, _, _, errors, requests = studio
    enter_product(page)
    inputs, output, _ = product_fixture()
    output['items'][0]['name'] = '<img src="https://malicious.example/x" onerror="globalThis.productInjected=true">'
    fill_sample(page, inputs, output); validate_sample(page)
    expect(page.locator('#productSemanticsResult')).to_contain_text('<img src=')
    assert page.locator('#productSemanticsResult img').count() == 0 and page.evaluate('globalThis.productInjected!==true')
    assert page.locator('#productSemanticsResult a').count() == 0
    assert not [path for _, path, _ in requests if 'malicious.example' in path]
    assert not errors


def test_private_error_details_are_not_rendered_as_sample_findings(studio):
    page, _, _, errors, _ = studio
    enter_product(page); fill_sample(page)
    page.route('**/workflow-product-semantics/validate', lambda route: route.fulfill(status=500, content_type='application/json', body='{"detail":"private-runtime-secret /private/deployment/path"}'))
    page.locator('#productSemanticsValidate').click()
    expect(page.locator('#productSemanticsStatus')).to_contain_text('sample could not be validated')
    assert 'private-runtime-secret' not in page.locator('body').inner_text()
    assert page.locator('#productSemanticsResult').inner_text() == '' and not errors


def test_expired_session_clears_pasted_data_and_closes_private_inspector(studio):
    page, _, _, errors, _ = studio
    enter_product(page); fill_sample(page)
    page.route('**/workflow-product-semantics/validate', lambda route: route.fulfill(status=401, content_type='application/json', body='{"detail":"Session expired"}'))
    page.locator('#productSemanticsValidate').click()
    expect(page.locator('#productSemanticsDialog')).to_be_hidden()
    expect(page.locator('#adminLoginModal')).to_be_visible()
    expect(page.locator('#productSemanticsInput')).to_have_value('')
    expect(page.locator('#productSemanticsOutput')).to_have_value('')
    assert page.locator('#productSemanticsResult').inner_text() == '' and not errors
