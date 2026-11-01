"""Connection lifetime guidance in isolated Chromium and intercepted API calls."""
import time
from pathlib import Path

from playwright.sync_api import expect

from tests.test_workspace_provider_connections_browser import connection_page  # noqa: F401
from tests.test_workspace_provider_connections import (  # noqa: F401
    payload, connections, customer_flow, typed_release_world, typed_world, routing,
)
from tests.test_front_workflow_browser import browser  # noqa: F401


def save_with_expiry(world, expiry):
    world.manager.save_key(world.ws, world.actor, world.rid, payload(world))
    with world.manager.access._tx(world.actor, write=True) as (db, _):
        data = world.manager._load(db, world.ws)
        data['records'][str(world.rid)]['expires'] = expiry
        world.manager._save(db, world.ws, data)


def test_expired_connection_prompts_reconnect_and_cannot_repeat_check(connection_page):
    world, page = connection_page
    save_with_expiry(world, time.time()-20)
    page.goto('https://customer.test/customer/organizations/'+world.ws+'/connections')
    page.get_by_role('button', name='Reconnect', exact=True).click()
    expect(page.locator('#provider-current')).to_contain_text('Expired')
    page.locator('#provider-verify-consent').check()
    expect(page.locator('#provider-verify')).to_be_disabled()
    expect(page.locator('#provider-key')).to_have_value('')
    assert world.manager.inspect(world.ws, world.actor, world.rid)['connection']['readiness']['execution_authorized'] is False
    page.screenshot(path=str(Path('reports/strategy-design-2.1-development-2026-10-26/connections-expired-desktop.png')),full_page=True)


def test_expiring_connection_has_readable_mobile_lifetime_guidance(connection_page):
    world, page = connection_page
    save_with_expiry(world, time.time()+240)
    page.set_viewport_size({'width':390,'height':844})
    page.goto('https://customer.test/customer/organizations/'+world.ws+'/connections')
    expect(page.locator('#provider-saved')).to_contain_text('Expires soon')
    page.locator('#provider-saved').get_by_role('button',name='Manage',exact=True).click()
    expect(page.locator('#provider-current')).to_contain_text('Replace this credential before a future scheduled task')
    expect(page.locator('#provider-execution')).to_contain_text('Separate workflow capability and execution approval')
    assert page.locator('#provider-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    page.screenshot(path=str(Path('reports/strategy-design-2.1-development-2026-10-26/connections-expiring-mobile.png')),full_page=True)
