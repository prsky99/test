"""Native dashboard whole-graph review uses intercepted synthetic MCP only."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

from agent_market.workflow_product_semantics import CONTRACT_ID
from tests.test_workspace_execution_api import private_api
from tests.test_workflow_product_composer import product_world
from tests.test_front_workflow_browser import browser


def definition(x):
    first = {'id': 'first', 'resource_id': x.w.rid, 'contract_id': CONTRACT_ID, 'input': copy.deepcopy(x.inputs),
             'bindings': {}, 'after': [], 'when': None}
    second = copy.deepcopy(first); second.update(id='followup', after=['first'],
        when={'node_id': 'first', 'path': ['partial'], 'equals': False},
        bindings={'query': {'node_id': 'first', 'path': ['items', 0, 'name']}})
    del second['input']['query']
    return {'nodes': [first, second]}


def launch(x, browser, *, hold=False):
    context = browser.new_context(offline=True)
    context.add_init_script('sessionStorage.setItem("adminToken",' + json.dumps(x.w.headers['owner']['Authorization'][7:]) + ');')
    page = context.new_page(); errors = []; external = []; held = []
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test': external.append(request.url); return route.abort()
        if hold and url.path.endswith('/prepare') and '/typed-flows/' in url.path:
            held.append(route); return
        response = x.w.client.request(request.method, url.path, headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, headers={k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}, body=response.content)
    context.route('**/*', serve); page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('https://admin.test/admin/ui#workspaces'); expect(page.locator('#workspaceSelect')).to_be_enabled()
    page.locator('#workspaceSelect').select_option(x.ws)
    page.locator('#workspaceFlowMount').get_by_role('button', name='Compose private typed workflow').click()
    dialog = page.get_by_role('dialog', name='Private typed workflows')
    expect(dialog).to_be_visible(); expect(dialog.get_by_role('status')).to_contain_text('Up to ten')
    dialog.get_by_label('Workflow name', exact=True).fill('Private product discovery sequence')
    dialog.get_by_label('Typed graph definition').fill(json.dumps(definition(x)))
    return context, page, dialog, errors, external, held


def save(dialog):
    dialog.get_by_role('button', name='Save new immutable version').click()
    expect(dialog.get_by_role('status')).to_contain_text('Private version saved.')


def test_actual_dashboard_graph_review_runs_two_nodes_once_and_clears_consent(product_world, browser):
    x = product_world; context, page, dialog, errors, external, _ = launch(x, browser)
    before = x.w.calls.count('tools/call'); save(dialog)
    assert x.w.calls.count('tools/call') == before
    dialog.get_by_role('button', name='Review entire workflow').click()
    expect(dialog.get_by_role('status')).to_contain_text('Review every agent')
    expect(dialog).to_contain_text('Prior-output bindings:')
    expect(dialog).to_contain_text('followup → agent')
    consent = dialog.get_by_role('checkbox', name='I allow the exact literals', exact=False)
    expect(consent).not_to_be_checked(); expect(dialog.get_by_role('button', name='Run reviewed workflow')).to_be_disabled()
    assert x.w.calls.count('tools/call') == before
    consent.check(); dialog.get_by_role('button', name='Run reviewed workflow').click()
    expect(dialog.get_by_role('status')).to_contain_text('Private run recorded: succeeded', timeout=20000)
    expect(dialog).to_contain_text('Synthetic product 0')
    assert x.w.calls.count('tools/call') == before + 2
    expect(consent).not_to_be_checked(); expect(dialog.get_by_role('button', name='Run reviewed workflow')).to_be_disabled()
    assert dialog.locator('pre a,pre img,pre script').count() == 0
    assert x.w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
    assert not errors and not external
    target = Path('reports/advancement-completion-2026-10-18'); target.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({'width': 1280, 'height': 1000}); page.screenshot(path=str(target / 'private-typed-flow-review.png'))
    context.close()


def test_editing_graph_clears_prepared_whole_graph_consent_without_call(product_world, browser):
    x = product_world; context, page, dialog, errors, external, _ = launch(x, browser)
    save(dialog); dialog.get_by_role('button', name='Review entire workflow').click()
    consent = dialog.get_by_role('checkbox', name='I allow the exact literals', exact=False)
    expect(dialog.get_by_role('status')).to_contain_text('Review every agent'); consent.check()
    dialog.get_by_label('Workflow name', exact=True).fill('Changed local objective')
    expect(consent).not_to_be_checked(); expect(dialog.get_by_role('button', name='Run reviewed workflow')).to_be_disabled()
    assert not x.w.calls and not errors and not external
    context.close()


def test_closed_dialog_ignores_late_preparation_and_never_calls_provider(product_world, browser):
    x = product_world; context, page, dialog, errors, external, held = launch(x, browser, hold=True)
    save(dialog); dialog.get_by_role('button', name='Review entire workflow').click()
    page.wait_for_function('() => [...document.querySelectorAll("button")].some(b=>b.textContent==="Review entire workflow"&&b.disabled)')
    dialog.get_by_role('button', name='Close', exact=True).click(); assert held
    route = held[0]; request = route.request
    response = x.w.client.request(request.method, urlsplit(request.url).path, headers=request.headers, content=request.post_data)
    try: route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
    except Exception: pass
    assert page.get_by_role('dialog', name='Private typed workflows').count() == 0
    assert not x.w.calls and not errors and not external
    context.close()
