# ruff: noqa: F401, F811 -- imported pytest fixtures
"""Task-first library placement and visible progress on actual isolated handlers."""
from pathlib import Path

from playwright.sync_api import expect
from agent_market.workspace_app_factory import AppFactory
from tests.test_workspace_prelaunch_browser import open_studio,ready,customer_flow,typed_release_world,typed_world,routing,browser
from tests.test_customer_typed_authoring import save_run
from tests.test_workflow_model_ollama import adapter

ROOT=Path('reports/workspace-responsive-ai-2026-10-20')


def test_primary_ai_action_library_search_themes_and_mobile(customer_flow,browser):
    x=customer_flow;proposer,_,model_client=adapter(x);x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer);flow,_=save_run(x)
    context,page,errors,_=open_studio(x,browser)
    try:
        ready(page);page.set_viewport_size({'width':1440,'height':900})
        page.evaluate('scrollTo(0,0)')
        assert page.locator('#model').evaluate('(n)=>n.getBoundingClientRect().bottom<innerHeight')
        page.set_viewport_size({'width':1920,'height':780})
        page.screenshot(path=str(ROOT/'studio-wide-check.png'))
        assert page.locator('#model').evaluate('(n)=>n.getBoundingClientRect().bottom<innerHeight'), page.locator('#model').bounding_box()
        page.set_viewport_size({'width':1440,'height':900})
        expect(page.locator('#library')).to_be_hidden()
        expect(page.locator('.workflow-card')).to_have_count(1)
        page.locator('#human-nav-library').click()
        expect(page).to_have_url('https://customer.test/customer/organizations/'+x.ws+'/flows#library')
        page.evaluate('async()=>{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))}')
        expect(page.locator('.workspace-sidebar a[aria-current=page]')).to_have_count(1)
        expect(page.locator('.workspace-sidebar a[aria-current=page]')).to_have_text('Workflows')
        page.locator('#workflow-search').fill('No matching workflow')
        expect(page.locator('#library-empty')).to_be_visible()
        page.locator('#workflow-search').fill(flow['name'])
        expect(page.locator('.workflow-card')).to_have_count(1)
        page.locator('.workflow-card').click()
        expect(page.locator('#workflow-state')).to_contain_text(flow['name'])
        expect(page.locator('#workspace-progress')).to_be_hidden()
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(ROOT/'studio-light.png'))
        page.locator('#workspace-theme').click();page.screenshot(path=str(ROOT/'studio-dark.png'))
        page.set_viewport_size({'width':390,'height':844});page.evaluate('scrollTo(0,0)')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'studio-mobile.png'))
        assert not errors
    finally:context.close();model_client.close()


def test_slow_ai_action_shows_progress_and_blocks_double_submission(customer_flow,browser):
    x=customer_flow;proposer,_,client=adapter(x);x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer)
    context,page,errors,requests=open_studio(x,browser);held=[]
    try:
        ready(page)
        page.locator('#objective').fill('Find public research in exactly two steps')
        page.locator('#model-consent').check()
        page.route('**/typed/reviews/model',lambda route:held.append(route))
        page.locator('#model').click()
        expect(page.locator('#workspace-progress')).to_contain_text('Generating a workflow')
        expect(page.locator('#model')).to_have_attribute('aria-busy','true')
        expect(page.locator('#model')).to_be_disabled()
        expect(page.locator('#model-consent')).to_be_disabled()
        expect(page.locator('#workspace-progress-elapsed')).not_to_have_text('0s')
        page.screenshot(path=str(ROOT/'studio-ai-progress.png'))
        assert len(held)==1
        held[0].fulfill(status=409,content_type='application/json',body='{}')
        expect(page.locator('#workspace-progress')).to_be_hidden()
        expect(page.locator('#status')).to_contain_text('No new workflow was saved')
        assert not x.core.typed.listing(x.ws,x.actor) and not errors
    finally:context.close();client.close()
