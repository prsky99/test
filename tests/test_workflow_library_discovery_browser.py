"""Task-first journeys across 1,000 templates, including preview and cancellation."""
# ruff: noqa: F401,F811
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from playwright.sync_api import expect
from tests.test_pearl_frontend import ORIGIN,client,pearl_page,browser

OUT=Path(__file__).resolve().parents[1] / 'reports/workflow-template-discovery-redesign-2026-10-25'

@pytest.mark.parametrize('width,count',[(1440,25),(390,25),(1440,1000),(390,1000),(320,1000),(768,1000)])
def test_find_by_task_preview_cancel_choose_jump_and_recover(pearl_page,client,width,count):
    page,errors,calls=pearl_page
    sample=client.get('/api/workflows/templates').json()['templates'][0]
    templates=[];target_index=count-2
    for i in range(count):
        t=copy.deepcopy(sample);t.update(id=10000+i,name='Evidence pack '+str(i+1).zfill(4),description='Public reference information.',category='dev_tools' if i%2 else 'docs_knowledge',execution_availability={'available':i%10!=0,'message':'Recorded connection checks.'})
        templates.append(t)
    target=templates[target_index];target['description']='Find battery recycling research and source references.';target['execution_availability']['available']=True
    templates[-1]['name']='<img src=x onerror="window.libraryXss=1">'
    def catalog(route):
        query=parse_qs(urlsplit(route.request.url).query).get('q',[''])[0].lower()
        route.fulfill(json={'ok':True,'templates':[t for t in templates if not query or query in (t['name']+' '+t['description']).lower()]})
    page.route('**/api/workflows/templates*',catalog)
    page.set_viewport_size({'width':width,'height':900});page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text(str(count) if count<1000 else '1,000')
    assert page.locator('#pearlWorkflowChoices select').count()==0
    initial=page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')
    picker=page.locator('#pearlWorkflowTemplates').bounding_box();run=page.locator('#btnFrontRunWorkflow').bounding_box();assert run['y']<850
    page.locator('#pearlWorkflowSearch').fill('battery recycling');page.locator('#pearlWorkflowSearch').press('Enter')
    expect(page.locator('#frontTmplSearchInput')).to_be_focused()
    cards=page.locator('#frontTemplatesGrid .template-card');expect(cards).to_have_count(1)
    expect(cards).to_contain_text(target['name'])
    cards.get_by_role('button',name='Preview '+target['name'],exact=True).click()
    expect(page.locator('#wfLibraryPreview')).to_be_visible();expect(page.locator('#wfLibraryPreviewTitle')).to_have_text(target['name'])
    assert page.locator('#wfLibraryPreview .wf-library-pearl').count()>0
    for name in ('Close preview','Use this workflow'):
        bounds=page.locator('#wfLibraryPreview').get_by_role('button',name=name,exact=True).bounding_box()
        assert bounds['y']>=0 and bounds['y']+bounds['height']<=900
    assert page.evaluate('String(frontActiveTemplateId)')==initial
    page.keyboard.press('Escape');expect(page.locator('#wfLibraryPreview')).not_to_be_visible()
    expect(cards.get_by_role('button',name='Preview '+target['name'],exact=True)).to_be_focused()
    assert page.evaluate('String(frontActiveTemplateId)')==initial
    cards.get_by_role('button',name='Preview '+target['name'],exact=True).click()
    page.locator('#wfLibraryPreview').get_by_role('button',name='Use this workflow',exact=True).click()
    expect(page.locator('#frontWfActiveName')).to_have_text(target['name']);expect(page.locator('#frontWfActiveName')).to_be_focused()
    assert page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')==str(target['id'])
    page.locator('#btnFrontWfViewTemplates').click();page.locator('#wfLibraryClear').click()
    limit=4 if width<=700 else 8;expect(cards).to_have_count(limit)
    pager=page.locator('#uxTemplatePager-top')
    for name in ('Previous','Next'):
        assert pager.get_by_role('button',name=name,exact=True).evaluate('(n)=>{const r=document.createRange();r.selectNodeContents(n);return r.getBoundingClientRect().height<25}')
    pages=(count+limit-1)//limit
    pager.get_by_role('spinbutton').fill(str(pages));pager.get_by_role('button',name='Go',exact=True).click()
    expect(pager).to_have_attribute('data-page',str(pages));expect(cards).to_have_count(count-(pages-1)*limit)
    assert cards.locator('img').count()==0 and page.evaluate('typeof window.libraryXss')=='undefined'
    cards.filter(has_text='onerror').get_by_role('button',name='Preview '+templates[-1]['name'],exact=True).click()
    expect(page.locator('#wfLibraryPreviewTitle')).to_have_text(templates[-1]['name'])
    assert page.locator('#wfLibraryPreview img').count()==0 and page.evaluate('typeof window.libraryXss')=='undefined'
    page.keyboard.press('Escape')
    page.locator('#wfLibraryReady').check();expect(pager).to_have_attribute('data-page','1')
    assert not cards.locator('button:disabled').count()
    page.locator('#wfLibrarySort').select_option('name');expect(pager).to_have_attribute('data-page','1')
    category=page.locator('#frontTmplCategoryFilters [data-category="docs_knowledge"]')
    if not category.is_visible():page.locator('.wf-library-category-details summary').click()
    category.click();expect(category).to_have_attribute('aria-pressed','true')
    page.locator('#frontTmplSearchInput').fill('no-such-task');expect(cards).to_have_count(0);expect(pager).not_to_be_visible()
    page.locator('.wf-library-reset').click();expect(cards).to_have_count(limit)
    expect(page.locator('#frontTmplCategoryFilters [data-category="all"]')).to_have_class(re.compile('primary'))
    expect(category).not_to_have_class(re.compile('primary'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors
    OUT.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(OUT/f'library-{width}-{count}.png'),full_page=True)
    (OUT/f'journey-{width}-{count}.json').write_text(json.dumps({'width':width,'templates':count,'picker_height':picker['height'],'run_y':run['y'],'task_query':'battery recycling','unknown_name_found':target['name'],'direct_last_page':pages,'no_auto_execution':True,'errors':errors},indent=2))
    page.locator('#btnFrontWfViewCanvas').click();page.screenshot(path=str(OUT/f'execution-{width}-{count}.png'))

@pytest.mark.parametrize('width',[390,1440])
def test_keyboard_dark_preview_and_busy_run_preserve_selection(pearl_page,client,width):
    from tests.test_pearl_frontend import mock_selectable_templates
    page,errors,calls=pearl_page;mock_selectable_templates(page,client)
    page.set_viewport_size({'width':width,'height':900});page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text('3 published templates')
    page.get_by_role('button',name='Toggle dark theme',exact=True).click()
    selected=page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')
    page.locator('#btnFrontWfViewTemplates').click()
    card=page.locator('#frontTemplatesGrid .template-card').filter(has_not=page.locator('.wf-library-selected')).first
    preview=card.get_by_role('button').first;preview.focus();page.keyboard.press('Enter')
    expect(page.locator('#wfLibraryPreview')).to_be_visible()
    for _ in range(5):
        page.keyboard.press('Tab');assert page.locator('#wfLibraryPreview').evaluate('(n)=>n.contains(document.activeElement)')
    OUT.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(OUT/f'preview-dark-{width}.png'))
    page.keyboard.press('Escape');expect(preview).to_be_focused()
    page.evaluate('frontWorkflowRunning=true')
    card.get_by_role('button',name='Use workflow',exact=True).click()
    assert page.evaluate('String(frontActiveTemplateId)')==selected
    page.evaluate('frontWorkflowRunning=false')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors

@pytest.mark.parametrize('width',[390,1440])
def test_unchanged_results_still_reset_page_on_filter_sort_and_reset(pearl_page,client,width):
    page,errors,calls=pearl_page;sample=client.get('/api/workflows/templates').json()['templates'][0]
    values=[]
    for i in range(25):
        t=copy.deepcopy(sample);t.update(id=10000+i,name='Ready workflow '+str(i+1).zfill(3),execution_availability={'available':True,'message':'Isolated presentation fixture.'});values.append(t)
    page.route('**/api/workflows/templates',lambda route:route.fulfill(json={'ok':True,'templates':values}))
    page.set_viewport_size({'width':width,'height':900});page.goto(ORIGIN+'/#workflows');expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text('25 published templates')
    page.locator('#btnFrontWfViewTemplates').click();pager=page.locator('#uxTemplatePager-top')
    def last_page():
        target='7' if width==390 else '4';pager.get_by_role('spinbutton').fill(target);pager.get_by_role('button',name='Go',exact=True).click();expect(pager).to_have_attribute('data-page',target)
    last_page();page.locator('#wfLibraryReady').check();expect(pager).to_have_attribute('data-page','1')
    last_page();page.locator('#wfLibraryReady').uncheck();expect(pager).to_have_attribute('data-page','1')
    last_page();page.locator('#wfLibrarySort').select_option('name');expect(pager).to_have_attribute('data-page','1')
    last_page();page.locator('#wfLibrarySort').select_option('default');expect(pager).to_have_attribute('data-page','1')
    last_page();page.locator('.wf-library-reset').click();expect(pager).to_have_attribute('data-page','1')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors


def test_unchanged_catalog_refresh_preserves_page_input_and_preview_focus(pearl_page,client):
    page,errors,calls=pearl_page;sample=client.get('/api/workflows/templates').json()['templates'][0]
    values=[]
    for i in range(25):
        t=copy.deepcopy(sample);t.update(id=10000+i,name='Stable workflow '+str(i+1),execution_availability={'available':True,'message':'Isolated presentation fixture.'});values.append(t)
    pending=[];state={'hold':False}
    def catalog(route):
        if state['hold']:pending.append(route)
        else:route.fulfill(json={'ok':True,'templates':values})
    page.route('**/api/workflows/templates',catalog)
    page.goto(ORIGIN+'/#workflows');expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text('25 published templates')
    page.locator('#btnFrontWfViewTemplates').click();expect(page.locator('#frontTemplatesGrid .template-card')).to_have_count(8)
    # An unchanged revalidation must not redraw the form or replace focused cards.
    state['hold']=True;page.evaluate('window.refreshForTest=loadFrontTemplates(true);void 0')
    for _ in range(100):
        if pending:break
        page.wait_for_timeout(10)
    assert pending
    number=page.locator('#uxTemplatePager-top').get_by_role('spinbutton');number.fill('4')
    for route in pending:route.fulfill(json={'ok':True,'templates':values})
    pending.clear();page.evaluate('async()=>await window.refreshForTest')
    expect(number).to_have_value('4');expect(number).to_be_focused()
    preview=page.locator('#frontTemplatesGrid .template-card').first.get_by_role('button').first
    page.evaluate('window.refreshForTest=loadFrontTemplates(true);void 0')
    for _ in range(100):
        if pending:break
        page.wait_for_timeout(10)
    assert pending;preview.focus()
    for route in pending:route.fulfill(json={'ok':True,'templates':values})
    page.evaluate('async()=>await window.refreshForTest');expect(preview).to_be_focused()
    page.keyboard.press('Enter');expect(page.locator('#wfLibraryPreview')).to_be_visible()
    assert not errors
