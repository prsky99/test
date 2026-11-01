"""Native private reservation/review UI with explicitly synthetic staff evidence."""
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_workflow_quality_review_api import quality_api
from tests.test_workspace_execution_api import private_api,execute
from tests.test_front_workflow_browser import browser
from tests.test_workspace_browser import sign_in,select_space


@pytest.fixture
def quality_page(quality_api,browser):
    w=quality_api;context=browser.new_context();w.page=context.new_page();w.quality_context=context;w.quality_person=None;w.errors=[];w.external=[];w.requests=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='admin.test':w.external.append(req.url);return route.abort()
        w.requests.append((req.method,url.path,req.post_data))
        if url.path=='/admin/assets/workflow-quality-admin.js':return route.fulfill(status=200,content_type='application/javascript',body=Path('agent_market/gateway/workflow-quality-admin.js').read_text())
        response=w.client.request(req.method,url.path,headers=req.headers,content=req.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);w.page.on('pageerror',lambda error:w.errors.append(str(error)))
    yield w
    context.close()


def enter(w,person):
    if w.quality_person is not None:
        w.page.close();w.page=w.quality_context.new_page()
        w.page.on('pageerror',lambda error:w.errors.append(str(error)))
    w.quality_person=person
    sign_in(w,person);select_space(w,w.ws)
    if not w.page.evaluate('Boolean(window.WorkflowQualityReviewAdmin)'):
        w.page.add_script_tag(url='https://admin.test/admin/assets/workflow-quality-admin.js')
    w.page.evaluate('(ws)=>window.WorkflowQualityReviewAdmin.open(ws)',w.ws['id'])
    expect(w.page.locator('#workflowQualityDialog')).to_be_visible()
    return w.page.locator('#workflowQualityDialog')


def test_native_prerun_reservation_actual_manual_run_and_two_current_staff_reviews(quality_page):
    w=quality_page;dialog=enter(w,'owner')
    expect(dialog).to_contain_text('not configured')
    dialog.get_by_role('button',name='Reserve a new case before execution').click()
    dialog.locator('select').nth(0).select_option(w.draft['id'])
    expect(dialog.locator('select').nth(1)).to_contain_text('Snapshot 1')
    dialog.locator('select').nth(1).select_option(w.snapshot['id'])
    dialog.get_by_label('Frozen dataset SHA-256').fill('a'*64);dialog.get_by_label('Frozen case SHA-256').fill('b'*64)
    dialog.get_by_label('Separate source bundle SHA-256').fill('c'*64);dialog.get_by_label('Opaque source reference').fill('synthetic_staff_sources')
    dialog.locator('select').nth(2).select_option(str(w.users['owner']))
    dialog.locator('select').nth(3).select_option(str(w.users['outsider']))
    for person in ('editor','viewer'):dialog.get_by_label('Review account '+str(w.users[person]),exact=True).check()
    review=dialog.get_by_label('Reserve these exact hashes and separated account roles before creating the measured run. This is not independent holdout chronology proof.')
    expect(review).not_to_be_checked();review.check();dialog.get_by_role('button',name='Reserve pre-run case',exact=True).click()
    expect(dialog).to_contain_text('awaiting a new manual private run')
    assert not w.calls
    attack='Private result <img src=x onerror=window.__qualityXss=1>'
    w.remote.call_result={'content':[{'type':'text','text':attack}]}
    job,_=execute(w);assert w.calls.count('tools/call')==1
    dialog.get_by_label('New retained private run ID').fill(job['id']);dialog.get_by_role('button',name='Bind retained run created after reservation').click()
    expect(dialog).to_contain_text('retained run bound')
    assert dialog.get_by_role('button',name='Inspect assigned output').count()==0
    for person in ('editor','viewer'):
        dialog=enter(w,person)
        c=dialog.get_by_label('Open assigned private output and record this disclosure.');expect(c).not_to_be_checked();c.check()
        dialog.get_by_role('button',name='Inspect assigned output',exact=True).click()
        expect(dialog).to_contain_text(attack)
        assert dialog.locator('img,script,iframe').count()==0 and w.page.evaluate('window.__qualityXss||0')==0
        for select in dialog.locator('select').all():select.select_option('2')
        dialog.get_by_label('Source observation UTC (YYYY-MM-DDTHH:MM:SSZ)').fill(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        dialog.get_by_label('Assessment notes or adjudication reason').fill('Explicitly synthetic staff browser judgment')
        dialog.get_by_label('I reviewed the separately referenced source material.').check()
        dialog.get_by_label('I declare no conflict with this execution or assessment.').check()
        c=dialog.get_by_label('Record this explicit staff judgment. This does not certify expert qualification or provider truth.')
        expect(c).not_to_be_checked();c.check();dialog.get_by_role('button',name='Record assigned review',exact=True).click()
        expect(dialog).to_contain_text('retained run bound')
    dialog.get_by_role('button',name='Read assignment state',exact=True).click()
    expect(dialog).to_contain_text('judgments 2')
    expect(dialog).to_contain_text('qualified operating evidence not established')
    assert w.calls.count('tools/call')==1 and not w.errors and not w.external
