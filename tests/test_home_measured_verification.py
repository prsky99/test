"""Home statistics count measured execution evidence, with real period boundaries."""
import json
import time
from urllib.parse import urlsplit
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.capability_registry import Registry
from agent_market.concierge.front import Front, create_front_app, clear_front_caches
from agent_market.concierge.verification_summary import execution_summary
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser


@pytest.fixture
def measured_home(tmp_path):
    store = Store(str(tmp_path / 'home.sqlite3'))
    now = time.time()
    rid = store.upsert_resource({'key':'measured-home', 'source':'fixture', 'kind':'a2a',
        'name':'Measured Reader', 'url':'https://reader.example/a2a', 'description':'Read public documents',
        'category':'docs_knowledge', 'networks':[]})
    with store.tx() as db:
        db.execute("UPDATE resources SET active=1,health_status='healthy',trial_ok=1,last_ok_at=? WHERE id=?", (now,rid))
    registry = Registry(store)
    version = registry.current(rid)
    def record(scope, outcome, ago):
        return registry.record(version, scope=scope, outcome=outcome, started=now-ago-1, finished=now-ago)
    record('execution','succeeded',60)
    record('execution','succeeded',3700)
    record('execution','failed',7200)
    record('execution','unknown',10800)
    record('transport','succeeded',20)
    record('execution','succeeded',86401)
    front = Front(store, allow_private=True)
    client = TestClient(create_front_app(front))
    clear_front_caches()
    yield store,front,client,now
    client.close();front.book.close();store._db.close()


def test_execution_summary_excludes_transport_legacy_flags_and_expired_window(measured_home):
    store,_,client,now = measured_home
    result = execution_summary(store,now)
    assert result['completed']==4 and result['succeeded']==2
    assert result['failed']==1 and result['unknown']==1 and result['successful_resources']==1
    assert result['period_start']==now-86400 and result['period_end']==now
    assert result['success_share_pct']==50 and result['timezone']=='UTC'
    assert sum(sum(row[k] for k in ('succeeded','failed','unknown')) for row in result['hourly'])==4
    response=client.get('/api/overview')
    assert response.status_code==200 and response.json()['verification']['completed']==4
    assert client.get('/api/explore?verified=true').json()['total_is_estimate'] is True
    assert 'reader.example' not in json.dumps(result)
    assert 'agent_ref' not in json.dumps(result) and 'operation_ref' not in json.dumps(result)


def test_empty_execution_evidence_never_defaults_to_success():
    store=Store()
    try:
        result=execution_summary(store)
        assert result['completed']==0 and result['success_share_pct'] is None
        assert result['successful_resources']==0
    finally:store._db.close()


def test_recorded_checks_keep_their_original_protocol_after_catalog_changes(measured_home):
    store,_,_,now=measured_home
    with store.tx() as db:
        db.execute("UPDATE resources SET kind='mcp'")
    result=execution_summary(store,now)
    assert result['by_protocol']['a2a']['succeeded']==2
    assert result['by_protocol']['mcp']['succeeded']==0
    assert result['completed']==4


def test_home_uses_current_catalog_and_ignores_old_midnight_meta(measured_home):
    store,front,client,_=measured_home
    store.set_meta('daily_midnight_stats_1', {'a2a':999999})
    assert front.live_counts()=={'a2a':1}
    payload=client.get('/api/overview').json()
    assert payload['health_summary']['total_active']==1
    assert payload['health_summary']['live_total']==1


def test_home_chart_and_empty_state_render_real_values_in_both_themes(browser,measured_home):
    _,_,client,_=measured_home
    for scheme in ('light','dark'):
        context=browser.new_context(color_scheme=scheme,reduced_motion='reduce')
        errors=[]
        def serve(route):
            req=route.request;url=urlsplit(req.url)
            if url.hostname!='agentconcierge.biz':return route.abort()
            response=client.request(req.method,url.path+('?' +url.query if url.query else ''),
                content=req.post_data,headers={'accept':req.headers.get('accept','*/*')})
            route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
                if k not in ('content-length','content-encoding','transfer-encoding')})
        context.route('**/*',serve)
        page=context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))
        page.goto('https://agentconcierge.biz/')
        expect(page.locator('#ovSurveys')).to_contain_text('Succeeded: 2')
        expect(page.locator('#ovSurveys')).to_contain_text('Failed: 1')
        expect(page.locator('#ovSurveys')).to_contain_text('Unknown: 1')
        expect(page.locator('#ovSurveys svg')).to_have_count(1)
        assert '99.4%' not in page.locator('#ovSurveys').inner_text()
        reject=page.get_by_role('button',name='Reject Non-Essential',exact=True)
        if reject.is_visible():reject.click()
        captures=Path(__file__).resolve().parents[1]/'reports/frontend-operations-remediation-2026-10-19'
        captures.mkdir(exist_ok=True)
        page.screenshot(path=str(captures/f'home-{scheme}-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(captures/f'home-{scheme}-mobile.png'),full_page=True)
        page.evaluate('''() => { const data=structuredClone(ovCache);data.verification={scope:'execution',succeeded:0,failed:0,unknown:0,period_start:1,period_end:86401,hourly:[]};renderOverview(data); }''')
        expect(page.locator('#ovSurveys')).to_contain_text('No execution checks were recorded')
        expect(page.locator('#ovSurveys svg')).to_have_count(0)
        page.evaluate('''() => {const data=structuredClone(ovCache);data.verification={scope:'execution',succeeded:1,failed:0,unknown:0,period_start:1,period_end:86401,hourly:[{start:'<img src=x onerror=alert(1)>',succeeded:1}]};renderOverview(data);}''')
        assert not page.locator('#ovSurveys img, #ovSurveys script').count()
        page.evaluate('''() => {const data=structuredClone(ovCache);data.resources=[{kind:'a2a',active:1,status:'healthy',n:1},{kind:'a2a',active:1,status:'unknown',n:9},{kind:'a2a',active:0,status:'healthy',n:99}];renderOverview(data);}''')
        expect(page.locator('#ovKindStatus')).to_contain_text('1/10 reachable (10%)')
        page.evaluate('''() => {document.getElementById('xHasReport').checked=true;renderExplore([], '', 100, true);}''')
        expect(page.locator('#xTitle')).to_contain_text('Showing 0 of up to 100')
        assert 'reports verified' not in page.locator('#xTitle').inner_text()
        assert not errors
        context.close()
