"""Provider lifecycle controls use isolated staff sessions and no endpoint GET."""
from playwright.sync_api import expect

from tests.test_workspace_browser import workspace_browser, sign_in, select_space, make_space
from tests.test_front_workflow_browser import browser


def test_owner_rechallenge_retires_old_nonce_and_requires_separate_unchecked_verification(workspace_browser):
    w = workspace_browser; w.page.context.set_offline(True); ws = make_space(w)
    rid = w.store.upsert_resource({'key': 'mcp:https://provider-fixture.invalid/mcp', 'source': 'mcp-registry', 'kind': 'mcp',
        'url': 'https://provider-fixture.invalid/mcp', 'name': 'Synthetic endpoint', 'description': 'Synthetic control proof',
        'category': 'dev_tools', 'networks': [], 'price_usdc': 0, 'details': {}})
    sign_in(w); select_space(w, ws); w.page.locator('#workspaceIdentity').click()
    dialog = w.page.get_by_role('dialog', name='Customer access and provider control')
    expect(dialog.get_by_role('status')).to_contain_text('Customer access is explicit.')
    dialog.get_by_label('Registered resource ID').fill(str(rid)); dialog.get_by_role('button', name='Prepare HTTPS challenge').click()
    expect(dialog.locator('pre')).to_contain_text('provider-https-control-v1')
    original = dialog.locator('pre').inner_text()
    dialog.get_by_role('button', name='Refresh recorded state').click()
    expect(dialog.get_by_role('button', name='Prepare fresh challenge')).to_be_visible()
    dialog.get_by_role('button', name='Prepare fresh challenge').click()
    expect(dialog.get_by_role('status')).to_contain_text('A fresh challenge is required.')
    assert dialog.locator('pre').inner_text() != original
    expect(dialog.get_by_role('checkbox', name='I authorize one HTTPS request', exact=False)).not_to_be_checked()
    expect(dialog.get_by_role('button', name='Verify endpoint control')).to_be_disabled()
    assert w.store.query("SELECT COUNT(*) FROM provider_control_claims WHERE status='superseded'")[0][0] == 1
    assert w.store.query("SELECT COUNT(*) FROM provider_control_claims WHERE status='pending'")[0][0] == 1
    assert not any(method == 'POST' and path.endswith('/provider-claims/verify') for method, path, _ in w.requests)
    dialog.get_by_label('Transfer target workspace ID').fill('ws_' + 'a' * 32)
    dialog.get_by_label('Received transfer ID').fill('pt_' + 'b' * 32)
    dialog.get_by_role('button', name='Close', exact=True).click()
    assert not w.external and not w.errors
