"""QA10 focus, actual hit targets, help search and progressive page content."""
# ruff: noqa: F811 -- pytest fixture imports.
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

OUT = Path('reports/qa10-remediation-2026-10-29')


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
def test_focus_and_target_assessment(chat_page):
    page, _, _, errors, _ = chat_page
    results = []
    for width, theme in ((1366, 'light'), (390, 'light'), (320, 'light'), (1366, 'dark')):
        page.set_viewport_size({'width': width, 'height': 900})
        page.emulate_media(color_scheme=theme)
        for name in ('index', 'explore', 'chat', 'test', 'workflows', 'learn', 'list-agent', 'about'):
            page.goto('https://agentconcierge.biz/new/en/' + name + '.html')
            expect(page.locator('main h1:visible')).to_have_count(1)
            page.wait_for_timeout(100)
            small = page.evaluate('''() => [...document.querySelectorAll('a,button,input,select,textarea,[role=button],summary')].flatMap(e=>{
              const r=e.getBoundingClientRect(),s=getComputedStyle(e);
              if(!r.width||!r.height||s.display==='none'||s.visibility==='hidden'||e.closest('[aria-hidden="true"]'))return [];
              if(e.tagName==='A'&&s.display==='inline')return [];
              if(r.width>=24&&r.height>=24)return [];
              const labels=[...(e.labels||[])].map(l=>{const r=l.getBoundingClientRect();return {w:r.width,h:r.height}});
              return [{tag:e.tagName,id:e.id,classes:e.className,text:(e.textContent||e.getAttribute('aria-label')||'').trim().slice(0,40),w:r.width,h:r.height,labels}];
            })''')
            result = {'page': name, 'width': width, 'theme': theme, 'small': small,
                'overflow': page.evaluate('document.documentElement.scrollWidth-innerWidth')}
            if name == 'chat':
                page.locator('#chatInput').focus()
                focus = page.locator('#chatInput').evaluate('e=>{const s=getComputedStyle(e);return {style:s.outlineStyle,width:parseFloat(s.outlineWidth),color:s.outlineColor}}')
                assert focus['style'] != 'none' and focus['width'] >= 2, focus
                result['focus'] = focus
                page.screenshot(path=str(OUT / f'chat-focus-{width}-{theme}.png'))
            results.append(result)
    (OUT / 'focus-target-assessment.json').write_text(json.dumps(results, indent=2) + '\n')
    assert all(row['overflow'] <= 1 for row in results), results
    effective=[e for row in results for e in row['small'] if 'skip-link' not in e['classes'].split() and not any(label['w']>=24 and label['h']>=24 for label in e['labels'])]
    assert not effective,effective
    assert not errors, errors


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
def test_guide_search_selects_a_topic_and_recovers_from_empty_results(chat_page):
    page, _, _, errors, _ = chat_page
    page.goto('https://agentconcierge.biz/new/en/learn.html')
    field = page.get_by_label('Search learning guides')
    field.fill('evidence')
    expect(page.locator('.learn-guide-results button').first).to_be_visible()
    page.locator('.learn-guide-results button').first.click()
    expect(page.locator('.reference-learn-panels [role=tabpanel]:visible')).to_have_count(1)
    field.fill('zzqqnotatopic')
    expect(page.locator('.learn-guide-search [role=status]')).to_contain_text('No matching guides')
    field.clear()
    expect(page.locator('.learn-guide-results button')).to_have_count(0)
    assert not errors, errors


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
def test_unknown_hash_has_an_actionable_page_and_navigation_recovers(chat_page):
    page, _, _, errors, _ = chat_page
    page.add_init_script("window.__routes=[];for(const name of ['replaceState','pushState']){const prior=history[name];history[name]=function(...args){window.__routes.push({name,url:args[2],stack:new Error().stack.split('\\n').slice(1,4)});return prior.apply(this,args)}}")
    page.goto('https://agentconcierge.biz/#nonexistent')
    (OUT/'route-trace.json').write_text(json.dumps(page.evaluate('({url:location.href,trace:window.__routes,errors:window.__errors})'),indent=2))
    expect(page.locator('#unknownRouteNotice')).to_be_visible()
    expect(page.locator('main h1:visible')).to_have_text('This page could not be found.')
    page.locator('#navTabs a[data-tab=explore]').click()
    expect(page.locator('#secExplore')).to_be_visible()
    expect(page.locator('#unknownRouteNotice')).to_have_count(0)
    assert not errors, errors


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
def test_historical_assessment_does_not_present_archived_prose_as_current(chat_page):
    page, _, _, errors, _ = chat_page
    page.goto('https://agentconcierge.biz/new/en/explore.html')
    page.evaluate('''() => { const target=document.createElement('div');target.id='qaReport';target.innerHTML=renderAgentTestReportHtml({id:1,kind:'mcp',test_report:{id:1,is_success:1,content_md:'Archived optimistic assessment',summary:'Old summary',execution_measured:false,evidence_label:'Historical document; no current execution verified'}});document.querySelector('#secExplore').append(target); }''')
    expect(page.locator('#qaReport [role=note]')).to_contain_text('no current execution verified')
    expect(page.locator('#qaReport .archived-report-assessment')).not_to_have_attribute('open')
    page.locator('#qaReport .archived-report-assessment > summary').click()
    expect(page.locator('#qaReport .archived-report-assessment')).to_have_attribute('open', '')
    assert not errors, errors
