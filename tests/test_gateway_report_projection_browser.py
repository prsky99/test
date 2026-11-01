"""Public report visibility and obsolete-cache discard in isolated Chromium."""
import json

from playwright.sync_api import expect
from tests.test_single_agent_chat_browser import chat_page,catalog,browser


def test_sanitized_historical_report_is_visible_without_mutating_original(chat_page,catalog):
    page,requests,bodies,errors,best=chat_page;store,*_=catalog
    resource=store.resource(best);raw=resource['url']
    content='## Findings\nPublic observations\n- **Upstream Provider Target**: `'+raw+'`\n## Sources\nhttps://docs.example/report\n<script>window.__gatewayReportXss=1</script>'
    with store.tx() as db:
        db.execute('UPDATE agent_test_reports SET content_md=?,eval_grade=NULL,status_code=NULL WHERE resource_id=?',(content,best))
    page.goto('https://agentconcierge.biz/#explore');page.evaluate('id=>openAgent(id)',best)
    card=page.locator('.test-report-card');expect(card).to_be_visible()
    card.locator('details').evaluate_all('(items)=>items.forEach(item=>item.open=true)')
    text=card.inner_text();assert raw not in text and 'Upstream Provider Target' not in text
    assert 'Historical records are sanitized' in text and 'does not run a new test' in text
    assert 'Unrated' in text and 'Status Code: Not recorded' in text
    assert 'https://docs.example/report' in text
    assert not card.locator('script,img').count() and page.evaluate('window.__gatewayReportXss||0')==0
    assert store.query('SELECT content_md FROM agent_test_reports WHERE resource_id=?',(best,))[0][0]==content
    assert not errors


def test_v2_public_cache_cannot_restore_raw_report_and_other_preferences_survive(chat_page):
    page,_,_,errors,best=chat_page
    page.add_init_script('''localStorage.setItem('concierge_swr_gateway_v2_agent:1',JSON.stringify({agent:{name:'Old unsafe cache',test_report:{content_md:'https://retired-private.example/api'}}}));localStorage.setItem('concierge_swr_gateway_v3_explore',JSON.stringify({items:[{name:'Old wrongly bound report',report_count:1,report_grade:'A'}]}));localStorage.setItem('theme','dark');''')
    page.goto('https://agentconcierge.biz/#explore')
    assert page.evaluate("localStorage.getItem('concierge_swr_gateway_v2_agent:1')") is None
    assert page.evaluate("localStorage.getItem('concierge_swr_gateway_v3_explore')") is None
    assert page.evaluate("localStorage.getItem('theme')")=='dark'
    assert page.evaluate('SWR_STORAGE_KEY_PREFIX')=='concierge_swr_gateway_v6_'
    assert 'retired-private.example' not in page.content() and not errors
