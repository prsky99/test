"""AI AD Coin operator console (English, like every public frontend page; admin token).

It uses the Agent Concierge "Pearl Connection" design system as it is (shared files
under /new/en/assets, the workspace shell and shared components; no page-local
styles). The admin console's own stylesheet lives on the private admin host, so this
page uses the public files, which carry the same pearl tokens. Fixed text renders at
once; each panel loads when its button is pressed and the status panel fetches its
two sources in parallel. No dialogs or full-screen loading."""
from .advertiser_page import ICON

VIEWS = (('status', 'Status and backing', 'home'), ('review', 'Ad review and advertisers', 'megaphone'),
         ('audit', 'Sponsorship audit', 'chart'), ('invites', 'Invitations', 'team'), ('split', 'Revenue split', 'receipt'),
         ('campaigns', 'Test campaigns', 'plus'), ('products', 'Test products', 'plus'), ('ops', 'Runs and settlement', 'receipt'))

SIDEBAR = ''.join(
    '<a class="side-item%s" href="#%s" data-view-link="%s"%s>%s%s</a>\n' % (
        ' active' if key == 'status' else '', key, key, ' aria-current="page"' if key == 'status' else '', ICON[icon], label)
    for key, label, icon in VIEWS)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, noarchive">
<meta name="referrer" content="no-referrer">
<title>AI AD Coin operations | Agent Concierge</title>
<link rel="icon" href="/new/en/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/new/en/assets/styles.css">
<link rel="stylesheet" href="/new/en/assets/necklace.css">
<link rel="stylesheet" href="/new/en/assets/pearl-live.css">
<script src="/new/en/assets/app.js" defer></script>
<script src="/ad-coin/admin.js" defer></script>
</head>
<body data-page="ad-coin-admin">
<a class="sr-only skip-link" href="#main">Skip to content</a>
<header class="ws-top">
<div class="container header-inner">
<a class="brand" href="/new/en/index.html"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>
<span class="small mobile-hidden">AI AD Coin operations</span>
<div class="header-actions">
{sun}<button class="theme-toggle" type="button" data-action="theme" aria-label="Toggle dark theme" aria-pressed="false"></button>{moon}
</div>
</div>
</header>
<div class="container ws-layout">
<aside class="ws-sidebar" aria-label="AI AD Coin operations">
<p class="caption">AI AD Coin operations</p>
<div class="row"><span class="badge warning">Test mode</span></div>
<hr class="divider">
{sidebar}</aside>
<main class="ws-main" id="main">
<div class="page-heading">
<p class="eyebrow">AI AD Coin · Operations</p>
<h1>Sponsorship and coin operations</h1>
<p class="lead">Test mode. Budgets, coins and settlements are virtual; payments and real advertiser spending are closed. Only house test campaigns serve.</p>
</div>

<section class="card" aria-labelledby="token-h">
<h2 id="token-h">Operator token</h2>
<p class="caption">Kept in this tab only.</p>
<div class="field"><label for="token">Token</label><input id="token" type="password" autocomplete="off"></div>
<div class="actions"><button type="button" class="btn primary" id="save">Use token</button></div>
<p class="caption" id="token-status" role="status" aria-live="polite"></p>
</section>

<section class="view stack" data-view="status" aria-labelledby="status-h">
<section class="card">
<h2 id="status-h">Status and backing</h2>
<p>If what is held for people and advertisers ever exceeds the (virtual) trust balance, the circuit opens and new sponsored offers stop.</p>
<div class="actions"><button type="button" class="btn primary" id="load-status">Load status</button></div>
<div id="status" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>Circuit</h2>
<div class="field"><label for="circuit-reason">Reason for opening the circuit</label><input id="circuit-reason"></div>
<div class="actions"><button type="button" class="btn danger" id="open-circuit">Open circuit</button><button type="button" class="btn" id="close-circuit">Close circuit</button></div>
<div id="circuit-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="review" aria-labelledby="review-h" hidden>
<section class="card">
<h2 id="review-h">Ad review</h2>
<p>Ads that need a person (sensitive claims, a public copy off the advertiser's website, appeals) wait here.</p>
<div class="actions"><button type="button" class="btn primary" id="v-queue">Show review queue</button></div>
<div id="v-out" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>Advertisers</h2>
<p>Verifying an advertiser lifts the 20,000 won daily limit.</p>
<div class="field"><label for="v-adv">Advertiser id</label><input id="v-adv" placeholder="adv_..."></div>
<div class="field"><label for="v-state">Verification</label><select id="v-state"><option value="verified">Verified</option><option value="unverified">Not verified</option><option value="rejected">Rejected</option></select></div>
<div class="actions"><button type="button" class="btn" id="v-verify">Save verification</button></div>
<div class="field"><label for="v-acct">Account status</label><select id="v-acct"><option value="active">Active</option><option value="suspended">Suspended</option></select></div>
<div class="actions"><button type="button" class="btn" id="v-status">Save account status</button></div>
<hr class="divider">
<h3>Refund an invalid view</h3>
<div class="field"><label for="v-resv">Reservation id of the invalid view</label><input id="v-resv" placeholder="h_..."></div>
<div class="field"><label for="v-reason">Reason</label><input id="v-reason"></div>
<div class="actions"><button type="button" class="btn danger" id="v-invalid">Mark invalid and refund</button></div>
<div class="field"><label for="v-reserve">Refund reserve (won)</label><input id="v-reserve" inputmode="numeric"></div>
<div class="actions"><button type="button" class="btn" id="v-fund">Add to reserve (virtual)</button></div>
<div id="v-ops" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="audit" aria-labelledby="audit-h" hidden>
<section class="card">
<h2 id="audit-h">Sponsorship audit</h2>
<p>Every month the same questions run with sponsorship off, on and off again, to check that the top three recommendations never change. Any change opens the circuit and stops sponsored offers.</p>
<div class="actions"><button type="button" class="btn primary" id="a-list">Show audits</button></div>
<div id="a-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view" data-view="invites" aria-labelledby="invites-h" hidden>
<div class="split">
<section class="card">
<h2 id="invites-h">Invitations</h2>
<p>Withdrawing an invitation also stops that person's agent keys.</p>
<div class="actions"><button type="button" class="btn primary" id="i-list">Show invitations</button></div>
<div id="i-out" role="status" aria-live="polite"></div>
</section>
<aside class="card">
<h2>Invite a person</h2>
<p class="caption">Invite by sign-in account id. A person sees their own account id under "Check my account" on the AI AD Coin page.</p>
<div class="field"><label for="i-id">Account id</label><input id="i-id"></div>
<div class="field"><label for="i-note">Note (optional)</label><input id="i-note"></div>
<button type="button" class="btn primary block" id="i-add">Invite</button>
</aside>
</div>
</section>

<section class="view stack" data-view="split" aria-labelledby="split-h" hidden>
<section class="card">
<h2 id="split-h">Revenue split (basis points)</h2>
<p>The parts add up to 10000. The person's share is at least 4000; operator plus direct costs are at most 4000.</p>
<div class="field"><label for="s-user">Person</label><input id="s-user" inputmode="numeric"></div>
<div class="field"><label for="s-operator">Operator</label><input id="s-operator" inputmode="numeric"></div>
<div class="field"><label for="s-direct">Direct costs</label><input id="s-direct" inputmode="numeric"></div>
<div class="field"><label for="s-platform">Platform</label><input id="s-platform" inputmode="numeric"></div>
<div class="actions"><button type="button" class="btn" id="load-split">Show current</button><button type="button" class="btn primary" id="save-split">Save split</button></div>
<div id="split-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="campaigns" aria-labelledby="campaigns-h" hidden>
<section class="card">
<h2 id="campaigns-h">Test campaigns</h2>
<div class="actions"><button type="button" class="btn primary" id="load-campaigns">Show campaigns</button></div>
<div id="campaign-out" role="status" aria-live="polite"></div>
<div class="table-wrap status-table"><table class="data-table" id="campaigns" hidden><thead><tr>
<th>Campaign</th><th>Product</th><th>Bid</th><th>Escrow</th><th>Status</th><th><span class="sr-only">Open</span></th></tr></thead><tbody></tbody></table></div>
</section>
<section class="card" id="c-detail" hidden aria-labelledby="c-detail-title">
<p class="eyebrow" id="c-detail-id"></p>
<h2 id="c-detail-title"></h2>
<div class="field"><label for="c-fund">Add budget (won, virtual)</label><input id="c-fund" inputmode="numeric" placeholder="50000"></div>
<div class="actions"><button type="button" class="btn primary" id="c-fund-go">Add budget</button><button type="button" class="btn" id="c-toggle">Pause</button><button type="button" class="btn" id="c-report">Report</button><button type="button" class="btn danger" id="c-refund">Refund and stop</button></div>
<div id="c-note" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>New test campaign</h2>
<div class="field"><label for="c-advertiser">Advertiser (house test)</label><input id="c-advertiser" value="House test"></div>
<div class="field"><label for="c-product">Product</label><select id="c-product"><option value="S1">S1 task sponsorship</option><option value="P2">P2 view and confirm</option><option value="B1">B1 signed offer for agents</option></select></div>
<div class="field"><label for="c-bid">Bid (won)</label><input id="c-bid" inputmode="numeric" value="1500"></div>
<div class="field"><label for="c-categories">Categories (comma separated)</label><input id="c-categories" value="deep_research"></div>
<div class="field"><label for="c-title">Headline</label><input id="c-title"></div>
<div class="field"><label for="c-body">Description</label><input id="c-body"></div>
<div class="field"><label for="c-question">Confirmation question</label><input id="c-question"></div>
<div class="field"><label for="c-answer">Answer</label><input id="c-answer"></div>
<div class="field"><label for="c-url">Public copy URL (https)</label><input id="c-url" value="https://agentconcierge.biz/ad-coin/test-offer"></div>
<div class="actions"><button type="button" class="btn primary" id="create">Create campaign</button></div>
</section>
</section>

<section class="view stack" data-view="products" aria-labelledby="products-h" hidden>
<section class="card">
<h2 id="products-h">Test products</h2>
<p>Hidden workflow products built from real catalog agents. They are not listed with public workflows and their runs are simulated. Agents that look like they move money or change state, and paid agents that cannot take coins, are refused.</p>
<div class="field"><label for="t-name">Name</label><input id="t-name" placeholder="Market brief"></div>
<div class="field"><label for="t-desc">Description</label><input id="t-desc"></div>
<div class="field"><label for="t-steps">Steps (agent id x calls per run, comma separated)</label><input id="t-steps" placeholder="74x5, 484x2, 32926x1"></div>
<div class="actions"><button type="button" class="btn primary" id="t-create">Create product</button><button type="button" class="btn" id="t-list">Show products</button></div>
<div id="t-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="ops" aria-labelledby="ops-h" hidden>
<section class="card">
<h2 id="ops-h">Runs and settlement (simulated)</h2>
<div class="field"><label for="x-id">AI AD Coin run id</label><input id="x-id" placeholder="x_..."></div>
<label class="check"><input id="x-ok" type="checkbox" checked><span>Succeeded</span></label>
<div class="actions"><button type="button" class="btn" id="complete">Mark run complete</button></div>
<div class="field"><label for="r-ids">Published workflow run ids (comma separated, one per quoted run)</label><input id="r-ids"></div>
<div class="actions"><button type="button" class="btn" id="settle-runs">Settle from run records</button></div>
<div class="note">{info}<p>Sponsored runs and coin payments for published workflows settle from the real run records: only the calls that succeeded at each step are paid, and the rest goes back to whoever paid. A customer's private workflows settle in that customer's own session.</p></div>
<div class="field"><label for="p-id">Provider id</label><input id="p-id" placeholder="r123"></div>
<div class="actions"><button type="button" class="btn" id="settle">Settle (virtual)</button><button type="button" class="btn" id="sweep">Sweep dormant agent wallets</button></div>
<div id="ops-out" role="status" aria-live="polite"></div>
</section>
</section>
</main>
</div>
</body>
</html>
""".replace('{sun}', ICON['sun']).replace('{moon}', ICON['moon']).replace('{sidebar}', SIDEBAR).replace('{info}', ICON['info'])

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',KEY='adCoinAdmin',token='';try{token=sessionStorage.getItem(KEY)||''}catch(e){}
var $=function(id){return document.getElementById(id)};
function say(id,t){var box=$(id);box.textContent='';String(t).split('\n').forEach(function(line){if(line){var p=document.createElement('p');p.textContent=line;box.appendChild(p)}})}
function call(path,body,method){var init={method:method||(body?'POST':'GET'),headers:{'Authorization':'Bearer '+token}};
  if(body){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.message||d.error||'Request failed');return d})})}
function key(){return Date.now().toString(36)+Math.random().toString(36).slice(2,8)}
function won(n){return Number(n||0).toLocaleString('en-US')+' won'}
$('save').onclick=function(){token=$('token').value.trim();try{sessionStorage.setItem(KEY,token)}catch(e){}say('token-status','Token set for this tab.')};
$('load-status').onclick=function(){say('status','Loading...');
  Promise.all([call('/status'),call('/admin/invariant')]).then(function(v){var s=v[0],i=v[1];
    say('status',['Payments: '+(s.payments==='closed'?'closed':s.payments)+' · Test mode: '+(s.test_mode?'yes':'no'),
      'Circuit: '+(s.circuit.open?'open ('+s.circuit.reason+')':'closed'),
      'Backing: '+(i.ok?'sound':'problem '+i.problems.join(', '))+' · held for others '+won(i.obligations_won)+' / trust '+won(i.trust_statement_won),
      'Coins held for people '+won(i.coin_liability_won)+' · unbalanced journals '+i.unbalanced_journals].join('\n'))})
  .catch(function(e){say('status',e.message)})};
$('open-circuit').onclick=function(){call('/admin/circuit',{open:true,reason:$('circuit-reason').value||'manual'}).then(function(c){say('circuit-out','Circuit opened: '+c.reason)}).catch(function(e){say('circuit-out',e.message)})};
$('close-circuit').onclick=function(){call('/admin/circuit',{open:false}).then(function(){say('circuit-out','Circuit closed.')}).catch(function(e){say('circuit-out',e.message)})};
var parts=['user','operator','direct','platform'];
$('load-split').onclick=function(){call('/admin/settings').then(function(d){parts.forEach(function(p){$('s-'+p).value=d.split_bps[p]});say('split-out','')}).catch(function(e){say('split-out',e.message)})};
$('save-split').onclick=function(){var v={};parts.forEach(function(p){v[p]=parseInt($('s-'+p).value,10)});
  call('/admin/settings',{split_bps:v},'PUT').then(function(){say('split-out','Saved.')}).catch(function(e){say('split-out',e.message)})};
$('create').onclick=function(){$('create').disabled=true;call('/admin/campaigns',{advertiser:$('c-advertiser').value,product:$('c-product').value,
    bid_won:parseInt($('c-bid').value,10),categories:$('c-categories').value.split(',').map(function(x){return x.trim()}).filter(Boolean),
    title:$('c-title').value,body:$('c-body').value,question:$('c-question').value,answer:$('c-answer').value,public_url:$('c-url').value})
  .then(function(c){say('campaign-out','Created '+c.id+'. Add budget before it can serve.');list()}).catch(function(e){say('campaign-out',e.message)})
  .finally(function(){$('create').disabled=false})};
function action(label,fn,plain,danger){var b=document.createElement('button');b.type='button';b.textContent=label;
  b.className='btn small'+(plain?'':' primary')+(danger?' danger':'');b.onclick=fn;return b}
var picked=null;
function list(){var table=$('campaigns'),body=table.querySelector('tbody');say('campaign-out','Loading...');
  call('/admin/campaigns').then(function(d){body.textContent='';table.hidden=!d.campaigns.length;say('campaign-out',d.campaigns.length?'':'No campaigns yet.');
    d.campaigns.forEach(function(c){var tr=document.createElement('tr');
      [c.advertiser+' · '+c.title,c.product,won(c.bid_won),won(c.escrow_won)].forEach(function(t){var td=document.createElement('td');td.textContent=t;tr.appendChild(td)});
      var st=document.createElement('td'),b=document.createElement('span');b.className='badge'+(c.status==='active'?' success':'');b.textContent=c.status==='active'?'Active':'Paused';st.appendChild(b);tr.appendChild(st);
      var td=document.createElement('td');td.appendChild(action('Open',function(){open(c)},true));tr.appendChild(td);
      body.appendChild(tr);if(picked&&picked.id===c.id)open(c)})}).catch(function(e){say('campaign-out',e.message)})}
function open(c){picked=c;$('c-detail').hidden=false;$('c-detail-id').textContent=c.product+' · '+c.id;$('c-detail-title').textContent=c.advertiser+' · '+c.title;
  $('c-toggle').textContent=c.status==='active'?'Pause':'Resume'}
function done(m){return function(){say('c-note',m);list()}}
function fail(e){say('c-note',e.message)}
$('c-fund-go').onclick=function(){call('/admin/campaigns/fund',{campaign_id:picked.id,amount_won:parseInt($('c-fund').value,10),idempotency_key:key()}).then(done('Budget added.')).catch(fail)};
$('c-toggle').onclick=function(){call('/admin/campaigns/status',{campaign_id:picked.id,status:picked.status==='active'?'paused':'active'}).then(done('Status changed.')).catch(fail)};
$('c-refund').onclick=function(){call('/admin/campaigns/refund',{campaign_id:picked.id,idempotency_key:key()}).then(done('Escrow returned and campaign stopped.')).catch(fail)};
$('c-report').onclick=function(){call('/admin/campaigns/report?campaign_id='+encodeURIComponent(picked.id)).then(function(r){
  say('c-note','Approved views '+r.approved_views+' (people '+r.people+') · sponsored runs started '+r.sponsored_runs_started+' / succeeded '+r.sponsored_runs_succeeded+' · agent receipts '+r.agent_receipts)}).catch(fail)};
$('load-campaigns').onclick=list;
function steps(){return $('t-steps').value.split(',').map(function(x){return x.trim()}).filter(Boolean).map(function(x){var p=x.toLowerCase().split('x');return {resource_id:parseInt(p[0],10),calls_per_run:parseInt(p[1]||'1',10)}})}
function products(){var box=$('t-out');say('t-out','Loading...');call('/admin/test-products').then(function(d){say('t-out',d.test_products.length?'':'No test products yet.');
  d.test_products.forEach(function(p){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=p.id+' · '+p.name+' · '+(p.status==='active'?'active':'archived')+' · '+p.steps.map(function(s){return s.resource_id+'x'+s.calls_per_run}).join(', ');row.appendChild(t);
    if(p.status==='active')row.appendChild(action('Archive',function(){call('/admin/test-products/archive',{id:p.id}).then(products).catch(function(e){t.textContent=e.message})},true));
    box.appendChild(row)})}).catch(function(e){say('t-out',e.message)})}
$('t-list').onclick=products;
function invites(){var box=$('i-out');say('i-out','Loading...');call('/admin/invites').then(function(d){say('i-out',d.invites.length?'':'No invitations yet.');
  d.invites.forEach(function(v){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=v.customer_id+' · '+(v.status==='invited'?'invited':'withdrawn')+(v.note?' · '+v.note:'');row.appendChild(t);
    if(v.status==='invited')row.appendChild(action('Withdraw',function(){call('/admin/invites/revoke',{customer_id:v.customer_id}).then(invites).catch(function(e){t.textContent=e.message})},true,true));
    box.appendChild(row)})}).catch(function(e){say('i-out',e.message)})}
$('i-list').onclick=invites;
function queue(){say('v-out','Loading...');call('/admin/reviews').then(function(d){var box=$('v-out');say('v-out',d.queue.length?'':'No ads waiting for review.');
  d.queue.forEach(function(q){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=q.advertiser+' · '+q.title+' — '+q.body+' · '+q.public_url+(q.note?' · '+q.note:'');row.appendChild(t);
    [['eligible','Approve'],['eligible_limited','Approve (limited)'],['disapproved','Disapprove']].forEach(function(d){row.appendChild(action(d[1],function(){
      call('/admin/reviews/decide',{creative_id:q.creative_id,decision:d[0]}).then(queue).catch(function(e){t.textContent=e.message})},d[0]!=='eligible',d[0]==='disapproved'))});
    box.appendChild(row)})}).catch(function(e){say('v-out',e.message)})}
$('v-queue').onclick=queue;
$('v-verify').onclick=function(){call('/admin/advertisers/verification',{advertiser_id:$('v-adv').value.trim(),verification:$('v-state').value}).then(function(a){say('v-ops',a.name+': '+a.verification)}).catch(function(e){say('v-ops',e.message)})};
$('v-status').onclick=function(){call('/admin/advertisers/status',{advertiser_id:$('v-adv').value.trim(),status:$('v-acct').value}).then(function(a){say('v-ops',a.name+': '+a.status)}).catch(function(e){say('v-ops',e.message)})};
$('v-invalid').onclick=function(){call('/admin/invalid-activity',{reservation_id:$('v-resv').value.trim(),reason:$('v-reason').value||'invalid'}).then(function(r){say('v-ops','Refunded '+won(r.refunded_won)+' (the person keeps their coins).')}).catch(function(e){say('v-ops',e.message)})};
$('v-fund').onclick=function(){call('/admin/platform-reserve',{amount_won:parseInt($('v-reserve').value,10),idempotency_key:key()}).then(function(r){say('v-ops','Refund reserve '+won(r.reserve_won))}).catch(function(e){say('v-ops',e.message)})};
$('a-list').onclick=function(){say('a-out','Loading...');call('/admin/audits').then(function(d){
  say('a-out',d.audits.length?d.audits.map(function(a){return new Date(a.created_at*1000).toLocaleString('en-US')+' · '+(a.inconclusive?'inconclusive':a.passed?'passed':'failed')+
    ' · same '+a.counts.same+', changed '+a.counts.changed+', unstable '+a.counts.unstable+', errors '+a.counts.error+(a.changed_queries.length?' · changed questions: '+a.changed_queries.join(' / '):'')}).join('\n'):'No audits yet.')})
  .catch(function(e){say('a-out',e.message)})};
$('i-add').onclick=function(){call('/admin/invites',{customer_id:$('i-id').value.trim(),note:$('i-note').value}).then(invites).catch(function(e){say('i-out',e.message)})};
$('t-create').onclick=function(){$('t-create').disabled=true;call('/admin/test-products',{name:$('t-name').value,description:$('t-desc').value,steps:steps()})
  .then(function(p){say('t-out','Created '+p.id);setTimeout(products,300)}).catch(function(e){say('t-out',e.message)}).finally(function(){$('t-create').disabled=false})};
$('complete').onclick=function(){var ok=$('x-ok').checked,digest='sha256:'+'0'.repeat(64);
  call('/admin/executions/complete',{execution_id:$('x-id').value.trim(),ok:ok,result_digest:ok?digest:null}).then(function(r){say('ops-out',r.status==='succeeded'?'Marked succeeded; the provider payout is scheduled.':'Marked failed; coins and the sponsored run were returned.')}).catch(function(e){say('ops-out',e.message)})};
$('settle-runs').onclick=function(){var ids=$('r-ids').value.split(',').map(function(x){return x.trim()}).filter(Boolean);
  call('/admin/executions/settle-from-runs',{execution_id:$('x-id').value.trim(),run_ids:ids}).then(function(r){
    say('ops-out',r.status==='waiting'?'A run is still in progress: '+r.run:'Settlement: '+r.status+' · paid '+won(r.paid_won)+' · refunded '+won(r.refunded_won)+' · succeeded calls per step '+r.line_calls_succeeded.join(', '))})
  .catch(function(e){say('ops-out',e.message)})};
$('settle').onclick=function(){call('/admin/settle',{provider:$('p-id').value.trim(),idempotency_key:key()}).then(function(r){say('ops-out',r.status==='settled'?'Settled (virtual) '+won(r.won):'Nothing to pay.')}).catch(function(e){say('ops-out',e.message)})};
$('sweep').onclick=function(){call('/admin/sweep-dormant',{}).then(function(r){say('ops-out','Swept '+r.swept_wallets+' wallets, '+r.coins+' coins.')}).catch(function(e){say('ops-out',e.message)})};
function show(view){if(!document.querySelector('[data-view="'+view+'"]'))view='status';
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(v){v.hidden=v.dataset.view!==view});
  Array.prototype.forEach.call(document.querySelectorAll('[data-view-link]'),function(a){var on=a.dataset.viewLink===view;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')})}
window.addEventListener('hashchange',function(){show(location.hash.slice(1))});
show(location.hash.slice(1)||'status');
})();
"""
