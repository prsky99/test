"""Advertiser console page (English, signed-in invited customers).

It uses the Agent Concierge "Pearl Connection" design system as it is: the shared
stylesheets and app.js under /new/en/assets, the workspace shell (ws-top header,
ws-sidebar, ws-main, page-heading) and the shared components (card, field, btn,
badge, data-table, note, tabs, pearl steps). No page-local styles.

Screen policy (docs/FRONTEND_SCREEN_POLICY.md): the fixed frame is HTML and paints
at once; each view loads its data when it is opened, only inside that view; a busy
button shows aria-busy. Data is written with textContent only. Writes carry the
customer session's CSRF proof."""

ICON = {
    'sun': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>',
    'moon': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<path d="M21 13A9 9 0 0 1 11 3 9 9 0 1 0 21 13Z"/></svg>',
    'user': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="7" r="4"/>'
            '<path d="M4 22v-2a8 8 0 0 1 16 0v2"/></svg>',
    'home': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<path d="m3 10 9-8 9 8v12h-7v-8h-4v8H3Z"/></svg>',
    'megaphone': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                 '<path d="m3 11 18-5v12L3 14v-3Z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>',
    'plus': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg>',
    'chart': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
             '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>',
    'receipt': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
               '<path d="M5 2h14v20l-3-2-2 2-2-2-2 2-2-2-3 2Z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg>',
    'team': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<path d="M16 22v-2a6 6 0 0 0-12 0v2m16-1v-2a6 6 0 0 0-4-5"/><circle cx="10" cy="6" r="4"/>'
            '<path d="M17 2a4 4 0 0 1 0 8"/></svg>',
    'info': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/>'
            '<path d="M12 16v-4m0-4h.01"/></svg>',
    'arrow': '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
}

VIEWS = (('overview', 'Overview', 'home'), ('campaigns', 'Campaigns', 'megaphone'), ('create', 'New campaign', 'plus'),
         ('reports', 'Reports', 'chart'), ('billing', 'Billing & history', 'receipt'), ('team', 'Team', 'team'))

SIDEBAR = ''.join(
    '<a class="side-item%s" href="#%s" data-view-link="%s"%s>%s%s</a>\n' % (
        ' active' if key == 'overview' else '', key, key, ' aria-current="page"' if key == 'overview' else '', ICON[icon], label)
    for key, label, icon in VIEWS)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, noarchive">
<meta name="referrer" content="no-referrer">
<title>Advertising | Agent Concierge</title>
<link rel="icon" href="/new/en/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/new/en/assets/styles.css">
<link rel="stylesheet" href="/new/en/assets/necklace.css">
<link rel="stylesheet" href="/new/en/assets/pearl-live.css">
<script src="/new/en/assets/app.js" defer></script>
<script src="/ad-coin/advertiser.js" defer></script>
</head>
<body data-page="ad-coin-advertiser">
<a class="sr-only skip-link" href="#main">Skip to content</a>
<header class="ws-top">
<div class="container header-inner">
<a class="brand" href="/new/en/index.html"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>
<a class="small mobile-hidden" href="/new/en/explore.html">Back to discovery</a>
<div class="header-actions">
{sun}<button class="theme-toggle" type="button" data-action="theme" aria-label="Toggle dark theme" aria-pressed="false"></button>{moon}
</div>
<a class="btn small" href="/new/en/account.html">{user}Account</a>
</div>
</header>
<div class="container ws-layout">
<aside class="ws-sidebar" aria-label="Advertising navigation">
<p class="caption" id="side-account">Advertiser account</p>
<div class="row"><span class="badge" id="role-badge" hidden></span><span class="badge" id="verify-badge" hidden></span></div>
<hr class="divider">
{sidebar}</aside>
<main class="ws-main" id="main">
<div class="page-heading">
<p class="eyebrow">AI AD Coin · Closed test</p>
<h1>Advertising, approved by people.</h1>
<p class="lead">Sponsor AI work people already chose. Your ad never changes which agent is recommended; every view is approved and rewarded, and invalid views are refunded.</p>
<div class="field"><label for="account">Advertiser account</label><select id="account" aria-describedby="account-status"><option value="">Checking your accounts</option></select></div>
</div>

<section class="view stack" data-view="overview" aria-labelledby="overview-title">
<section class="card">
<h2 id="overview-title">Account status</h2>
<p id="account-status" role="status" aria-live="polite">Checking your session.</p>
<div id="account-facts"></div>
<div id="notifications"></div>
</section>
<section class="card">
<h2>How a campaign serves</h2>
<div class="review-steps">
<div><span class="pearl" aria-hidden="true"></span><p><strong>Create</strong></p><p class="caption">Choose the task categories and a bid.</p></div>
<div><span class="pearl" aria-hidden="true"></span><p><strong>Review</strong></p><p class="caption">Each ad is reviewed before it serves.</p></div>
<div><span class="pearl" aria-hidden="true"></span><p><strong>Fund</strong></p><p class="caption">Add budget; the daily budget is never exceeded.</p></div>
<div><span class="pearl" aria-hidden="true"></span><p><strong>Serve</strong></p><p class="caption">People approve each view; you pay only then.</p></div>
</div>
<div class="note">{info}<p>Closed test: budgets are virtual and nothing is charged.</p></div>
</section>
<section class="card">
<h2>Open an advertiser account</h2>
<p>You become its owner. Unverified accounts serve up to 20,000 won a day.</p>
<div class="field"><label for="a-name">Business name</label><input id="a-name" type="text" autocomplete="organization" required></div>
<div class="field"><label for="a-site">Website</label><input id="a-site" type="url" placeholder="https://example.com" required></div>
<div class="actions"><button type="button" class="btn primary" id="a-create">Open account</button></div>
<p class="caption" id="a-out" role="status" aria-live="polite"></p>
</section>
</section>

<section class="view stack" data-view="campaigns" aria-labelledby="campaigns-title" hidden>
<section class="card">
<div class="row"><h2 id="campaigns-title">Campaigns</h2></div>
<p id="c-out" role="status" aria-live="polite">Open this view to load your campaigns.</p>
<div class="table-wrap status-table"><table class="data-table" id="c-table" hidden><thead><tr><th>Campaign</th><th>Objective</th><th>Status</th><th>Bid</th><th>Today / daily</th><th>Budget left</th><th><span class="sr-only">Open</span></th></tr></thead><tbody></tbody></table></div>
</section>
<section class="card" id="detail" hidden aria-labelledby="d-title">
<p class="eyebrow" id="d-objective"></p>
<h2 id="d-title"></h2>
<p class="caption" id="d-facts"></p>
<div class="tabs" role="tablist" aria-label="Campaign sections">
<button class="tab" role="tab" type="button" id="tab-d-settings" aria-controls="panel-d-settings" data-tab="d-settings" aria-selected="true">Settings</button>
<button class="tab" role="tab" type="button" id="tab-d-ads" aria-controls="panel-d-ads" data-tab="d-ads" aria-selected="false" tabindex="-1">Ads</button>
<button class="tab" role="tab" type="button" id="tab-d-budget" aria-controls="panel-d-budget" data-tab="d-budget" aria-selected="false" tabindex="-1">Budget</button>
</div>
<div role="tabpanel" id="panel-d-settings" aria-labelledby="tab-d-settings" data-tab-panel="d-settings">
<div class="field"><label for="d-bid">Max bid per unit (won)</label><input id="d-bid" inputmode="numeric"></div>
<div class="field"><label for="d-daily">Daily budget (won)</label><input id="d-daily" inputmode="numeric"></div>
<div class="field"><label for="d-cap">Views per person per day (1 to 3)</label><input id="d-cap" inputmode="numeric"></div>
<div class="actions"><button type="button" class="btn primary" id="d-save">Save settings</button><button type="button" class="btn" id="d-toggle">Pause</button></div>
</div>
<div role="tabpanel" id="panel-d-ads" aria-labelledby="tab-d-ads" data-tab-panel="d-ads" hidden>
<div id="d-ads"></div>
<h3>Add an ad</h3>
<div class="field"><label for="na-title">Headline</label><input id="na-title" maxlength="80"></div>
<div class="field"><label for="na-body">Description</label><input id="na-body" maxlength="400"></div>
<div class="field"><label for="na-question">Confirmation question</label><input id="na-question" maxlength="160"></div>
<div class="field"><label for="na-answer">Answer</label><input id="na-answer" maxlength="40"></div>
<div class="field"><label for="na-url">Public copy of the ad (https, on your website)</label><input id="na-url" type="url"></div>
<div class="actions"><button type="button" class="btn" id="na-add">Add ad for review</button></div>
</div>
<div role="tabpanel" id="panel-d-budget" aria-labelledby="tab-d-budget" data-tab-panel="d-budget" hidden>
<p id="d-budget-now"></p>
<div class="field"><label for="d-fund">Add budget (won)</label><input id="d-fund" inputmode="numeric" placeholder="50000"></div>
<div class="actions"><button type="button" class="btn primary" id="d-fund-go">Add budget</button></div>
<p class="caption">Budget is held for this campaign and returned if you stop it.</p>
</div>
<p class="caption" id="d-out" role="status" aria-live="polite"></p>
</section>
</section>

<section class="view stack" data-view="create" aria-labelledby="create-title" hidden>
<section class="card">
<h2 id="create-title">New campaign</h2>
<div class="review-steps">
<div><span class="pearl" aria-hidden="true"></span><p><strong>Campaign</strong></p></div>
<div><span class="pearl" aria-hidden="true"></span><p>First ad</p></div>
<div><span class="pearl" aria-hidden="true"></span><p>Review</p></div>
</div>
<h3>Campaign</h3>
<div class="field"><label for="n-name">Name</label><input id="n-name" required></div>
<div class="field"><label for="n-objective">Objective</label><select id="n-objective">
<option value="S1">Sponsor a task: pay per sponsored run</option>
<option value="P2">View and confirm: pay per approved view</option>
<option value="B1">Signed offer for agents: pay per agent receipt</option></select></div>
<div class="field"><label for="n-categories">Task categories (comma separated)</label><input id="n-categories" placeholder="deep_research, dev_tools"></div>
<div class="field"><label for="n-exclude">Excluded categories (optional)</label><input id="n-exclude"></div>
<div class="field"><label for="n-bid">Max bid per unit (won)</label><input id="n-bid" inputmode="numeric" value="1500"></div>
<div class="field"><label for="n-daily">Daily budget (won, at least one bid)</label><input id="n-daily" inputmode="numeric" value="10000"></div>
<div class="field"><label for="n-cap">Views per person per day (1 to 3)</label><input id="n-cap" inputmode="numeric" value="3"></div>
<div class="field"><label for="n-end">End date (optional)</label><input id="n-end" type="date"></div>
<h3>First ad</h3>
<div class="field"><label for="n-title">Headline</label><input id="n-title" maxlength="80"></div>
<div class="field"><label for="n-body">Description</label><input id="n-body" maxlength="400"></div>
<div class="field"><label for="n-question">Confirmation question</label><input id="n-question" maxlength="160"></div>
<div class="field"><label for="n-answer">Answer</label><input id="n-answer" maxlength="40"></div>
<div class="field"><label for="n-url">Public copy of the ad (https, on your website)</label><input id="n-url" type="url"></div>
<div class="note">{info}<p>Medical, political, adult, gambling, weapon and drug categories are not available. Ads are reviewed before they serve.</p></div>
<div class="actions"><button type="button" class="btn primary" id="n-create">{arrow}Create campaign</button></div>
<p class="caption" id="n-out" role="status" aria-live="polite"></p>
</section>
</section>

<section class="view stack" data-view="reports" aria-labelledby="reports-title" hidden>
<section class="card">
<h2 id="reports-title">Reports</h2>
<div class="field"><label for="r-days">Period</label><select id="r-days"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option></select></div>
<div class="actions"><button type="button" class="btn primary" id="r-load">Show report</button><button type="button" class="btn" id="r-csv">Download CSV</button></div>
<p id="r-out" role="status" aria-live="polite"></p>
<div class="table-wrap status-table"><table class="data-table" id="r-table" hidden><thead><tr><th>Date</th><th>Offers</th><th>Views</th><th>People</th><th>View rate</th><th>Spend</th><th>Invalid refunded</th><th>Net spend</th><th>Cost per view</th><th>Runs</th></tr></thead><tbody></tbody></table></div>
</section>
</section>

<section class="view stack" data-view="billing" aria-labelledby="billing-title" hidden>
<section class="card">
<h2 id="billing-title">Statement</h2>
<p id="b-out" role="status" aria-live="polite">Open this view to load your statement.</p>
<div class="table-wrap status-table"><table class="data-table" id="b-table" hidden><thead><tr><th>When</th><th>Entry</th><th>Budget change</th><th>Campaign</th></tr></thead><tbody></tbody></table></div>
</section>
<section class="card">
<h2>Change history</h2>
<p id="h-out" role="status" aria-live="polite"></p>
<div class="table-wrap status-table"><table class="data-table" id="h-table" hidden><thead><tr><th>When</th><th>Change</th><th>Object</th><th>By</th></tr></thead><tbody></tbody></table></div>
</section>
</section>

<section class="view" data-view="team" aria-labelledby="team-title" hidden>
<div class="split">
<section class="card">
<h2 id="team-title">Members</h2>
<p id="m-out" role="status" aria-live="polite">Open this view to load your team.</p>
<div id="m-list"></div>
</section>
<aside class="card">
<h2>Add or change a member</h2>
<div class="field"><label for="m-id">Account id</label><input id="m-id" type="text"></div>
<div class="field"><label for="m-role">Role</label><select id="m-role"><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="owner">Owner</option><option value="removed">Remove access</option></select></div>
<div class="setting-row"><strong>Owner</strong><span class="caption">Budget, team and campaigns</span></div>
<div class="setting-row"><strong>Editor</strong><span class="caption">Campaigns and ads</span></div>
<div class="setting-row"><strong>Viewer</strong><span class="caption">Read only</span></div>
<button type="button" class="btn primary block" id="m-set">Save member</button>
<p class="caption">An account always keeps at least one owner.</p>
</aside>
</div>
</section>
</main>
</div>
</body>
</html>
""".replace('{sun}', ICON['sun']).replace('{moon}', ICON['moon']).replace('{user}', ICON['user']).replace(
    '{sidebar}', SIDEBAR).replace('{info}', ICON['info']).replace('{arrow}', ICON['arrow'])

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',csrf='',acct='',current=null,loaded={};
var $=function(id){return document.getElementById(id)};
function say(id,t,bad){var e=$(id);e.textContent=t;e.classList.toggle('error-text',!!bad)}
function won(n){return n==null?'-':Number(n).toLocaleString('en-US')+' won'}
function when(t){return new Date(t*1000).toLocaleString()}
function el(tag,text,cls){var e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function list(v){return v.split(',').map(function(x){return x.trim()}).filter(Boolean)}
function num(id){return parseInt($(id).value,10)}
function session(){if(csrf)return Promise.resolve();return fetch('/api/customer-auth/session',{credentials:'same-origin'})
  .then(function(r){return r.ok?r.json():{}}).then(function(s){csrf=s.csrf_token||''}).catch(function(){})}
function call(path,body){return session().then(function(){var init={method:body?'POST':'GET',credentials:'same-origin',headers:{}};
  if(body){init.headers['Content-Type']='application/json';init.headers['X-Customer-CSRF']=csrf;init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){return r.json().catch(function(){return {}}).then(function(d){
    if(r.status===401||d.error==='customer_session_required'){location.href='/new/en/sign-in.html';throw new Error('Sign in to continue.')}
    if(!r.ok)throw new Error(d.message||d.error||'Request failed');return d})})})}
function busy(button,promise){button.setAttribute('aria-busy','true');button.disabled=true;
  return promise.then(function(v){button.removeAttribute('aria-busy');button.disabled=false;return v},function(e){button.removeAttribute('aria-busy');button.disabled=false;throw e})}
function q(p){return p+(p.indexOf('?')<0?'?':'&')+'advertiser_id='+encodeURIComponent(acct)}
function badge(text,kind){var b=el('span',text,'badge'+(kind?' '+kind:''));return b}
var STATE={eligible:['Eligible','success'],eligible_limited:['Eligible (limited)','warning'],under_review:['Under review','warning'],
  disapproved:['Disapproved',''],serving:['Serving','success'],paused:['Paused',''],enabled:['Enabled','success'],removed:['Removed','']};
function stateBadge(s){var x=STATE[s]||[s,''];var b=badge(x[0],x[1]);if(s==='disapproved')b.classList.add('error-text');return b}
function rows(table,items,cells){var t=$(table),b=t.querySelector('tbody');b.textContent='';t.hidden=!items.length;
  items.forEach(function(it){var tr=el('tr');cells(it).forEach(function(v){var td=el('td');if(v&&v.nodeType)td.appendChild(v);else td.textContent=v==null?'':String(v);tr.appendChild(td)});b.appendChild(tr)})}
function needAccount(id){if(!acct){say(id,'Open an advertiser account first (Overview).',true);return false}return true}

/* views: the frame is HTML; a view loads its data the first time it is opened */
function show(view){if(!document.querySelector('[data-view="'+view+'"]'))view='overview';
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(v){v.hidden=v.dataset.view!==view});
  Array.prototype.forEach.call(document.querySelectorAll('[data-view-link]'),function(a){var on=a.dataset.viewLink===view;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  if(!loaded[view]&&LOAD[view]){loaded[view]=true;ready.then(LOAD[view])}}
window.addEventListener('hashchange',function(){show(location.hash.slice(1))});
var LOAD={campaigns:campaigns,billing:billing,team:team},ready;

function accounts(){return call('/advertisers').then(function(d){var s=$('account');s.textContent='';
  d.advertisers.forEach(function(a){var o=el('option',a.name);o.value=a.id;o.dataset.role=a.role;s.appendChild(o)});
  if(!d.advertisers.length){s.appendChild(el('option','No account yet'));acct='';say('account-status','No advertiser account yet. Open one below.');return}
  acct=s.value;return overview()}).catch(function(e){say('account-status',e.message,true)})}
$('account').onchange=function(){acct=this.value;loaded={overview:true};current=null;$('detail').hidden=true;overview()};
function overview(){say('account-status','Loading account.');return call(q('/advertiser')).then(function(d){var a=d.advertiser,f=$('account-facts');f.textContent='';
  var role=$('role-badge'),ver=$('verify-badge');role.hidden=ver.hidden=false;role.textContent=(a.role||'member').replace(/^./,function(c){return c.toUpperCase()});
  ver.textContent=a.verification==='verified'?'Verified':'Not verified';ver.className='badge'+(a.verification==='verified'?' success':' warning');
  say('account-status',a.name+' · '+a.website);$('side-account').textContent=a.name;
  [['Account status',stateBadge(a.status==='active'?'enabled':a.status)],['Verification',a.verification],
   ['Daily serving limit',a.limited_daily_won?won(a.limited_daily_won)+' until verified':'Your daily budgets']].forEach(function(x){
    var r=el('div',null,'history-row');r.appendChild(el('span',x[0]));var v=x[1];r.appendChild(v.nodeType?v:el('span',v));f.appendChild(r)});
  var n=$('notifications');n.textContent='';d.notifications.forEach(function(m){var box=el('div',null,'note'+(m.level==='error'||m.level==='warning'?' warn':''));box.appendChild(el('p',m.message));n.appendChild(box)})})
  .catch(function(e){say('account-status',e.message,true)})}
$('a-create').onclick=function(){var b=this;busy(b,call('/advertisers',{name:$('a-name').value,website:$('a-site').value})).then(function(a){say('a-out','Opened '+a.name+'.');ready=accounts();loaded={overview:true}}).catch(function(e){say('a-out',e.message,true)})};

function campaigns(){if(!needAccount('c-out'))return;say('c-out','Loading campaigns.');call(q('/advertiser/campaigns')).then(function(d){
  say('c-out',d.campaigns.length?d.campaigns.length+' campaign'+(d.campaigns.length>1?'s':''):'No campaigns yet. Create one in New campaign.');
  rows('c-table',d.campaigns,function(c){var st=el('span');st.appendChild(stateBadge(c.status));st.appendChild(document.createTextNode(' '));st.appendChild(stateBadge(c.review_status));
    var open=el('button','Open','btn small');open.type='button';open.onclick=function(){detail(c)};
    return [c.name,c.objective,st,won(c.bid_won),won(c.spent_today_won)+' / '+won(c.daily_budget_won),won(c.escrow_won),open]})}).catch(function(e){say('c-out',e.message,true)})}
function detail(c){current=c;var box=$('detail');box.hidden=false;$('d-title').textContent=c.name;$('d-objective').textContent=c.objective+' · '+c.serving;
  $('d-facts').textContent='Categories: '+c.categories.join(', ')+(c.excluded_categories.length?' · excluded: '+c.excluded_categories.join(', '):'');
  $('d-bid').value=c.bid_won;$('d-daily').value=c.daily_budget_won;$('d-cap').value=c.frequency_cap;
  $('d-toggle').textContent=c.status==='enabled'?'Pause':'Enable';$('d-budget-now').textContent='Budget left: '+won(c.escrow_won)+' (virtual)';
  var ads=$('d-ads');ads.textContent='';c.creatives.forEach(function(a){var r=el('div',null,'history-row');var left=el('div');left.appendChild(el('strong',a.title));
    if(a.review_note)left.appendChild(el('p',a.review_note,'caption'));r.appendChild(left);r.appendChild(stateBadge(a.review_status));
    var acts=el('div',null,'row');if(a.review_status==='disapproved'||a.review_status==='eligible_limited'){var why=el('input');why.placeholder='Why it should run';why.setAttribute('aria-label','Appeal reason for '+a.title);
      var ap=el('button','Appeal','btn small');ap.type='button';ap.onclick=function(){busy(ap,call('/advertiser/appeals',{advertiser_id:acct,creative_id:a.id,reason:why.value})).then(function(){say('d-out','Appeal sent; a person reviews it.')}).catch(function(e){say('d-out',e.message,true)})};
      acts.appendChild(why);acts.appendChild(ap)}
    var rm=el('button','Remove','btn small danger');rm.type='button';rm.onclick=function(){busy(rm,call('/advertiser/creatives/edit',{advertiser_id:acct,creative_id:a.id,remove:true})).then(detail).catch(function(e){say('d-out',e.message,true)})};
    acts.appendChild(rm);r.appendChild(acts);ads.appendChild(r)});
  box.scrollIntoView({block:'nearest'})}
$('d-save').onclick=function(){var b=this;busy(b,call('/advertiser/campaigns/update',{advertiser_id:acct,campaign_id:current.id,bid_won:num('d-bid'),daily_budget_won:num('d-daily'),frequency_cap:num('d-cap')}))
  .then(function(n){say('d-out','Saved.');detail(n);campaigns()}).catch(function(e){say('d-out',e.message,true)})};
$('d-toggle').onclick=function(){var b=this;busy(b,call('/advertiser/campaigns/update',{advertiser_id:acct,campaign_id:current.id,status:current.status==='enabled'?'paused':'enabled'}))
  .then(function(n){detail(n);campaigns()}).catch(function(e){say('d-out',e.message,true)})};
$('d-fund-go').onclick=function(){var b=this;busy(b,call('/advertiser/campaigns/fund',{advertiser_id:acct,campaign_id:current.id,amount_won:num('d-fund'),idempotency_key:Date.now().toString(36)}))
  .then(function(f){say('d-out','Budget now '+won(f.escrow_won)+' (virtual).');current.escrow_won=f.escrow_won;$('d-budget-now').textContent='Budget left: '+won(f.escrow_won)+' (virtual)';campaigns()}).catch(function(e){say('d-out',e.message,true)})};
$('na-add').onclick=function(){var b=this,body={advertiser_id:acct,campaign_id:current.id};['title','body','question','answer'].forEach(function(k){body[k]=$('na-'+k).value});body.public_url=$('na-url').value;
  busy(b,call('/advertiser/creatives',body)).then(function(n){say('d-out','Ad added. Review: '+n.creatives[n.creatives.length-1].review_status.replace('_',' ')+'.');detail(n)}).catch(function(e){say('d-out',e.message,true)})};

$('n-create').onclick=function(){if(!needAccount('n-out'))return;var b=this,end=$('n-end').value?Date.parse($('n-end').value+'T23:59:59')/1000:null;
  busy(b,call('/advertiser/campaigns',{advertiser_id:acct,objective:$('n-objective').value,name:$('n-name').value,categories:list($('n-categories').value),
    excluded_categories:list($('n-exclude').value),bid_won:num('n-bid'),daily_budget_won:num('n-daily'),frequency_cap:num('n-cap'),ends_at:end,
    creative:{title:$('n-title').value,body:$('n-body').value,question:$('n-question').value,answer:$('n-answer').value,public_url:$('n-url').value}}))
  .then(function(c){say('n-out','Created. Review: '+c.review_status.replace('_',' ')+'. Add budget to start serving.');loaded.campaigns=true;location.hash='campaigns';campaigns();detail(c)})
  .catch(function(e){say('n-out',e.message,true)})};

function reportPath(p){return q(p+'?days='+$('r-days').value)+(current?'&campaign_id='+encodeURIComponent(current.id):'')}
$('r-load').onclick=function(){if(!needAccount('r-out'))return;var b=this;busy(b,call(reportPath('/advertiser/report'))).then(function(d){
  rows('r-table',d.rows,function(r){return [r.date,r.offers,r.views,r.people,(r.view_rate*100).toFixed(1)+'%',won(r.spend_won),won(r.invalid_refunded_won),won(r.net_spend_won),won(r.cost_per_view_won),r.runs_succeeded+' / '+r.runs_started]});
  var x=d.totals;say('r-out',(d.rows.length?'':'No activity in this period. ')+'Total: '+x.views+' views of '+x.offers+' offers, net spend '+won(x.net_spend_won)+'. '+d.note+(current?' Showing '+current.name+'.':''))}).catch(function(e){say('r-out',e.message,true)})};
$('r-csv').onclick=function(){if(!needAccount('r-out'))return;location.href=API+reportPath('/advertiser/report.csv')};

function billing(){if(!needAccount('b-out'))return;say('b-out','Loading statement.');
  Promise.all([call(q('/advertiser/statement')),call(q('/advertiser/history'))]).then(function(r){
    say('b-out',r[0].entries.length?'':'No entries yet.');rows('b-table',r[0].entries,function(e){return [when(e.at),e.kind,won(e.escrow_change_won),e.campaign_id]});
    say('h-out',r[1].history.length?'':'No changes yet.');rows('h-table',r[1].history,function(h){return [when(h.at),h.action,h.object,h.actor]})}).catch(function(e){say('b-out',e.message,true)})}
function members(list){var box=$('m-list');box.textContent='';list.forEach(function(m){var r=el('div',null,'history-row');var left=el('div',null,'row');var p=el('span',null,'pearl small');p.setAttribute('aria-hidden','true');
  left.appendChild(p);left.appendChild(el('span',m.customer_id));r.appendChild(left);r.appendChild(badge(m.role.replace(/^./,function(c){return c.toUpperCase()})));box.appendChild(r)});
  say('m-out',list.length+' member'+(list.length>1?'s':''))}
function team(){if(!needAccount('m-out'))return;say('m-out','Loading team.');call(q('/advertiser')).then(function(d){members(d.members)}).catch(function(e){say('m-out',e.message,true)})}
$('m-set').onclick=function(){if(!needAccount('m-out'))return;var b=this;busy(b,call('/advertiser/members',{advertiser_id:acct,customer_id:$('m-id').value.trim(),role:$('m-role').value})).then(function(d){members(d.members)}).catch(function(e){say('m-out',e.message,true)})};

ready=accounts();   // the account list is this page's own content, so it loads with the page
show(location.hash.slice(1)||'overview');
})();
"""
