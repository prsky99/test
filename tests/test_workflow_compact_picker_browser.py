"""Discovery errors and same-template selection must retain the current work."""
# ruff: noqa: F401,F811
import pytest
from playwright.sync_api import expect
from tests.test_pearl_frontend import ORIGIN,client,pearl_page,browser


def test_library_search_error_recovers_without_losing_current_work(pearl_page,client):
    page,errors,calls=pearl_page
    from tests.test_pearl_frontend import mock_selectable_templates
    mock_selectable_templates(page,client)
    page.goto(ORIGIN+'/#workflows');expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    selected=page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')
    page.route('**/api/workflows/templates?*',lambda route:route.fulfill(status=503,json={'error':'private diagnostic'}))
    page.locator('#pearlWorkflowSearch').fill('news');page.locator('#pearlWorkflowSearch').press('Enter')
    expect(page.locator('#frontTemplatesGrid')).to_contain_text('search is unavailable')
    assert page.evaluate('String(frontActiveTemplateId)')==selected
    assert 'private diagnostic' not in page.locator('body').inner_text()
    page.locator('#wfLibraryClear').click();expect(page.locator('#frontTemplatesGrid .template-card')).to_have_count(3)
    page.locator('#frontTemplatesGrid [data-template-id="'+selected+'"]').get_by_role('button',name='Use workflow',exact=True).click()
    expect(page.locator('#frontWfCanvasView')).to_be_visible()
    assert page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')==selected
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors
