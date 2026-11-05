"""Closed-test page for invited people: account, agent keys, wallet, a sponsored-run
card, receipts and mandates. Public copy is English.

It uses the Agent Concierge "Pearl Connection" design system as it is (shared files
under /new/en/assets, the workspace shell and shared components; no page-local
styles). Fixed text renders as HTML at once; each region loads only when its button
is pressed, and independent loads run in parallel. Data is always written with
textContent, never as markup."""
from .advertiser_page import ICON

VIEWS = (('account', 'Your account', 'user'), ('agents', 'Your agents', 'team'), ('wallet', 'Wallet', 'receipt'),
         ('try', 'Sponsored run', 'megaphone'), ('receipts', 'Receipts', 'chart'))

SIDEBAR = ''.join(
    '<a class="side-item%s" href="#%s" data-view-link="%s"%s>%s%s</a>\n' % (
        ' active' if key == 'account' else '', key, key, ' aria-current="page"' if key == 'account' else '', ICON[icon], label)
    for key, label, icon in VIEWS)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, noarchive">
<meta name="referrer" content="no-referrer">
<title>AI AD Coin | Agent Concierge</title>
<link rel="icon" href="/new/en/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/new/en/assets/styles.css">
<link rel="stylesheet" href="/new/en/assets/necklace.css">
<link rel="stylesheet" href="/new/en/assets/pearl-live.css">
<script src="/new/en/assets/app.js" defer></script>
<script src="/ad-coin/app.js" defer></script>
</head>
<body data-page="ad-coin">
<a class="sr-only skip-link" href="#main">Skip to content</a>
<header class="ws-top">
<div class="container header-inner">
<a class="brand" href="/new/en/index.html"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>
<a class="small mobile-hidden" href="/new/en/chat.html">Back to Chat</a>
<div class="header-actions">
{sun}<button class="theme-toggle" type="button" data-action="theme" aria-label="Toggle dark theme" aria-pressed="false"></button>{moon}
</div>
<a class="btn small" href="/new/en/account.html">{user}Account</a>
</div>
</header>
<div class="container ws-layout">
<aside class="ws-sidebar" aria-label="AI AD Coin navigation">
<p class="caption">AI AD Coin</p>
<div class="row"><span class="badge warning">Closed test</span></div>
<hr class="divider">
{sidebar}</aside>
<main class="ws-main" id="main">
<div class="page-heading">
<p class="eyebrow">AI AD Coin · Closed test</p>
<h1>Coins for work you already chose.</h1>
<p class="lead">Sponsors can pay for work you already chose. They never change which agent was recommended or how well it works. Budgets and coins are virtual, payments are closed and nothing here has cash value.</p>
</div>

<section class="view stack" data-view="account" aria-labelledby="access-h">
<section class="card">
<h2 id="access-h">Your account</h2>
<p>AI AD Coin uses your workspace sign-in. Only invited accounts can take part in this closed test.</p>
<div class="actions"><button type="button" class="btn primary" id="account">Check my account</button></div>
<div id="access-status" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>Closed-test token</h2>
<p class="caption">Only if you were given a visitor token instead of a sign-in.</p>
<div class="field"><label for="token">Visitor token</label><input id="token" type="password" autocomplete="off" spellcheck="false"></div>
<div class="actions"><button type="button" class="btn" id="save">Use this token</button></div>
</section>
</section>

<section class="view stack" data-view="agents" aria-labelledby="keys-h" hidden>
<section class="card">
<h2 id="keys-h">Your agents</h2>
<p>Give an agent its own key so it can earn and spend coins for you. Each key works for one agent, is shown once, and stops working when you revoke it. Revoking also moves that agent's coins back to your wallet.</p>
<div class="field"><label for="agent-name">Agent name</label><input id="agent-name" autocomplete="off" placeholder="my-research-agent"></div>
<div class="actions"><button type="button" class="btn primary" id="create-key">Create agent key</button><button type="button" class="btn" id="list-keys">Show my agents</button></div>
<div id="keys" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="wallet" aria-labelledby="wallet-h" hidden>
<section class="card">
<h2 id="wallet-h">Wallet</h2>
<p>Coins earned through your agents are kept in your name. You can move them between your wallets or call them back at any time.</p>
<div class="actions"><button type="button" class="btn primary" id="load-wallet">Show wallet</button></div>
<div id="wallet" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="try" aria-labelledby="try-h" hidden>
<section class="card">
<h2 id="try-h">Try a sponsored run</h2>
<div class="review-steps">
<div><span class="pearl" aria-hidden="true"></span><p><strong>Check</strong></p><p class="caption">Find a paid upgrade.</p></div>
<div><span class="pearl" aria-hidden="true"></span><p><strong>Approve</strong></p><p class="caption">View one offer for 15 seconds.</p></div>
<div><span class="pearl" aria-hidden="true"></span><p><strong>Run</strong></p><p class="caption">The sponsor covers one run.</p></div>
</div>
<p>Paste the agent ids from a Chat answer, in the order shown, to check for a paid upgrade.</p>
<div class="note">{info}<p>For a multi-step task, write each step as id x calls (for example 109457x20, 116275x1). For a published workflow, write w, its id and the number of runs (for example w39x5); for a closed-test product, its id and runs (for example tp_0123456789abcdef x5); for your own saved workflow, its workspace and flow ids while signed in to your workspace (for example ws_.../wtf_... x5). One run of the whole task is what a sponsor can cover. Leave it empty to use an example (comparing five papers in full text, 60 coins).</p></div>
<div class="field"><label for="ids">Agent ids or steps from the answer (comma separated)</label><input id="ids" autocomplete="off"></div>
<div class="actions"><button type="button" class="btn primary" id="quote">Show funding options</button><button type="button" class="btn" id="products">Show test products</button></div>
<div id="product-list" role="status" aria-live="polite"></div>
<div id="quote-out" role="status" aria-live="polite"></div>
</section>
<section class="card" id="card" hidden aria-labelledby="card-label">
<span class="badge warning" id="card-label"></span>
<h3 id="card-text"></h3>
<p class="caption" id="card-digest"></p>
<div class="field"><label for="answer" id="card-question"></label><input id="answer" autocomplete="off"></div>
<div class="actions"><button type="button" class="btn primary" id="approve">Approve and view (15 seconds)</button><button type="button" class="btn" id="decline">Keep the free result</button></div>
<p class="caption" id="timer" aria-live="polite"></p>
<p class="caption" id="card-notice"></p>
</section>
</section>

<section class="view stack" data-view="receipts" aria-labelledby="receipts-h" hidden>
<section class="card">
<h2 id="receipts-h">Receipts and mandates</h2>
<p>Every view, reward, transfer and run has a signed receipt. Mandates limit what an agent may spend without asking you.</p>
<div class="actions"><button type="button" class="btn primary" id="load-receipts">Show receipts</button><button type="button" class="btn" id="load-mandates">Show mandates</button></div>
<div id="receipts" role="status" aria-live="polite"></div>
<div id="mandates" role="status" aria-live="polite"></div>
</section>
</section>
</main>
</div>
</body>
</html>
""".replace('{sun}', ICON['sun']).replace('{moon}', ICON['moon']).replace('{user}', ICON['user']).replace(
    '{sidebar}', SIDEBAR).replace('{info}', ICON['info'])

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',KEY='adCoinToken',token='',csrf='';
try{token=sessionStorage.getItem(KEY)||''}catch(e){}
var $=function(id){return document.getElementById(id)};
function say(id,value){var box=$(id);box.textContent='';String(value).split('\n').forEach(function(line){if(line){var p=document.createElement('p');p.textContent=line;box.appendChild(p)}})}
function lines(id){return Array.prototype.map.call($(id).querySelectorAll('p'),function(p){return p.textContent}).join('\n')}
function session(){if(csrf||token)return Promise.resolve();return fetch('/api/customer-auth/session',{credentials:'same-origin'})
  .then(function(r){return r.ok?r.json():{}}).then(function(s){if(s&&s.csrf_token)csrf=s.csrf_token}).catch(function(){})}
function call(path,body){return (body?session():Promise.resolve()).then(function(){return send(path,body)})}
function send(path,body){
  var init={method:body?'POST':'GET',credentials:'same-origin',headers:{'X-Agent-Name':'concierge-web'}};
  if(token)init.headers['X-Visitor-Token']=token;
  if(csrf)init.headers['X-Customer-CSRF']=csrf;
  if(body){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){if(r.status===401){location.href='/new/en/sign-in.html';throw new Error('Sign in to continue.')}
    return r.json().then(function(d){if(!r.ok)throw new Error(d.message||d.error||'Request failed');return d})});
}
function busy(id,on){var b=$(id);b.disabled=on;if(on)b.setAttribute('aria-busy','true');else b.removeAttribute('aria-busy')}
$('token').placeholder=token?'A token is set for this tab':'';
$('account').onclick=function(){say('access-status','Checking...');
  fetch('/api/customer-auth/session',{credentials:'same-origin'}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})
  .then(function(s){if(s&&s.csrf_token)csrf=s.csrf_token;return call('/account')})
  .then(function(a){say('access-status',!a.signed_in?a.message:a.invited?'Signed in and invited. Account id: '+a.account_id:
    'Signed in, not invited yet. Send this account id to the operator: '+a.account_id)})
  .catch(function(e){say('access-status',e.message)})};
function keyList(){var box=$('keys');say('keys','Loading...');call('/agent-keys').then(function(d){
  say('keys',d.agent_keys.length?'':'No agent keys yet.');d.agent_keys.forEach(function(k){var row=document.createElement('div');row.className='history-row';
    var t=document.createElement('span');t.textContent=k.agent+(k.last_used_at?' - last used '+new Date(k.last_used_at*1000).toLocaleString():' - not used yet');
    var b=document.createElement('button');b.type='button';b.className='btn small danger';b.textContent='Revoke';
    b.onclick=function(){b.disabled=true;call('/agents/revoke',{agent:k.agent}).then(function(r){t.textContent=k.agent+' revoked. '+r.coins+' coins moved to your wallet.';b.remove()})
      .catch(function(e){t.textContent=e.message;b.disabled=false})};row.appendChild(t);row.appendChild(b);box.appendChild(row)})}).catch(function(e){say('keys',e.message)})}
$('list-keys').onclick=keyList;
$('create-key').onclick=function(){busy('create-key',true);call('/agent-keys',{agent:$('agent-name').value.trim()}).then(function(k){
    say('keys','Key for '+k.agent+' (copy it now; it is shown once): '+k.agent_key+'\n'+k.use)})
  .catch(function(e){say('keys',e.message)}).finally(function(){busy('create-key',false)})};
$('save').onclick=function(){token=$('token').value.trim();try{sessionStorage.setItem(KEY,token)}catch(e){}say('access-status','Token set for this tab.')};
$('load-wallet').onclick=function(){busy('load-wallet',true);say('wallet','Loading...');
  call('/wallets').then(function(d){var lines=['Total: '+d.total_coins+' coins (no cash value)'];
    d.wallets.forEach(function(w){lines.push((w.kind==='user'?'Your wallet':'Agent '+w.agent)+': '+w.available_coins+' coins')});
    var box=$('wallet');say('wallet',lines.join('\n'));
    d.vouchers.forEach(function(v){var row=document.createElement('div');row.className='history-row';
      var text=document.createElement('span');text.textContent='Sponsored run ready: '+v.task_ref+' with '+v.provider+' ';
      var run=document.createElement('button');run.type='button';run.className='btn small primary';run.textContent='Run it';
      run.onclick=function(){run.disabled=true;call('/vouchers/redeem',{voucher_id:v.id}).then(function(r){
        text.textContent='Run started ('+r.execution_id+'). Test mode: the provider result and settlement are simulated.';run.remove()})
        .catch(function(e){text.textContent=e.message;run.disabled=false})};
      row.appendChild(text);row.appendChild(run);box.appendChild(row)})})
  .catch(function(e){say('wallet',e.message)}).finally(function(){busy('load-wallet',false)})};
var current=null;
$('quote').onclick=function(){busy('quote',true);say('quote-out','Loading...');$('card').hidden=true;
  var raw=$('ids').value.split(',').map(function(x){return x.trim()}).filter(Boolean);
  var pw=raw.length===1&&/^ws_[0-9a-f]{32}\/wtf_[0-9a-f]{32}(\s*x\d+)?$/i.test(raw[0])?raw[0].replace(/\s+/g,'').toLowerCase().split(/[\/x]/):null;
  var tp=!pw&&raw.length===1&&/^tp_[0-9a-f]{16}(\s*x\d+)?$/i.test(raw[0])?raw[0].replace(/\s+/g,'').toLowerCase().split('x'):null;
  var wf=!tp&&raw.length===1&&/^w\d+(x\d+)?$/i.test(raw[0])?raw[0].slice(1).toLowerCase().split('x'):null;
  var bundle=!wf&&!tp&&!pw&&raw.some(function(x){return /x/i.test(x)});
  var ids=(bundle||wf||tp||pw)?[]:raw.map(function(x){return parseInt(x,10)}).filter(function(x){return x>0});
  var steps=bundle?raw.map(function(x){var p=x.toLowerCase().split('x');return {resource_id:parseInt(p[0],10),calls:parseInt(p[1]||'1',10)}}):[];
  var example={selection:{items:[{agent:'openscholar-finder',price:'free'},{agent:'research-pro',price_coins:60}],chosen:'research-pro'},
    task:{provider:'research-pro',task_ref:'compare-5-papers',price_won:600,category:'deep_research/academic'}};
  var priced=function(b){
      var why={all_steps_free:'Every step is free, so no coins or sponsor are needed.',workflow_not_published:'This workflow is not published.',unknown_test_product:'This test product does not exist or was archived.',private_workflow_unavailable:'This saved workflow is not available to you.',
        no_catalog_steps:'No step links to a catalog agent, so it cannot be priced.',bundle_has_ineligible_step:'A paid step cannot take coins yet (grade below B or not live).'}[b.reason];
      if(!b.upgrade_available)throw new Error((why||'No paid upgrade ('+b.reason+').')+' The free result stays available.');
      say('quote-out',(b.workflow?(b.workflow.kind==='test_product'?'Test product "':b.workflow.kind==='private_workflow'?'Your workflow "':'Workflow "')+(b.workflow.name||b.workflow.id)+'", '+b.workflow.runs+' run(s)'+(b.workflow.upper_bound?' (upper bound; branches that do not run are refunded)':'')+': ':'Task of '+b.lines.length+' steps: ')+
        b.price_coins+' coins in total ('+b.lines.map(function(l){return l.calls+' x '+(l.name||l.resource_id)+' = '+l.won+' won'}).join('; ')+').'+
        (b.note?' '+b.note:'')+(b.sponsorable?'':' It cannot be sponsored at this price; pay with coins or keep the free result.'));
      if(!b.quote_request)throw new Error('This task costs more than a sponsor can cover.');
      return call('/quotes',b.quote_request)};
  var request=pw?call('/upgrade-check',{private_workflow:{workspace_id:pw[0],flow_id:pw[1],runs:parseInt(pw[2]||'1',10)}}).then(priced):tp?call('/upgrade-check',{test_product:{id:tp[0],runs:parseInt(tp[1]||'1',10)}}).then(priced):wf?call('/upgrade-check',{workflow:{template_id:parseInt(wf[0],10),runs:parseInt(wf[1]||'1',10)}}).then(priced):
    bundle?call('/upgrade-check',{bundle:steps}).then(function(b){
      if(!b.upgrade_available)throw new Error('This task needs no paid step or a step cannot take coins ('+b.reason+'). The free result stays available.');
      say('quote-out','Task of '+b.lines.length+' steps: '+b.price_coins+' coins in total ('+b.lines.map(function(l){return l.calls+' x '+(l.name||l.resource_id)+' = '+l.won+' won'}).join('; ')+').'+
        (b.sponsorable?'':' It cannot be sponsored at this price; pay with coins or keep the free result.'));
      if(!b.quote_request)throw new Error('This task costs more than a sponsor can cover.');
      return call('/quotes',b.quote_request)}):
    ids.length?call('/upgrade-check',{recommendation_ids:ids}).then(function(u){
      if(!u.upgrade_available)throw new Error('No paid upgrade for this answer ('+u.reason+'). The free result is the right choice.');
      say('quote-out','Paid option from the answer: '+u.target.name+' ('+u.target.price_coins+' coins, grade '+u.target.grade+').');
      if(!u.quote_request)throw new Error('This paid agent costs more than a sponsor can cover. Compare it with the free result first.');
      if(!u.sponsorable)say('quote-out','Paid option from the answer: '+u.target.name+' ('+u.target.price_coins+' coins). It is too small to sponsor; pay with coins or keep the free result.');
      return call('/quotes',u.quote_request)}):call('/quotes',example);
  request.then(function(p){var opt=null;if(lines('quote-out')==='Loading...')say('quote-out','');
    p.funding_options.forEach(function(o){if(!opt&&o.type==='sponsored_run')opt=o;if(!opt&&o.type==='coin_reward')opt=o.items[0]});
    if(!opt){var why={no_matching_sponsor:'no test sponsor bids enough for this task',task_below_minimum:'the task is below 50 coins',circuit_open:'sponsorship is paused'}[p.sponsorship_unavailable_reason]||'none';
      var before=lines('quote-out');say('quote-out',(before?before+'\n':'')+'No sponsor now: '+why+'. You can pay with coins ('+p.coin_quote_and_balance.price_coins+' needed, '+p.coin_quote_and_balance.available_coins+' available) or keep the free result.');return}
    current={rid:opt.reservation_id};say('timer','');$('answer').value='';
    say('card-label','[Ad | Sponsored offer] '+opt.sponsor);
    say('card-text',opt.title+' - '+opt.body+(opt.coins?' You receive '+opt.coins+' coins.':' This covers the whole task shown above, once.'));
    say('card-digest','The recommendation was fixed before this offer (check code '+p.selection_digest.slice(7,15)+').');
    say('card-question',opt.question);say('card-notice',p.ai_generation_notice);$('card').hidden=false})
  .catch(function(e){say('quote-out',e.message)}).finally(function(){busy('quote',false)})};
$('products').onclick=function(){var box=$('product-list');say('product-list','Loading...');call('/test-products').then(function(d){
  say('product-list',d.test_products.length?'':'No test products yet.');d.test_products.forEach(function(p){var row=document.createElement('div');row.className='history-row';
    var t=document.createElement('span');t.textContent=p.name+' ('+p.steps.length+' agents) ';var use=document.createElement('button');use.type='button';use.className='btn small';use.textContent='Use 5 runs';
    use.onclick=function(){$('ids').value=p.id+'x5';$('quote').click()};row.appendChild(t);row.appendChild(use);box.appendChild(row)})}).catch(function(e){say('product-list',e.message)})};
$('decline').onclick=function(){if(!current)return;call('/declines',{reservation_id:current.rid}).then(function(){
  $('card').hidden=true;say('quote-out','Declined. Your free result is unchanged.')}).catch(function(e){say('quote-out',e.message)})};
$('approve').onclick=function(){if(!current)return;busy('approve',true);
  call('/consents',{reservation_id:current.rid}).then(function(c){var left=15,shown=0,start=Date.now();
    var tick=setInterval(function(){if(document.visibilityState==='visible')shown+=250;left=Math.max(0,15-Math.floor(shown/1000));
      say('timer',left?left+' seconds left':'Done. Send your answer.');if(!left){clearInterval(tick);finish(c.consent_id,shown)}},250)})
  .catch(function(e){say('quote-out',e.message);busy('approve',false)})};
function finish(consent,shown){call('/exposures',{reservation_id:current.rid,consent_id:consent,displayed_ms:shown,
    answer:$('answer').value,foreground:true})
  .then(function(r){$('card').hidden=true;say('quote-out',r.voucher_id?'Your sponsored run is ready. Run it from the wallet.':'You received '+r.coins+' coins.')})
  .catch(function(e){say('quote-out',e.message)}).finally(function(){busy('approve',false)})}
$('load-receipts').onclick=function(){say('receipts','Loading...');call('/receipts').then(function(d){
  say('receipts',d.receipts.length?d.receipts.map(function(r){return r.kind+' - '+new Date(r.issued_at*1000).toLocaleString()+' - signed '+r.key_id}).join('\n'):'No receipts yet.')})
  .catch(function(e){say('receipts',e.message)})};
$('load-mandates').onclick=function(){say('mandates','Loading...');call('/mandates').then(function(d){
  say('mandates',d.mandates.length?d.mandates.map(function(m){return m.agent+': '+m.spent_coins+'/'+m.total_coins+' coins, '+m.state}).join('\n'):'No mandates.')})
  .catch(function(e){say('mandates',e.message)})};
function show(view){if(!document.querySelector('[data-view="'+view+'"]'))view='account';
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(v){v.hidden=v.dataset.view!==view});
  Array.prototype.forEach.call(document.querySelectorAll('[data-view-link]'),function(a){var on=a.dataset.viewLink===view;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')})}
window.addEventListener('hashchange',function(){show(location.hash.slice(1))});
show(location.hash.slice(1)||'account');
})();
"""
