"""Real browser checks for bounded admin reads, invalidation and explicit freshness."""
from tests.test_operational_observability_browser import trace_page
from tests.test_front_workflow_browser import browser

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def prepare(page):
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    page.evaluate('''() => {
      clearTimeout(state.timer);invalidateAdminReads();window.__cacheCalls=[];
      window.__cacheFetch=window.fetch;
      window.fetch=async(path,opts)=>{
        if(path.startsWith('/admin/api/agents?cache_fixture=')) {
          window.__cacheCalls.push({path,force:opts.headers['X-Admin-Refresh']});
          return new Response(JSON.stringify({rows:[{name:'Synthetic row'}],version:window.__cacheCalls.length}),{status:200,headers:{'Content-Type':'application/json'}});
        }
        return window.__cacheFetch(path,opts);
      };
    }''')


def test_cached_reads_coalesce_detach_and_manual_refresh_bypasses(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    result=page.evaluate('''async () => {
      const path='/admin/api/agents?cache_fixture=one';
      const [a,b]=await Promise.all([api(path,{silent:true}),api(path,{silent:true})]);
      a.rows[0].name='Changed locally';
      const c=await api(path,{silent:true});
      const first=window.__cacheCalls.length;
      const fresh=await api(path,{silent:true,forceRead:true});
      return {first,name:c.rows[0].name,detached:b.rows[0].name,calls:window.__cacheCalls.length,version:fresh.version,force:window.__cacheCalls[1].force};
    }''')
    assert result=={'first':1,'name':'Synthetic row','detached':'Synthetic row','calls':2,'version':2,'force':'1'}
    assert not errors


def test_stale_refresh_and_session_change_cannot_share_cached_rows(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    result=page.evaluate('''async () => {
      const path='/admin/api/agents?cache_fixture=stale';
      await api(path,{silent:true});adminReadCache.get(path).at-=11000;
      window.__freshVersion=null;
      const old=await api(path,{silent:true,onFresh:result=>window.__freshVersion=result.version});
      await new Promise(resolve=>setTimeout(resolve,20));
      const fresh=window.__freshVersion;
      token='synthetic-next-session';syncAdminSession();
      const cleared=adminReadCache.size===0;
      const next=await api(path,{silent:true});
      return {old:old.version,fresh,cleared,next:next.version,calls:window.__cacheCalls.length};
    }''')
    assert result=={'old':1,'fresh':2,'cleared':True,'next':3,'calls':3}
    assert not errors


def test_write_invalidates_cached_queries_and_security_reads_are_never_cached(trace_page):
    page,_,_,errors,_=trace_page
    prepare(page)
    result=page.evaluate('''async () => {
      const original=window.fetch;let security=0;
      window.fetch=(path,opts)=>path==='/admin/api/cache-mutation'
        ? Promise.resolve(new Response('{}',{status:200}))
        : path==='/admin/api/security/cache-fixture'
        ? (security++,Promise.resolve(new Response('{}',{status:200}))) : original(path,opts);
      const path='/admin/api/agents?cache_fixture=write';
      await api(path,{silent:true});await api('/admin/api/cache-mutation',{method:'POST',silent:true,json:{}});
      await api(path,{silent:true});
      await api('/admin/api/security/cache-fixture',{silent:true});await api('/admin/api/security/cache-fixture',{silent:true});
      return {calls:window.__cacheCalls.length,security};
    }''')
    assert result=={'calls':2,'security':2}
    assert not errors
