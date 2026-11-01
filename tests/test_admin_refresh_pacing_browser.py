"""Admin refreshes pace requests, pause when hidden, and never overlap."""
from playwright.sync_api import expect

from tests.test_operational_observability_browser import trace_page
from tests.test_front_workflow_browser import browser

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def prepare(page):
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    page.clock.install()
    page.evaluate('''() => {
      window.__refreshCalls=[];
      window.__originalRefreshApi=api;
      api=async (path,opts) => { window.__refreshCalls.push(path); return window.__originalRefreshApi(path,opts); };
      schedule();
    }''')


def test_polling_waits_30_seconds_and_pauses_hidden_or_static_tabs(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.clock.run_for(29000)
    assert page.evaluate('window.__refreshCalls.length')==0
    page.clock.run_for(2000)
    page.wait_for_function('() => window.__refreshCalls.some(p=>p.startsWith("/admin/api/timeseries")) && !refreshInFlight')
    assert page.evaluate('window.__refreshCalls.filter(p=>p==="/admin/api/overview").length')==1
    page.evaluate('''() => {window.__refreshCalls=[];Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));}''')
    page.clock.run_for(120000)
    assert page.evaluate('window.__refreshCalls.length')==0
    assert page.evaluate('state.timer===null')
    page.evaluate('''() => {Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});state.tab='learn';document.dispatchEvent(new Event('visibilitychange'));}''')
    page.clock.run_for(60000)
    assert page.evaluate('window.__refreshCalls.length')==0
    assert not errors


def test_refresh_is_single_flight_and_failures_back_off(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.evaluate('''() => {
      clearTimeout(state.timer);
      api=async (path,opts) => {
        window.__refreshCalls.push(path);
        if(path==='/admin/api/overview') return new Promise(resolve=>{window.__releaseRefresh=()=>resolve(state.overview);});
        return window.__originalRefreshApi(path,opts);
      };
      void refresh(true);void refresh(true);void refresh(true);
    }''')
    assert page.evaluate('window.__refreshCalls.filter(p=>p==="/admin/api/overview").length')==1
    page.evaluate('window.__releaseRefresh()')
    page.wait_for_function('() => !refreshInFlight')
    page.evaluate('''() => {window.__refreshCalls=[];api=async path=>{window.__refreshCalls.push(path);throw new Error('synthetic outage');};schedule();}''')
    page.clock.run_for(31000)
    page.wait_for_function('() => refreshFailures===1 && !refreshInFlight')
    page.clock.run_for(58000)
    assert page.evaluate('window.__refreshCalls.length')==1
    page.clock.run_for(3000)
    page.wait_for_function('() => refreshFailures===2 && !refreshInFlight')
    assert page.evaluate('window.__refreshCalls.length')==2
    assert not errors


def test_old_session_refresh_and_queued_work_cannot_render_after_account_change(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.evaluate('''() => {
      clearTimeout(state.timer);window.__heldRefreshFetch=window.fetch;
      const old=structuredClone(state.overview);old.review_marker='previous-account';
      window.__heldOverviewCalls=0;
      window.fetch=(path,opts)=>{
        if(path==='/admin/api/overview') {
          window.__heldOverviewCalls++;
          return new Promise(resolve=>{window.__releaseOldOverview=()=>resolve(new Response(JSON.stringify(old),{status:200,headers:{'Content-Type':'application/json'}}));});
        }
        return window.__heldRefreshFetch(path,opts);
      };
      void refresh(true);void refresh(false);
    }''')
    page.wait_for_function('Boolean(window.__releaseOldOverview)')
    page.evaluate('''() => {
      token='isolated-next-account';currentUser={username:'next-account',role:'admin'};
      updateUserUI(currentUser,false);
      $('globalBanner').textContent='new-session-banner';window.__releaseOldOverview();
    }''')
    page.wait_for_function('!refreshInFlight')
    assert page.evaluate('state.overview===null')
    assert page.evaluate('window.__heldOverviewCalls')==1
    assert page.evaluate('token')=='isolated-next-account'
    assert page.locator('#globalBanner').inner_text()=='new-session-banner'
    assert page.locator('main').is_hidden()
    assert not errors


def test_old_unauthorized_response_cannot_log_out_a_new_account(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.evaluate('''() => {
      clearTimeout(state.timer);window.__heldRefreshFetch=window.fetch;
      window.fetch=(path,opts)=>path==='/admin/api/review-session'
        ? new Promise(resolve=>{window.__releaseOld401=()=>resolve(new Response(JSON.stringify({detail:'expired old session'}),{status:401,headers:{'Content-Type':'application/json'}}));})
        : window.__heldRefreshFetch(path,opts);
      window.__sessionOutcome='pending';
      void api('/admin/api/review-session',{silent:true}).then(()=>window.__sessionOutcome='returned',error=>window.__sessionOutcome=error.message);
    }''')
    page.wait_for_function('Boolean(window.__releaseOld401)')
    page.evaluate('''() => {
      token='isolated-next-account';currentUser={username:'next-account',role:'admin'};
      updateUserUI(currentUser,false);window.__releaseOld401();
    }''')
    page.wait_for_function("window.__sessionOutcome==='stale_session'")
    assert page.evaluate('token')=='isolated-next-account'
    assert page.evaluate('currentUser.username')=='next-account'
    expect(page.locator('#adminLoginModal')).to_be_hidden()
    assert not errors


def test_session_change_during_response_body_parse_discards_private_data(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.evaluate('''() => {
      clearTimeout(state.timer);window.__heldRefreshFetch=window.fetch;
      window.fetch=(path,opts)=>path==='/admin/api/review-body'
        ? Promise.resolve({status:200,ok:true,headers:new Headers({'Content-Type':'application/json'}),json:()=>new Promise(resolve=>{window.__releaseOldBody=()=>resolve({private_review_marker:'previous-account'});})})
        : window.__heldRefreshFetch(path,opts);
      window.__bodyOutcome='pending';
      void api('/admin/api/review-body',{silent:true}).then(result=>window.__bodyOutcome=result.private_review_marker,error=>window.__bodyOutcome=error.message);
    }''')
    page.wait_for_function('() => Boolean(window.__releaseOldBody)')
    page.evaluate('''() => {
      token='isolated-next-account';currentUser={username:'next-account',role:'admin'};
      updateUserUI(currentUser,false);window.__releaseOldBody();
    }''')
    page.wait_for_function("() => window.__bodyOutcome==='stale_session'")
    assert page.evaluate('token')=='isolated-next-account'
    assert not errors


def test_security_child_reads_stay_single_flight_and_caught_errors_back_off(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    page.evaluate('''() => {
      clearTimeout(state.timer);state.tab='security';window.__heldRefreshFetch=window.fetch;
      window.__securityChildCalls=0;window.__releaseSecurity=[];
      window.fetch=(path,opts)=>{
        if(path.startsWith('/admin/api/security/rules')||path.startsWith('/admin/api/security/events')) {
          window.__securityChildCalls++;
          return new Promise(resolve=>window.__releaseSecurity.push(()=>resolve(new Response(JSON.stringify({detail:'isolated read failure'}),{status:503,headers:{'Content-Type':'application/json'}}))));
        }
        return window.__heldRefreshFetch(path,opts);
      };
      void refresh(true);
    }''')
    page.wait_for_function('() => window.__releaseSecurity.length===2')
    assert page.evaluate('refreshInFlight')
    page.evaluate('void refresh(true)')
    assert page.evaluate('window.__securityChildCalls')==2
    page.evaluate('window.__releaseSecurity.forEach(release=>release())')
    page.wait_for_function('!refreshInFlight')
    assert page.evaluate('refreshFailures')==1
    assert page.locator('#globalBanner').inner_text().endswith('isolated read failure')
    assert not errors
