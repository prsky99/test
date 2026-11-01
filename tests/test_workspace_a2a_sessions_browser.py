"""Fresh consent is required for each A2A session turn or reconnection."""
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_remote_a2a import remote
from tests.test_workspace_remote_a2a_browser import task_page,submit
from tests.test_workspace_a2a_sessions import stream_provider


def test_private_a2a_input_required_continues_same_context_once(task_page):
    x=task_page;stream_provider(x);submit(x)
    page=x.page
    expect(page.locator('#remoteA2AContinuation')).to_be_visible()
    expect(page.locator('#remoteA2AcontinueOnce')).to_be_disabled()
    page.locator('#remoteA2AContinuation').fill('Reviewed second input')
    page.locator('#remoteA2AcontinueConsent').check()
    page.locator('#remoteA2AContinuation').fill('Changed second input')
    expect(page.locator('#remoteA2AcontinueConsent')).not_to_be_checked()
    page.locator('#remoteA2AcontinueConsent').check();page.locator('#remoteA2AcontinueOnce').click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('One new input was recorded for the same task context.')
    assert len(x.calls)==2 and x.calls[-1]['params']['message']['contextId']=='session-context'
    assert not x.errors and not x.external


def test_private_a2a_interrupted_stream_requires_fresh_resume_consent(task_page):
    x=task_page;stream_provider(x,disconnect=True);submit(x)
    page=x.page
    expect(page.locator('#remoteA2AresumeOnce')).to_be_disabled()
    page.locator('#remoteA2AresumeConsent').check();page.locator('#remoteA2AresumeOnce').click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('One stream reconnection was recorded for the same task.')
    assert [call['method'] for call in x.calls]==['message/stream','tasks/resubscribe']
    assert not x.errors and not x.external
