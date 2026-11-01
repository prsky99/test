"""Signed-in explanations with synthetic customers and no real provider calls."""
from playwright.sync_api import expect
from tests.test_workspace_human_studio_browser import launch,hub_world,customer_flow,typed_release_world,typed_world,routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_ai_button_explains_task_and_input_sharing_prerequisites(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        expect(page.locator('#model')).to_be_disabled()
        # An empty task still says why the button is disabled.
        expect(page.locator('#model-availability')).to_have_text('Describe a public task to begin.')
        expect(page.locator('#model')).to_have_attribute('aria-describedby','model-availability')
        expect(page.locator('#human-ai-help .context-help-body')).to_be_hidden()
        page.locator('#objective').fill('Find public battery recycling research in two steps')
        expect(page.locator('#model-availability')).to_be_visible()
        expect(page.locator('#model-availability')).to_contain_text('Allow input sharing')
        expect(page.locator('#model')).to_be_disabled()
        page.locator('#model-consent').check()
        expect(page.locator('#model')).to_be_enabled()
        expect(page.locator('#model-availability')).to_be_hidden()
        page.locator('#human-ai-help > summary').click()
        expect(page.locator('#human-ai-help .context-help-body')).to_contain_text('Review the proposed steps')
        page.evaluate("()=>{busy=true;humanStudio.operation='generate';sync();humanStudioSync()}")
        expect(page.locator('#model-availability')).to_contain_text('Creating your proposal')
        expect(page.locator('#model')).to_be_disabled()
        assert not calls and not errors
    finally:context.close();client.close()


def test_saved_library_does_not_call_repeated_steps_distinct_agents(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.evaluate('''()=>{libraryFlows=[{id:'tf_fixture',name:'Repeated research steps',active:true,step_count:2,updated:1792900000}];renderLibrary()}''')
        page.locator('#human-nav-library').click()
        expect(page.locator('.card-agent-count')).to_have_text('2 agent steps')
        expect(page.locator('#library-state')).to_have_text('1 custom workflow · 1 active')
        expect(page.locator('#human-library-help .context-help-body')).to_be_hidden()
        page.locator('#human-library-help > summary').click()
        expect(page.locator('#human-library-help')).to_contain_text('steps can reuse the same agent')
        expect(page.locator('#human-custom-library-heading')).to_be_visible()
        assert not calls and not errors
    finally:context.close();client.close()


def test_template_search_counts_matching_and_all_published_templates(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#human-nav-templates').click()
        expect(page.locator('#hub-state')).to_contain_text('templates')
        expect(page.locator('#hub-search-help .context-help-body')).to_be_hidden()
        page.locator('#hub-search-help > summary').click()
        expect(page.locator('#hub-search-help')).to_contain_text('agent step names')
        page.locator('#hub-search').fill('NoSuchTemplateForScopeCheck')
        expect(page.locator('#hub-state')).to_contain_text('0 of ')
        expect(page.locator('#hub-page')).to_contain_text('No matching templates')
        assert not calls and not errors
    finally:context.close();client.close()


def test_unavailable_capability_names_what_is_missing_and_keeps_the_request(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#objective').fill('Find AI news, then related papers')
        page.evaluate('''()=>showReview({state:'needs_details',missing_requirements:['News search'],
            message:'This goal needs capabilities that are not available in the reviewed workflow.'})''')
        expect(page.locator('#human-create-notice')).to_have_text(
            'Not available right now: News search. No workflow was saved and no credits were used. '
            'Try a research or documentation search, or start from a template.')
        expect(page.locator('#objective')).to_be_visible()
        expect(page.locator('#objective')).to_have_value('Find AI news, then related papers')
        page.locator('#objective').fill('Find battery recycling research')
        expect(page.locator('#human-create-notice')).to_be_hidden()
        assert not calls and not errors
    finally:context.close();client.close()


def test_examples_that_need_an_unavailable_capability_are_disabled(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.evaluate('''()=>humanExampleAvailability([{contract_id:'docs.search.v1',executable:true},
            {contract_id:'news.search.v1',executable:false}])''')
        news=page.get_by_role('button',name='Find recent news')
        expect(news).to_be_disabled()
        expect(news).to_have_attribute('title','Not available right now: News search')
        expect(page.get_by_role('button',name='Research a topic')).to_be_enabled()
        page.evaluate('''()=>humanExampleAvailability([{contract_id:'docs.search.v1',executable:true},
            {contract_id:'news.search.v1',executable:true}])''')
        expect(news).to_be_enabled()
        assert not calls and not errors
    finally:context.close();client.close()


def test_uncertain_outcome_offers_a_check_history_step_on_the_request_screen(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#objective').fill('Find battery recycling research')
        page.evaluate('()=>{uncertain=true;sync();humanStudioSync()}')
        expect(page.locator('#model-availability')).to_contain_text('Select Check history')
        recheck=page.locator('#human-check-history')
        expect(recheck).to_be_visible()
        recheck.click()
        expect(recheck).to_be_hidden()
        expect(page.locator('#model-availability')).not_to_contain_text('Check history')
        assert not errors
    finally:context.close();client.close()


def test_sign_in_expiry_is_announced_and_the_typed_task_survives_a_reload(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#objective').fill('Find battery recycling research')
        page.evaluate("()=>document.dispatchEvent(new CustomEvent('workspace-session-expires',{detail:{expires:Date.now()/1000+60,absolute:Date.now()/1000+43200}}))")
        expect(page.locator('#status')).to_contain_text('Your sign-in ends at')
        expect(page.locator('#status')).to_contain_text('Any action keeps you signed in')
        # Activity moves the end an hour out, so no new warning is scheduled now.
        page.evaluate("()=>{document.getElementById('status').textContent='';document.dispatchEvent(new Event('workspace-session-activity'))}")
        page.wait_for_timeout(300)
        assert 'Your sign-in ends at' not in page.locator('#status').text_content()
        # Near the 12-hour limit, activity cannot extend it and the warning says so.
        page.evaluate("()=>document.dispatchEvent(new CustomEvent('workspace-session-expires',{detail:{expires:Date.now()/1000+60,absolute:Date.now()/1000+60}}))")
        expect(page.locator('#status')).to_contain_text('12-hour limit')
        assert page.evaluate("()=>sessionStorage.getItem('workspace-objective-draft')")=='Find battery recycling research'
        assert not errors
    finally:context.close();client.close()
