"""Provider self-claim screens for customers (growth team, 11-19 bundle; draft reports/provider-entry-draft-2026-11-15).

/customer/provider-claims lists the signed-in customer's claims; ?agent=<id> on the same page starts one for that agent
(the navigation allow-list takes that one query, agent team 52bd81b6). Everything talks to the agent team's API at
/api/customer/provider-claims (docs/PROVIDER_SELF_CLAIM.md): writes carry x-customer-csrf from
/api/customer-auth/session; while the tables do not exist the API answers available false and the page says so.
Server values reach the page only through textContent. A verified claim is shown to its owner only (PM decision 3):
it never changes grades, ranks or tests, and the server's note is shown as it comes.
"""
import re

BASE = '/api/customer/provider-claims'
AGENT = re.compile(r'[1-9][0-9]{0,11}')

# English sentences for the API's codes (draft section 5, agent team contract 11-15).
MESSAGES = {
    'provider_claims_not_available': 'Provider verification is not open yet.',
    'resource_not_found': 'We could not find this agent in the catalog.',
    'invalid_resource': 'We could not find this agent in the catalog.',
    'resource_not_public_https': 'Only agents at a public HTTPS address can be verified.',
    'shared_host_use_protocol': 'This address is shared hosting, so a file cannot tell its customers apart. Use the marker inside the agent.',
    'protocol_needs_mcp_or_a2a': 'A marker inside the agent works for MCP servers and A2A agents only. Publish the file instead.',
    'already_verified': 'You have already verified this.',
    'too_many_claims': 'You have 20 open requests. Withdraw one first.',
    'claim_not_found': 'This request is no longer open. Start a new one.',
    'claim_not_pending': 'This request is no longer open. Start a new one.',
    'claim_changed': "The agent's address changed since you started. Start a new request.",
    'too_many_checks': "You have used today's 10 checks. Try again tomorrow.",
    'origin_checked_recently': 'This site was checked less than a minute ago. Wait a minute and check again.',
    'not_verified_for_resource': 'Verify this agent first to see its test record.',
    'busy': 'We are busy right now. Try again in a few seconds.',
    'rate_limited': 'Too many requests. Wait a minute.',
    'http_status': 'The file did not answer with HTTP 200. Check the address and that there is no redirect.',
    'invalid_body': 'The file is not exactly the JSON shown above. Copy it again without extra fields.',
    'value_mismatch': 'The value we found does not match this request. Copy it again exactly, then press Check.',
    'response_too_large': 'The answer was larger than 4 KiB. Serve only the JSON shown above.',
    'not_public_address': 'The address did not resolve to a public internet address.',
    'call_budget_refused': 'We have checked this domain enough for today. Try again tomorrow.',
    'resource_moved': "The agent's address moved off this site, so it is no longer covered.",
    'request_failed': 'We could not reach the file or the agent. Check that it is live, then press Check again.',
}
STATUS = {'pending': 'Waiting for your file or marker', 'verified': 'Verified', 'lapsed': 'Lapsed: the last two checks failed',
          'expired': 'Expired: not checked within 24 hours', 'withdrawn': 'Withdrawn'}


def page_html_parts(agent=None):
    """(title, description, content, script) for customer_identity_view._page; agent is a catalog id or None."""
    import json
    agent = agent if isinstance(agent, str) and AGENT.fullmatch(agent) else None
    content = (
        '<h1>Prove you run an agent</h1>'
        '<p class="note">This shows that you can change something at the agent&#39;s address right now. It does not change '
        'its grade, rank, tests or recommendations, and nothing about it is shown publicly.</p>'
        '<p id="status" role="status" aria-live="polite">Loading.</p>'
        '<section id="start" hidden aria-labelledby="startTitle"><h2 id="startTitle">How do you want to prove it?</h2>'
        '<fieldset><legend class="note">Choose one</legend>'
        '<label><input type="radio" name="method" value="well_known" checked> Publish a file on your site '
        '(covers every listed agent on that site)</label>'
        '<label><input type="radio" name="method" value="protocol"> Add a marker inside the agent '
        '(this agent only; use it on shared hosting)</label></fieldset>'
        '<button id="prepare" type="button" disabled>Get my one-time value</button></section>'
        '<section id="publish" hidden aria-labelledby="publishTitle"><h2 id="publishTitle">Publish this</h2>'
        '<p class="note">Your one-time value is shown only now. Copy it before you leave this page.</p>'
        '<p id="publishWhere"></p><pre id="publishWhat" tabindex="0"></pre><p id="publishNote" class="note"></p>'
        '<p class="note">This request stays open for 24 hours. When it is live, press Check now.</p>'
        '<button id="check" type="button">Check now</button> <button id="withdraw" type="button">Withdraw</button></section>'
        '<section id="mine" hidden aria-labelledby="mineTitle"><h2 id="mineTitle">My agents</h2><ul id="claims"></ul></section>'
        '<section id="record" hidden aria-labelledby="recordTitle"><h2 id="recordTitle">Test record</h2>'
        '<dl id="recordList"></dl><p id="recordNote" class="note"></p></section>')
    script = ('const BASE=' + json.dumps(BASE) + ',AGENT=' + json.dumps(agent) + ',MSG=' + json.dumps(MESSAGES)
              + ',STATUS=' + json.dumps(STATUS) + ';' + _SCRIPT)
    return 'Prove you run an agent', 'Verify that you run an agent listed on AgentValCon.', content, script


# Plain DOM only: values from the server are set with textContent. Busy (503) shows a line in this page's status area.
_SCRIPT = r'''
const $=id=>document.getElementById(id);let csrf='',claim=null;
const say=t=>{$('status').textContent=t};
const message=code=>MSG[code]||('It did not work ('+String(code||'error')+'). Try again later.');
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
 headers:body===undefined?{}:{'content-type':'application/json','x-customer-csrf':csrf},body:body===undefined?undefined:JSON.stringify(body),
 signal:AbortSignal.timeout(20000)});
 if(r.status===401){location.assign('/customer/sign-in?next='+encodeURIComponent(location.pathname+location.search));throw new Error('sign-in')}
 let data={};try{data=await r.json()}catch(e){}
 if(!r.ok){const code=(data.detail&&data.detail.code)||data.code||(r.status===503?'busy':'error');const e=new Error(code);e.code=code;throw e}
 return data}
function row(dl,k,v){if(v===undefined||v===null||v==='')return;const dt=document.createElement('dt'),dd=document.createElement('dd');
 dt.textContent=k;dd.textContent=typeof v==='object'?JSON.stringify(v):String(v);dl.append(dt,dd)}
async function record(rid){const box=$('recordList');box.replaceChildren();$('record').hidden=false;
 try{const d=await api(BASE+'/resources/'+encodeURIComponent(rid));row(box,'Health',d.health);row(box,'Last test call',d.last_trial);
  row(box,'Test reports',d.test_reports);if(d.retest_queue)row(box,'Retest queue','Position '+d.retest_queue.position+' of '+d.retest_queue.of);
  row(box,'Correction requests',d.corrections);$('recordNote').textContent=d.note||''}
 catch(e){if(e.message!=='sign-in')$('recordNote').textContent=message(e.code)}}
async function mine(){const d=await api(BASE);if(!d.available){say(MSG.provider_claims_not_available);return false}
 const ul=$('claims');ul.replaceChildren();for(const c of d.items||[]){const li=document.createElement('li');
  li.textContent=(c.origin||('agent '+c.resource_id))+' — '+(STATUS[c.status]||c.status)+(c.expires?' (until '+c.expires+')':'');
  if(c.status==='verified'&&c.resource_id){const b=document.createElement('button');b.type='button';b.textContent='Test record';
   b.onclick=()=>record(c.resource_id);li.append(' ',b)}ul.append(li)}
 $('mine').hidden=false;return true}
function show(p){claim=p.claim_id;const i=p.instructions||{};$('publish').hidden=false;
 $('publishWhere').textContent=i.publish_at?('Publish exactly this JSON at '+i.publish_at):('Put this in '+(i.publish_in||'the agent'));
 $('publishWhat').textContent=i.content?JSON.stringify(i.content):(i.text||'');$('publishNote').textContent=i.notes||''}
async function guarded(fn){try{await fn()}catch(e){if(e.message!=='sign-in')say(message(e.code))}}
$('prepare').onclick=()=>guarded(async()=>{const method=document.querySelector('input[name=method]:checked').value;
 const p=await api(BASE,{resource_id:Number(AGENT),method});show(p);say('Your request is open.')});
$('check').onclick=()=>guarded(async()=>{const r=await api(BASE+'/'+encodeURIComponent(claim)+'/verify',{});
 say(r.status==='verified'?'Verified. Your test record is open below.':message(r.outcome));if(r.status==='verified'){await mine();await record(AGENT)}});
$('withdraw').onclick=()=>guarded(async()=>{await api(BASE+'/'+encodeURIComponent(claim)+'/withdraw',{});$('publish').hidden=true;say('Withdrawn.');await mine()});
(async()=>{await guarded(async()=>{const s=await api('/api/customer-auth/session');csrf=(s.session||{}).csrf_token||'';
 const open=await mine();if(!open)return;say(AGENT?'Choose how to prove it.':'Your claims are listed below.');
 if(AGENT){$('start').hidden=false;$('prepare').disabled=!csrf}})})();
'''


def page_for(agent=None):
    from .customer_identity_view import _page
    return _page(*page_html_parts(agent), section='account')


def provider_claims_page_router():
    """GET /customer/provider-claims (and ?agent=<id>). To be included where the customer pages are assembled."""
    from fastapi import APIRouter, Request
    router = APIRouter()

    @router.get('/customer/provider-claims', include_in_schema=False)
    def page(request: Request):
        return page_for(request.query_params.get('agent'))

    return router
