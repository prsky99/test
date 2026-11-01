"""Offline native review of runtime simulation and optional assistant sharing."""
import json
from types import SimpleNamespace

import httpx
from playwright.sync_api import expect
import pytest

from agent_market.workspace_ai_support import WorkspaceAISupport
from tests.test_advancement_browser import advancement_page
from tests.test_advancement_api import advancement_api
from tests.test_workspace_execution_api import private_api, execute
from tests.test_front_workflow_browser import browser


@pytest.fixture
def configured_page(monkeypatch, request):
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        value = {'answer': 'Review the saved snapshot and its selected agent before making a change.',
            'documents': ['safe-change-review'], 'changes': {'name': 'Reviewed assistant task'}}
        return httpx.Response(200, json={'message': {'content': json.dumps(value)}})
    engine = SimpleNamespace(ollama_url='http://assistant.test', generation_model='synthetic-model',
        http=httpx.Client(transport=httpx.MockTransport(respond)))
    original = WorkspaceAISupport.__init__
    def configured(self, access, supplied=None):
        original(self, access, engine)
    monkeypatch.setattr(WorkspaceAISupport, '__init__', configured)
    w = request.getfixturevalue('advancement_page')
    w.model_calls = calls
    w.page.context.set_offline(True)
    yield w
    engine.http.close()


def meter_state(w, ready, seconds=10):
    """Poll the stored meter; a Promise returned to wait_for_function is truthy before it resolves."""
    value = None
    for _ in range(int(seconds * 10)):
        value = w.page.evaluate("async path => (await api(path,{silent:true})).result", w.base + '/runtime-meter')
        if ready(value):
            return value
        w.page.wait_for_timeout(100)
    raise AssertionError('Runtime meter state was not reached: ' + json.dumps(value)[:300])


def test_native_runtime_policy_needs_fresh_consent_and_records_one_real_logical_run(configured_page):
    w = configured_page; dialog = w.page.locator('#advancementAdminDialog')
    dialog.get_by_role('button', name='Runtime simulation', exact=True).click()
    expect(dialog).to_contain_text('Logical runs: 0; dispatch attempts: 0')
    consent = dialog.get_by_label('Authorize this bounded simulation policy for one hour.')
    enabled = dialog.get_by_label('Enable simulation for newly authorized private runs in this workspace.')
    expect(consent).not_to_be_checked(); expect(enabled).not_to_be_checked()
    dialog.get_by_role('button', name='Save runtime simulation policy').click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_meter_policies').fetchone()[0] == 0
    consent.check(); enabled.check(); expect(consent).not_to_be_checked()
    consent.check(); dialog.get_by_role('button', name='Save runtime simulation policy').click()
    expect(consent).not_to_be_checked()
    # The save is asynchronous; admit the run only after the policy is stored.
    meter_state(w, lambda value: (value['policy'] or {}).get('enabled') is True)
    job, _ = execute(w)
    result = w.client.get(w.path+'/runs/'+job['id'], headers=w.headers['owner'])
    assert result.status_code == 200
    meter_state(w, lambda value: value['operations'] == 1 and value['outcomes'].get('succeeded') == 1)
    dialog.get_by_role('button', name='Runtime simulation', exact=True).click()
    expect(dialog).to_contain_text('Logical runs: 1; dispatch attempts: 1; simulated units: 1; balanced: yes.')
    assert w.calls.count('tools/call') == 1 and not w.model_calls and not w.errors and not w.external


def test_native_generated_guidance_shares_only_public_goal_and_needs_separate_apply(configured_page):
    w = configured_page; dialog = w.page.locator('#advancementAdminDialog')
    dialog.get_by_role('button', name='Draft support', exact=True).click()
    expect(dialog).to_contain_text('Optional generated guidance needs separate sharing consent')
    dialog.locator('select').nth(0).select_option(w.draft['id'])
    expect(dialog.locator('select').nth(1)).to_contain_text('Snapshot 1')
    with w.page.expect_response(lambda r: r.url.endswith('/snapshots/'+w.snapshot['id'])):
        dialog.locator('select').nth(1).select_option(w.snapshot['id'])
    goal = dialog.get_by_label('Public objective for optional generated guidance')
    goal.fill('Explain a public research workflow')
    share = dialog.get_by_label('Share only this public objective and the listed help documents with the configured assistant. Private draft content is excluded.')
    expect(share).not_to_be_checked()
    dialog.get_by_role('button', name='Generate guidance for review').click()
    assert not w.model_calls
    share.check(); goal.fill('Suggest a clearer draft name for a public news research workflow'); expect(share).not_to_be_checked()
    share.check(); dialog.get_by_role('button', name='Generate guidance for review').click()
    expect(dialog).to_contain_text('Generated guidance is unverified.')
    assert len(w.model_calls) == 1
    shared = json.loads(w.model_calls[0]['messages'][1]['content'])
    assert set(shared) == {'public_objective', 'documents'}
    assert w.draft['id'] not in json.dumps(w.model_calls) and w.snapshot['id'] not in json.dumps(w.model_calls)
    apply = dialog.get_by_label('Apply this exact generated proposal to a new private draft revision.')
    expect(apply).not_to_be_checked()
    dialog.get_by_role('button', name='Apply generated proposal').click()
    assert w.store._db.execute('SELECT revision FROM workspace_drafts WHERE id=?', (w.draft['id'],)).fetchone()[0] == 1
    apply.check(); dialog.get_by_role('button', name='Apply generated proposal').click()
    expect(dialog).to_contain_text('Reviewed private draft revision 2 saved.')
    assert not w.calls and not w.errors and not w.external


def test_native_document_guidance_uses_reviewed_sources_without_a_model_or_patch(configured_page):
    w=configured_page;dialog=w.page.locator('#advancementAdminDialog')
    dialog.get_by_role('button',name='Draft support',exact=True).click()
    dialog.locator('select').nth(0).select_option(w.draft['id'])
    expect(dialog.locator('select').nth(1)).to_contain_text('Snapshot 1')
    dialog.locator('select').nth(1).select_option(w.snapshot['id'])
    goal=dialog.get_by_label('Public objective for optional generated guidance')
    goal.fill('Explain why task updates need separate destination verification.')
    share=dialog.get_by_label('Share only this public objective and the listed help documents with the configured assistant. Private draft content is excluded.')
    share.check();dialog.get_by_role('button',name='Generate guidance for review').click()
    expect(dialog).to_contain_text('Documentation guidance.')
    expect(dialog).to_contain_text('Task updates are optional and purpose-specific.')
    expect(dialog).to_contain_text('A webhook or inbox must pass destination verification.')
    expect(dialog.get_by_role('button',name='Apply generated proposal')).to_have_count(0)
    assert not w.model_calls and not w.calls and not w.errors and not w.external
    assert w.store._db.execute('SELECT revision FROM workspace_drafts WHERE id=?',(w.draft['id'],)).fetchone()[0]==1
