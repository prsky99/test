"""Desktop purpose-grant controls use the existing native modal and API."""
from playwright.sync_api import expect

from agent_market.workspace_machine_automation import MachineUpdateAutomation
from tests.test_workspace_machine_updates_browser import machine_page  # noqa: F401
from tests.test_workspace_machine_updates import machine, provider, subscribe  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_workspace_machine_automation import source_for


def test_automatic_metadata_grant_requires_own_consent_and_withdrawal_stops_consumer(machine_page):
    page, w, calls, errors = machine_page
    source_for(w)
    automation = MachineUpdateAutomation(w.machine, enabled=True)
    subscription = subscribe(w)
    page.evaluate('ws=>WorkspaceMachineUpdatesAdmin.open(ws)', w.ws)
    dialog = page.locator('#workspaceMachineUpdatesDialog')
    expect(dialog).to_be_visible()
    card = dialog.locator('section').filter(has=page.get_by_role('heading', name=subscription['id'], exact=True))
    submit = card.get_by_role('button', name='Authorize bounded automatic updates', exact=True)
    expect(submit).to_be_visible()
    submit.click()
    assert not any(method == 'POST' for method, _ in calls)
    card.get_by_label('Authorize only changed evidence metadata', exact=False).check()
    submit.click()
    expect(card).to_contain_text('Automatic metadata grant: up to 10 notices')
    assert automation.tick()['accepted'] == 1
    assert automation.tick()['accepted'] == 0 and len(w.receiver.calls) == 1
    card.get_by_label('Withdraw this subscription independently', exact=False).check()
    card.get_by_role('button', name='Withdraw subscription', exact=True).click()
    expect(card).to_contain_text('State: withdrawn.')
    assert automation.tick()['accepted'] == 0 and len(w.receiver.calls) == 1
    assert not errors
