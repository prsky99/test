"""Closed-test page for invited people: wallet, a sponsored-run card, receipts
and mandates. Public copy is English. Fixed text renders as HTML at once; each
region loads only when its button is pressed, and independent loads run in
parallel. Data is always written with textContent, never as markup."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>AI AD Coin closed test</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#5d5d58;--card:#fff;--line:#d9d9d3;--accent:#0f6e66;--ad:#8a4b00}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#f0efe9;--muted:#b4b2a8;--card:#1f1f1d;--line:#3a3a36;--accent:#4fc2b6;--ad:#f0b25c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:0 0 8px}
p{margin:6px 0}.muted{color:var(--muted)}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
button{font:inherit;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:8px;padding:8px 14px;cursor:pointer;min-height:40px}
button.secondary{background:transparent;color:var(--accent)}button:disabled{opacity:.5;cursor:default}
input{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);min-height:40px;width:100%}
label{display:block;font-size:14px;color:var(--muted);margin-top:8px}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.ad{color:var(--ad);font-weight:700}.out{white-space:pre-wrap;font-size:14px;margin-top:10px;min-height:1em}
.status{font-size:14px;color:var(--muted);margin-top:8px;text-align:center}
ul{padding-left:20px;margin:6px 0}
</style></head><body><main>
<h1>AI AD Coin</h1>
<p class="muted">Closed test. Budgets and coins are virtual, payments are closed and nothing here has cash value.</p>
<p>Sponsors can pay for work you already chose. They never change which agent was recommended or how well it works.</p>

<section aria-labelledby="access-h"><h2 id="access-h">Your invitation</h2>
<p class="muted">Paste the visitor token you were invited with. It stays in this tab only.</p>
<label for="token">Visitor token</label><input id="token" autocomplete="off" spellcheck="false">
<div class="row"><button id="save">Use this token</button></div><p class="status" id="access-status" aria-live="polite"></p></section>

<section aria-labelledby="wallet-h"><h2 id="wallet-h">Wallet</h2>
<p class="muted">Coins earned through your agents are kept in your name. You can move them between your wallets or call them back at any time.</p>
<div class="row"><button id="load-wallet" class="secondary">Show wallet</button></div>
<div class="out" id="wallet" aria-live="polite"></div></section>

<section aria-labelledby="try-h"><h2 id="try-h">Try a sponsored run</h2>
<p class="muted">Example: comparing five papers in full text needs a paid agent (60 coins). See how a sponsor could cover it.</p>
<div class="row"><button id="quote" class="secondary">Show funding options</button></div>
<div id="card" hidden>
<p class="ad" id="card-label"></p><p id="card-text"></p><p class="muted" id="card-digest"></p>
<p id="card-question"></p><label for="answer">Your answer</label><input id="answer" autocomplete="off">
<div class="row"><button id="approve">Approve and view (15 seconds)</button><button id="decline" class="secondary">Keep the free result</button></div>
<p class="status" id="timer" aria-live="polite"></p><p class="muted" id="card-notice"></p></div>
<div class="out" id="quote-out" aria-live="polite"></div></section>

<section aria-labelledby="receipts-h"><h2 id="receipts-h">Receipts and mandates</h2>
<p class="muted">Every view, reward, transfer and run has a signed receipt. Mandates limit what an agent may spend without asking you.</p>
<div class="row"><button id="load-receipts" class="secondary">Show receipts</button><button id="load-mandates" class="secondary">Show mandates</button></div>
<div class="out" id="receipts" aria-live="polite"></div><div class="out" id="mandates" aria-live="polite"></div></section>
</main><script src="/ad-coin/app.js"></script></body></html>
"""

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',KEY='adCoinToken',token='';
try{token=sessionStorage.getItem(KEY)||''}catch(e){}
var $=function(id){return document.getElementById(id)};
function say(id,text){$(id).textContent=text}
function call(path,body){
  var init={method:body?'POST':'GET',headers:{'X-Visitor-Token':token,'X-Agent-Name':'concierge-web'}};
  if(body){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.message||d.error||'Request failed');return d})});
}
function busy(id,on){$(id).disabled=on}
$('token').value=token?'saved':'';
$('save').onclick=function(){token=$('token').value.trim();try{sessionStorage.setItem(KEY,token)}catch(e){}say('access-status','Token set for this tab.')};
$('load-wallet').onclick=function(){busy('load-wallet',true);say('wallet','Loading...');
  call('/wallets').then(function(d){var lines=['Total: '+d.total_coins+' coins (no cash value)'];
    d.wallets.forEach(function(w){lines.push((w.kind==='user'?'Your wallet':'Agent '+w.agent)+': '+w.available_coins+' coins')});
    var box=$('wallet');box.textContent=lines.join('\n');
    d.vouchers.forEach(function(v){var row=document.createElement('div');row.className='row';
      var text=document.createElement('span');text.textContent='Sponsored run ready: '+v.task_ref+' with '+v.provider+' ';
      var run=document.createElement('button');run.textContent='Run it';
      run.onclick=function(){run.disabled=true;call('/vouchers/redeem',{voucher_id:v.id}).then(function(r){
        text.textContent='Run started ('+r.execution_id+'). Test mode: the provider result and settlement are simulated.';run.remove()})
        .catch(function(e){text.textContent=e.message;run.disabled=false})};
      row.appendChild(text);row.appendChild(run);box.appendChild(row)})})
  .catch(function(e){say('wallet',e.message)}).finally(function(){busy('load-wallet',false)})};
var current=null;
$('quote').onclick=function(){busy('quote',true);say('quote-out','Loading...');$('card').hidden=true;
  var selection={items:[{agent:'openscholar-finder',price:'free'},{agent:'research-pro',price_coins:60}],chosen:'research-pro'};
  call('/quotes',{selection:selection,task:{provider:'research-pro',task_ref:'compare-5-papers',price_won:600,category:'deep_research/academic'}})
  .then(function(p){say('quote-out','');var opt=null;
    p.funding_options.forEach(function(o){if(!opt&&o.type==='sponsored_run')opt=o;if(!opt&&o.type==='coin_reward')opt=o.items[0]});
    if(!opt){say('quote-out','No sponsor is available now ('+(p.sponsorship_unavailable_reason||'none')+'). The free result is ready.');return}
    current={rid:opt.reservation_id};
    say('card-label','[Ad | Sponsored offer] '+opt.sponsor);
    say('card-text',opt.title+' - '+opt.body+(opt.coins?' You receive '+opt.coins+' coins.':' This covers one run of the task.'));
    say('card-digest','The recommendation was fixed before this offer (check code '+p.selection_digest.slice(7,15)+').');
    say('card-question',opt.question);say('card-notice',p.ai_generation_notice);$('card').hidden=false})
  .catch(function(e){say('quote-out',e.message)}).finally(function(){busy('quote',false)})};
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
})();
"""
