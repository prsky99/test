"""Stored report language normalization with original evidence and escaping intact."""
import json
import re

import pytest

from tests.test_single_agent_chat_browser import chat_page, catalog, browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
HANGUL = re.compile(r'[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]')


def test_stored_report_drawer_is_english_without_changing_evidence(chat_page,catalog):
    page,requests,bodies,errors,best = chat_page
    store,front,client,add,now = catalog
    md = '## Pros and Cons (\uc7a5\uc810 \ubc0f \ub2e8\uc810)\n### Pros (\uc7a5\uc810)\n- Fast responses\n### Cons (\ub2e8\uc810)\n- Needs authentication\n### Workflow (\uc6cc\ud06c\ud50c\ub85c\uc6b0)\nUse the verified endpoint.'
    wire = json.dumps({'query':'\uc0bc\uc131\uc804\uc790'},ensure_ascii=False)
    with store.tx() as db:
        db.execute('UPDATE agent_test_reports SET content_md=?,pros=?,cons=?,input_wire=?,output_wire=? WHERE resource_id=?',
                   (md,json.dumps(['\uc7a5\uc810: Fast responses']),json.dumps(['\ub2e8\uc810: Needs authentication']),wire,wire,best))
    page.goto('https://agentconcierge.biz/#explore')
    page.evaluate('id=>openAgent(id)',best)
    report = page.locator('.test-report-card')
    playwright.expect(report).to_be_visible()
    report.locator('details').evaluate_all('(items)=>items.forEach(item=>item.open=true)')
    text = report.inner_text()
    assert not HANGUL.search(text) and 'Fast responses' in text and 'Needs authentication' in text
    assert '(Pros)' not in text and '(Cons)' not in text
    assert report.locator('.test-report-markdown-body h5').all_text_contents()==['Pros','Cons','Workflow']
    wire_text = report.locator('.test-report-wire-box').first.inner_text()
    assert '\\uc0bc' in wire_text and json.loads(wire_text)==json.loads(wire)
    stored = store.query('SELECT content_md,input_wire FROM agent_test_reports WHERE resource_id=?',(best,))[0]
    assert stored['content_md']==md and stored['input_wire']==wire and not errors


def test_legacy_report_strings_stay_escaped_and_input_object_is_not_mutated(chat_page):
    page,_,_,errors,_ = chat_page
    page.goto('https://agentconcierge.biz/#explore')
    report = {'id':123,'title':'Pros (\uc7a5\uc810)','eval_grade':'D','eval_score':20,'is_success':False,
              'pros':json.dumps(['\uc7a5\uc810: <img src=x onerror="window.__reportXss=1">']),
              'cons':json.dumps(['\ub2e8\uc810: Limited coverage']),
              'content_md':'## Pros (\uc7a5\uc810)\n<script>window.__reportXss=1</script>'}
    unchanged = page.evaluate('''report=>{
      const original=JSON.stringify(report);
      renderDrawerAgent({name:'Synthetic report agent',kind:'mcp',test_report:report},'cached');
      return JSON.stringify(report)===original;
    }''',report)
    node = page.locator('.test-report-card')
    node.locator('details').evaluate_all('(items)=>items.forEach(item=>item.open=true)')
    assert unchanged and not node.locator('img,script').count()
    assert not HANGUL.search(node.inner_text()) and 'FAILED' in node.inner_text() and 'Grade D' in node.inner_text()
    assert page.evaluate('window.__reportXss||0')==0 and not errors


def test_unknown_non_english_report_copy_uses_an_explicit_fallback(chat_page):
    page,_,_,errors,_ = chat_page
    page.goto('https://agentconcierge.biz/#explore')
    result = page.evaluate('text=>reportDisplayText(text)','Untranslated \uc0c8\ub85c\uc6b4 \ub0b4\uc6a9')
    assert result=='English text is not available for this report section.' and not errors


def test_legacy_numeric_and_iso_report_dates_render_without_changing_the_record(chat_page):
    page, _, _, errors, _ = chat_page
    page.goto('https://agentconcierge.biz/#explore')
    result = page.evaluate('''() => {
      const values = [1792368000, '1792368000', '2026-10-19T00:00:00Z', '2026-10-19 00:00:00'];
      return {times:values.map(nyTime), ages:values.map(nyAgo), invalid:nyTime('unavailable')};
    }''')
    assert len(set(result['times'])) == len(set(result['ages'])) == 1
    assert 'Invalid' not in result['times'][0] and 'NaN' not in result['ages'][0]
    assert result['invalid'] == '\u2013' and not errors
