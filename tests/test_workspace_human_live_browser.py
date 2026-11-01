"""Real configured local model, new UI and isolated customer/agent transports."""
# ruff: noqa: F401,F811
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_workspace_generation_diverse_live import matrix_world,customer_flow,typed_release_world,typed_world,routing
from tests.test_front_workflow_browser import browser
from tests.test_workspace_human_studio_browser import launch,approve

pytestmark=pytest.mark.skipif(os.environ.get('RUN_HUMAN_MODEL_LIVE')!='1',reason='Explicit configured model opt-in required')


@pytest.mark.parametrize('name,goal,count',[
 ('research10','Find public Rust documentation using exactly ten connected steps.',10),
 ('news-research','Find battery recycling news then supporting documentation in exactly two steps.',2),
 ('topics3','Find documentation for 3 topics: Docker, Kubernetes and Terraform',3),
])
def test_real_generation_review_save_and_run_in_guided_ui(matrix_world,browser,name,goal,count):
    x,trace=matrix_world
    context,page,errors,requests,calls,client=launch(x,browser,real_model=True)
    try:
        page.locator('#objective').fill(goal);page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#human-save')).to_be_enabled(timeout=60000)
        expect(page.locator('#pearl-flow-preview .pearl-flow-node')).to_have_count(count)
        if count>3:
            expect(page.locator('#pearl-flow-preview .pearl-flow-node:visible')).to_have_count(3)
            page.locator('#human-show-steps').click()
            expect(page.locator('#pearl-flow-preview .pearl-flow-node:visible')).to_have_count(count)
        page.locator('#human-save').click();approve(page,'save');expect(page.locator('#human-try')).to_be_enabled()
        page.locator('#human-try').click();approve(page,'run')
        expect(page.locator('#results')).to_contain_text('All steps completed',timeout=30000)
        assert len(calls)==1 and not errors,errors
        assert not page.locator('pre:visible').count()
        page.screenshot(path=str(Path('reports/workspace-human-centered-2026-10-25')/(name+'-live.png')),full_page=True)
    finally:context.close();client.close()
