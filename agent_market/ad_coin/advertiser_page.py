"""Advertiser console page (English, signed-in invited customers). Fixed text renders
as HTML at once; each region loads when asked, and data is written with
textContent only. Writes carry the customer session's CSRF proof."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>AI AD Coin for advertisers</title>
<style>
:root{--bg:#f6f6f3;--fg:#1c1c1a;--muted:#5b5b55;--card:#fff;--line:#d8d8d1;--accent:#0f6e66;--err:#a33a1f;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#efeee8;--muted:#b3b1a7;--card:#1f1f1d;--line:#3a3a36;--accent:#4fc2b6;--err:#f08a6c;--warn:#f0b25c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:20px 16px 60px}h1{font-size:24px;margin:0}h2{font-size:18px;margin:0 0 8px}h3{font-size:16px;margin:12px 0 6px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0}
.muted{color:var(--muted)}.err{color:var(--err)}.warn{color:var(--warn)}
button{font:inherit;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:7px;padding:6px 12px;cursor:pointer;min-height:36px}
button.secondary{background:transparent;color:var(--accent)}button:disabled{opacity:.5}
input,select,textarea{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);min-height:36px;width:100%}
label{font-size:13px;color:var(--muted);display:block;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}.row>*{width:auto}
.out{white-space:pre-wrap;font-size:13px;margin-top:8px;min-height:1em}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}th{white-space:nowrap;text-align:left}th,td{border-top:1px solid var(--line);padding:6px;vertical-align:top}
.scroll{overflow-x:auto}.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 8px;font-size:12px}
</style></head><body><main>
<h1>AI AD Coin for advertisers</h1>
<p class="muted">Closed test: budgets are virtual and nothing is charged. Your ads sponsor AI work people already chose; they never change which agent is recommended. Every view is approved by the person and rewarded, and invalid views are refunded.</p>

<section><h2>Account</h2>
<div class="row"><button id="load">Load my accounts</button><select id="account" aria-label="Advertiser account"></select></div>
<div class="out" id="account-out" aria-live="polite"></div>
<details><summary class="muted">Open a new advertiser account</summary>
<div class="grid"><div><label for="a-name">Business name</label><input id="a-name"></div>
<div><label for="a-site">Website (https)</label><input id="a-site" placeholder="https://example.com"></div></div>
<div class="row"><button id="a-create" class="secondary">Open account</button></div></details></section>

<section><h2>Campaigns</h2>
<div class="row"><button id="c-list" class="secondary">Show campaigns</button></div>
<div class="scroll"><table id="c-table" hidden><thead><tr><th>Campaign</th><th>Objective</th><th>Status</th><th>Serving</th><th>Bid</th><th>Today / daily</th><th>Budget left</th><th>Actions</th></tr></thead><tbody></tbody></table></div>
<div class="out" id="c-out" aria-live="polite"></div>
<h3>New campaign</h3>
<div class="grid">
<div><label for="n-name">Name</label><input id="n-name"></div>
<div><label for="n-objective">Objective</label><select id="n-objective"><option value="S1">Sponsor a task (pay per sponsored run)</option><option value="P2">View and confirm (pay per approved view)</option><option value="B1">Signed offer for agents (pay per agent receipt)</option></select></div>
<div><label for="n-categories">Task categories (comma)</label><input id="n-categories" placeholder="deep_research, dev_tools"></div>
<div><label for="n-exclude">Excluded categories (comma)</label><input id="n-exclude"></div>
<div><label for="n-bid">Max bid per unit (won)</label><input id="n-bid" inputmode="numeric" value="1500"></div>
<div><label for="n-daily">Daily budget (won)</label><input id="n-daily" inputmode="numeric" value="10000"></div>
<div><label for="n-cap">Views per person per day (1-3)</label><input id="n-cap" inputmode="numeric" value="3"></div>
<div><label for="n-end">End date (optional)</label><input id="n-end" type="date"></div></div>
<h3>First ad</h3>
<div class="grid">
<div><label for="n-title">Headline</label><input id="n-title" maxlength="80"></div>
<div><label for="n-body">Description</label><input id="n-body" maxlength="400"></div>
<div><label for="n-question">Confirmation question</label><input id="n-question" maxlength="160"></div>
<div><label for="n-answer">Answer</label><input id="n-answer" maxlength="40"></div>
<div><label for="n-url">Public copy of the ad (https, on your website)</label><input id="n-url"></div></div>
<div class="row"><button id="n-create">Create campaign</button></div><div class="out" id="n-out" aria-live="polite"></div></section>

<section><h2>Campaign details</h2><p class="muted">Pick a campaign above to edit it, manage its ads or add budget.</p>
<div id="detail"></div><div class="out" id="d-out" aria-live="polite"></div></section>

<section><h2>Reports</h2>
<div class="row"><select id="r-days" aria-label="Period"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option></select><button id="r-load" class="secondary">Show report</button><button id="r-csv" class="secondary">Download CSV</button></div>
<div class="scroll"><table id="r-table" hidden><thead><tr><th>Date</th><th>Offers</th><th>Views</th><th>People</th><th>View rate</th><th>Spend</th><th>Invalid refunded</th><th>Net spend</th><th>Cost per view</th><th>Runs</th></tr></thead><tbody></tbody></table></div>
<div class="out" id="r-out" aria-live="polite"></div></section>

<section><h2>Billing, history and team</h2>
<div class="row"><button id="b-load" class="secondary">Statement</button><button id="h-load" class="secondary">Change history</button><button id="m-load" class="secondary">Team</button></div>
<div class="out" id="b-out" aria-live="polite"></div>
<div class="grid"><div><label for="m-id">Account id to add</label><input id="m-id"></div>
<div><label for="m-role">Role</label><select id="m-role"><option>viewer</option><option>editor</option><option>owner</option><option value="removed">remove</option></select></div></div>
<div class="row"><button id="m-set" class="secondary">Save team member</button></div></section>
</main><script src="/ad-coin/advertiser.js"></script></body></html>
"""

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',csrf='',acct='',current=null;
var $=function(id){return document.getElementById(id)};function say(id,t){$(id).textContent=t}
function won(n){return n==null?'-':Number(n).toLocaleString('en-US')+' won'}
function session(){if(csrf)return Promise.resolve();return fetch('/api/customer-auth/session',{credentials:'same-origin'})
  .then(function(r){return r.ok?r.json():{}}).then(function(s){csrf=s.csrf_token||''}).catch(function(){})}
function call(path,body){return session().then(function(){var init={method:body?'POST':'GET',credentials:'same-origin',headers:{}};
  if(body){init.headers['Content-Type']='application/json';init.headers['X-Customer-CSRF']=csrf;init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.message||d.error||'Request failed');return d})})})}
function q(p){return p+(p.indexOf('?')<0?'?':'&')+'advertiser_id='+encodeURIComponent(acct)}
function el(tag,text,cls){var e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function btn(label,fn,secondary){var b=el('button',label,secondary?'secondary':null);b.onclick=fn;return b}
function list(v){return v.split(',').map(function(x){return x.trim()}).filter(Boolean)}
function needAccount(id){if(!acct){say(id,'Load or open an advertiser account first.');return false}return true}
$('load').onclick=function(){say('account-out','Loading...');call('/advertisers').then(function(d){var s=$('account');s.textContent='';
  d.advertisers.forEach(function(a){var o=el('option',a.name+' ('+a.role+', '+a.verification+')');o.value=a.id;s.appendChild(o)});
  acct=s.value||'';if(!acct){say('account-out','No advertiser account yet. Open one below.');return}showAccount()}).catch(function(e){say('account-out',e.message)})};
$('account').onchange=function(){acct=this.value;showAccount()};
function showAccount(){call(q('/advertiser')).then(function(d){var a=d.advertiser,lines=[a.name+' - '+a.website,'Status: '+a.status+' - verification: '+a.verification+
  (a.limited_daily_won?' (serving limited to '+won(a.limited_daily_won)+' a day until verified)':'')];
  d.notifications.forEach(function(n){lines.push((n.level==='error'?'! ':'- ')+n.message)});say('account-out',lines.join('\n'))}).catch(function(e){say('account-out',e.message)})}
$('a-create').onclick=function(){call('/advertisers',{name:$('a-name').value,website:$('a-site').value}).then(function(a){acct=a.id;say('account-out','Opened '+a.name+'. Load your accounts to switch.');showAccount()}).catch(function(e){say('account-out',e.message)})};
function campaigns(){if(!needAccount('c-out'))return;say('c-out','Loading...');call(q('/advertiser/campaigns')).then(function(d){var t=$('c-table'),b=t.querySelector('tbody');b.textContent='';
  t.hidden=!d.campaigns.length;say('c-out',d.campaigns.length?'':'No campaigns yet.');
  d.campaigns.forEach(function(c){var tr=el('tr');[c.name,c.objective,c.status+' / '+c.review_status,c.serving,won(c.bid_won),won(c.spent_today_won)+' / '+won(c.daily_budget_won),won(c.escrow_won)].forEach(function(v){tr.appendChild(el('td',v))});
    var td=el('td');td.appendChild(btn('Open',function(){current=c.id;detail(c)},true));tr.appendChild(td);b.appendChild(tr)})}).catch(function(e){say('c-out',e.message)})}
$('c-list').onclick=campaigns;
$('n-create').onclick=function(){if(!needAccount('n-out'))return;var end=$('n-end').value?Date.parse($('n-end').value+'T23:59:59')/1000:null;
  call('/advertiser/campaigns',{advertiser_id:acct,objective:$('n-objective').value,name:$('n-name').value,categories:list($('n-categories').value),
    excluded_categories:list($('n-exclude').value),bid_won:parseInt($('n-bid').value,10),daily_budget_won:parseInt($('n-daily').value,10),
    frequency_cap:parseInt($('n-cap').value,10),ends_at:end,creative:{title:$('n-title').value,body:$('n-body').value,question:$('n-question').value,answer:$('n-answer').value,public_url:$('n-url').value}})
  .then(function(c){say('n-out','Created. Review: '+c.review_status+(c.creatives[0].review_note?' - '+c.creatives[0].review_note:'')+'. Add budget to start serving.');current=c.id;detail(c);campaigns()})
  .catch(function(e){say('n-out',e.message)})};
function detail(c){var box=$('detail');box.textContent='';box.appendChild(el('h3',c.name+' ('+c.objective+')'));
  box.appendChild(el('p','Serving: '+c.serving+' - review: '+c.review_status+' - categories: '+c.categories.join(', ')+(c.excluded_categories.length?' - excluded: '+c.excluded_categories.join(', '):''),'muted'));
  var g=el('div',null,'grid'),fields={};[['bid_won','Max bid (won)',c.bid_won],['daily_budget_won','Daily budget (won)',c.daily_budget_won],['frequency_cap','Views per person per day',c.frequency_cap]].forEach(function(f){
    var w=el('div');var l=el('label',f[1]);var i=el('input');i.value=f[2];i.inputMode='numeric';w.appendChild(l);w.appendChild(i);g.appendChild(w);fields[f[0]]=i});box.appendChild(g);
  var r=el('div',null,'row');r.appendChild(btn('Save settings',function(){var body={advertiser_id:acct,campaign_id:c.id};Object.keys(fields).forEach(function(k){body[k]=parseInt(fields[k].value,10)});
    call('/advertiser/campaigns/update',body).then(function(n){say('d-out','Saved.');detail(n);campaigns()}).catch(function(e){say('d-out',e.message)})}));
  r.appendChild(btn(c.status==='enabled'?'Pause':'Enable',function(){call('/advertiser/campaigns/update',{advertiser_id:acct,campaign_id:c.id,status:c.status==='enabled'?'paused':'enabled'})
    .then(function(n){detail(n);campaigns()}).catch(function(e){say('d-out',e.message)})},true));
  var amt=el('input');amt.placeholder='Add budget (won)';amt.inputMode='numeric';amt.style.width='160px';r.appendChild(amt);
  r.appendChild(btn('Add budget',function(){call('/advertiser/campaigns/fund',{advertiser_id:acct,campaign_id:c.id,amount_won:parseInt(amt.value,10),idempotency_key:Date.now().toString(36)})
    .then(function(f){say('d-out','Budget now '+won(f.escrow_won)+' (virtual).');campaigns()}).catch(function(e){say('d-out',e.message)})},true));box.appendChild(r);
  box.appendChild(el('h3','Ads'));c.creatives.forEach(function(a){var row=el('div',null,'row');row.appendChild(el('span',a.title+' - '+a.review_status+(a.review_note?' ('+a.review_note+')':'')+' - weight '+a.weight,a.review_status==='disapproved'?'err':null));
    if(a.review_status==='disapproved'||a.review_status==='eligible_limited'){var why=el('input');why.placeholder='Why it should run';why.style.width='220px';row.appendChild(why);
      row.appendChild(btn('Appeal',function(){call('/advertiser/appeals',{advertiser_id:acct,creative_id:a.id,reason:why.value}).then(function(){say('d-out','Appeal sent; a person reviews it.')}).catch(function(e){say('d-out',e.message)})},true))}
    row.appendChild(btn('Remove',function(){call('/advertiser/creatives/edit',{advertiser_id:acct,creative_id:a.id,remove:true}).then(detail).catch(function(e){say('d-out',e.message)})},true));box.appendChild(row)});
  var ng=el('div',null,'grid'),nf={};[['title','Headline'],['body','Description'],['question','Question'],['answer','Answer'],['public_url','Public copy (https)']].forEach(function(f){var w=el('div');w.appendChild(el('label',f[1]));var i=el('input');w.appendChild(i);ng.appendChild(w);nf[f[0]]=i});
  box.appendChild(ng);var nr=el('div',null,'row');nr.appendChild(btn('Add ad',function(){var body={advertiser_id:acct,campaign_id:c.id};Object.keys(nf).forEach(function(k){body[k]=nf[k].value});
    call('/advertiser/creatives',body).then(function(n){say('d-out','Ad added. Review: '+n.creatives[n.creatives.length-1].review_status);detail(n)}).catch(function(e){say('d-out',e.message)})},true));box.appendChild(nr)}
$('r-load').onclick=function(){if(!needAccount('r-out'))return;say('r-out','Loading...');call(q('/advertiser/report?days='+$('r-days').value)+(current?'&campaign_id='+encodeURIComponent(current):'')).then(function(d){
  var t=$('r-table'),b=t.querySelector('tbody');b.textContent='';t.hidden=!d.rows.length;d.rows.forEach(function(r){var tr=el('tr');[r.date,r.offers,r.views,r.people,(r.view_rate*100).toFixed(1)+'%',won(r.spend_won),won(r.invalid_refunded_won),won(r.net_spend_won),won(r.cost_per_view_won),r.runs_succeeded+'/'+r.runs_started].forEach(function(v){tr.appendChild(el('td',String(v)))});b.appendChild(tr)});
  var x=d.totals;say('r-out',(d.rows.length?'':'No activity in this period. ')+'Total: '+x.views+' views of '+x.offers+' offers, net spend '+won(x.net_spend_won)+'. '+d.note)}).catch(function(e){say('r-out',e.message)})};
$('r-csv').onclick=function(){if(!needAccount('r-out'))return;location.href=q(API+'/advertiser/report.csv?days='+$('r-days').value)+(current?'&campaign_id='+encodeURIComponent(current):'')};
$('b-load').onclick=function(){if(!needAccount('b-out'))return;call(q('/advertiser/statement')).then(function(d){say('b-out',d.entries.length?d.entries.map(function(e){return new Date(e.at*1000).toLocaleString()+'  '+e.kind+'  '+won(e.escrow_change_won)+'  '+e.campaign_id}).join('\n'):'No entries yet.')}).catch(function(e){say('b-out',e.message)})};
$('h-load').onclick=function(){if(!needAccount('b-out'))return;call(q('/advertiser/history')).then(function(d){say('b-out',d.history.length?d.history.map(function(h){return new Date(h.at*1000).toLocaleString()+'  '+h.action+'  '+h.object+'  by '+h.actor}).join('\n'):'No changes yet.')}).catch(function(e){say('b-out',e.message)})};
$('m-load').onclick=function(){if(!needAccount('b-out'))return;call(q('/advertiser')).then(function(d){say('b-out',d.members.map(function(m){return m.customer_id+' - '+m.role}).join('\n'))}).catch(function(e){say('b-out',e.message)})};
$('m-set').onclick=function(){if(!needAccount('b-out'))return;call('/advertiser/members',{advertiser_id:acct,customer_id:$('m-id').value.trim(),role:$('m-role').value}).then(function(d){say('b-out',d.members.map(function(m){return m.customer_id+' - '+m.role}).join('\n'))}).catch(function(e){say('b-out',e.message)})};
})();
"""
