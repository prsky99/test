"""AI AD Coin operator console (Korean, admin token). Fixed text renders at once;
each panel loads when its button is pressed and the status panel fetches its
two sources in parallel. No dialogs or full-screen loading."""

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>AI AD Coin 운영</title>
<style>
:root{--bg:#f6f6f3;--fg:#1c1c1a;--muted:#5b5b55;--card:#fff;--line:#d8d8d1;--accent:#0f6e66;--warn:#a33a1f}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#efeee8;--muted:#b3b1a7;--card:#1f1f1d;--line:#3a3a36;--accent:#4fc2b6;--warn:#f08a6c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1040px;margin:0 auto;padding:20px 16px 60px}h1{font-size:24px;margin:0}h2{font-size:18px;margin:0 0 8px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0}
.muted{color:var(--muted)}.warn{color:var(--warn);font-weight:600}
button{font:inherit;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:7px;padding:6px 12px;cursor:pointer;min-height:36px}
button.secondary{background:transparent;color:var(--accent)}button:disabled{opacity:.5}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);min-height:36px}
label{font-size:13px;color:var(--muted);display:block;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.out{white-space:pre-wrap;font-size:13px;margin-top:8px;min-height:1em}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}th{white-space:nowrap}th,td{border-top:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.scroll{overflow-x:auto}
</style></head><body><main>
<h1>AI AD Coin 운영</h1>
<p class="muted">시험 모드입니다. 예산·코인·정산은 모두 가상 값이고, 결제와 실제 광고주 집행은 닫혀 있습니다. 광고는 자체 시험 캠페인만 씁니다.</p>

<section><h2>관리자 토큰</h2><p class="muted">이 탭에만 보관합니다.</p>
<input id="token" type="password" autocomplete="off" style="width:100%"><div class="row"><button id="save">사용</button><span id="token-status" class="muted" aria-live="polite"></span></div></section>

<section><h2>상태와 재원</h2><p class="muted">보관 중인 사용자·광고주 몫이 예치금(가상 신탁 잔액)을 넘으면 회로가 열려 새 후원 제안이 멈춥니다.</p>
<div class="row"><button id="load-status" class="secondary">불러오기</button></div><div class="out" id="status" aria-live="polite"></div>
<div class="row"><input id="circuit-reason" placeholder="회로를 여는 이유"><button id="open-circuit" class="secondary">회로 열기</button><button id="close-circuit" class="secondary">회로 닫기</button></div>
<div class="out" id="circuit-out" aria-live="polite"></div></section>

<section><h2>후원 감사</h2>
<p class="muted">매달 같은 질문을 후원 끔·켬·끔으로 돌려 추천 상위 3개가 바뀌는지 봅니다. 바뀐 질문이 하나라도 있으면 회로가 열려 후원 제안이 멈춥니다. 실행: <code>nice -n 10 .venv/bin/python -m scripts.ad_coin_sponsorship_audit</code></p>
<div class="row"><button id="a-list" class="secondary">감사 기록</button></div><div class="out" id="a-out" aria-live="polite"></div></section>

<section><h2>초대</h2>
<p class="muted">고객 로그인 계정 ID로 초대합니다. 사용자는 AI AD Coin 화면의 "Check my account"에서 자기 계정 ID를 볼 수 있습니다. 초대를 거두면 그 사람의 에이전트 키도 함께 멈춥니다.</p>
<div class="row"><input id="i-id" placeholder="계정 ID"><input id="i-note" placeholder="메모(선택)"><button id="i-add">초대</button><button id="i-list" class="secondary">목록</button></div>
<div class="out" id="i-out" aria-live="polite"></div></section>

<section><h2>배분율(만분율)</h2><p class="muted">합계 10000. 사용자 몫은 4000 이상, 운영자+직접비는 4000 이하여야 합니다.</p>
<div class="grid"><div><label for="s-user">사용자</label><input id="s-user" inputmode="numeric"></div>
<div><label for="s-operator">운영자</label><input id="s-operator" inputmode="numeric"></div>
<div><label for="s-direct">직접비</label><input id="s-direct" inputmode="numeric"></div>
<div><label for="s-platform">플랫폼</label><input id="s-platform" inputmode="numeric"></div></div>
<div class="row"><button id="load-split" class="secondary">현재 값</button><button id="save-split">저장</button></div><div class="out" id="split-out" aria-live="polite"></div></section>

<section><h2>시험 캠페인</h2>
<div class="grid">
<div><label for="c-advertiser">광고주(시험)</label><input id="c-advertiser" value="House test"></div>
<div><label for="c-product">상품</label><select id="c-product"><option value="S1">S1 작업 후원</option><option value="P2">P2 노출+확인</option><option value="B1">B1 서명 오퍼(에이전트)</option></select></div>
<div><label for="c-bid">입찰가(원)</label><input id="c-bid" inputmode="numeric" value="1500"></div>
<div><label for="c-categories">범주(쉼표)</label><input id="c-categories" value="deep_research"></div>
<div><label for="c-title">제목(영어)</label><input id="c-title"></div>
<div><label for="c-body">본문(영어)</label><input id="c-body"></div>
<div><label for="c-question">확인 문항(영어)</label><input id="c-question"></div>
<div><label for="c-answer">정답</label><input id="c-answer"></div>
<div><label for="c-url">공개 사본 URL(https)</label><input id="c-url" value="https://agentconcierge.biz/ad-coin/test-offer"></div></div>
<div class="row"><button id="create">만들기</button><button id="load-campaigns" class="secondary">목록</button></div>
<div class="out" id="campaign-out" aria-live="polite"></div><div class="scroll"><table id="campaigns" hidden><thead><tr>
<th>캠페인</th><th>상품</th><th>입찰가</th><th>에스크로</th><th>상태</th><th>작업</th></tr></thead><tbody></tbody></table></div></section>

<section><h2>시험 상품</h2>
<p class="muted">실제 카탈로그 에이전트로 만든 숨김 워크플로 상품입니다. 공개 워크플로 목록에는 나가지 않고, 실행은 시뮬레이션입니다. 돈을 옮기거나 상태를 바꾸는 것처럼 보이는 에이전트, 코인을 받을 수 없는 유료 에이전트는 거부합니다.</p>
<div class="grid"><div><label for="t-name">이름(영어)</label><input id="t-name" placeholder="Market brief"></div>
<div><label for="t-desc">설명(영어)</label><input id="t-desc"></div>
<div><label for="t-steps">단계(ID x 실행당 호출 수, 쉼표)</label><input id="t-steps" placeholder="74x5, 484x2, 32926x1"></div></div>
<div class="row"><button id="t-create">만들기</button><button id="t-list" class="secondary">목록</button></div>
<div class="out" id="t-out" aria-live="polite"></div></section>

<section><h2>실행·정산(시뮬레이션)</h2>
<div class="row"><input id="x-id" placeholder="실행 ID (x_...)"><label><input id="x-ok" type="checkbox" checked> 성공</label><button id="complete" class="secondary">실행 완료 처리</button></div>
<div class="row"><input id="r-ids" placeholder="공개 워크플로 실행 ID(쉼표, 견적의 실행 횟수만큼)"><button id="settle-runs" class="secondary">실행 기록으로 정산</button></div>
<p class="muted">공개 워크플로 실행권·코인 결제는 실제 실행 기록으로 정산합니다. 위 실행 ID 칸에 AI AD Coin 실행 ID(x_...)를 넣으세요. 단계별로 성공한 호출만 지급하고 나머지는 낸 쪽에 돌려줍니다. 고객 비공개 흐름은 고객 본인 세션에서 정산합니다.</p>
<div class="row"><input id="p-id" placeholder="제공자 ID (예: r123)"><button id="settle" class="secondary">가상 정산</button><button id="sweep" class="secondary">휴면 에이전트 지갑 회수</button></div>
<div class="out" id="ops-out" aria-live="polite"></div></section>
</main><script src="/ad-coin/admin.js"></script></body></html>
"""

SCRIPT = r"""(function(){
var API='/api/ad-coin/v1',KEY='adCoinAdmin',token='';try{token=sessionStorage.getItem(KEY)||''}catch(e){}
var $=function(id){return document.getElementById(id)};function say(id,t){$(id).textContent=t}
function call(path,body,method){var init={method:method||(body?'POST':'GET'),headers:{'Authorization':'Bearer '+token}};
  if(body){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
  return fetch(API+path,init).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.message||d.error||'요청 실패');return d})})}
function key(){return Date.now().toString(36)+Math.random().toString(36).slice(2,8)}
function won(n){return Number(n||0).toLocaleString('ko-KR')+'원'}
$('save').onclick=function(){token=$('token').value.trim();try{sessionStorage.setItem(KEY,token)}catch(e){}say('token-status','설정했습니다.')};
$('load-status').onclick=function(){say('status','불러오는 중...');
  Promise.all([call('/status'),call('/admin/invariant')]).then(function(v){var s=v[0],i=v[1];
    say('status',['결제: '+(s.payments==='closed'?'닫힘':s.payments)+' · 시험 모드: '+(s.test_mode?'예':'아니오'),
      '회로: '+(s.circuit.open?'열림 ('+s.circuit.reason+')':'닫힘'),
      '재원: '+(i.ok?'정상':'문제 '+i.problems.join(', '))+' · 보관 의무 '+won(i.obligations_won)+' / 신탁 '+won(i.trust_statement_won),
      '사용자 코인 '+won(i.coin_liability_won)+' · 불균형 분개 '+i.unbalanced_journals+'건'].join('\n'))})
  .catch(function(e){say('status',e.message)})};
$('open-circuit').onclick=function(){call('/admin/circuit',{open:true,reason:$('circuit-reason').value||'manual'}).then(function(c){say('circuit-out','회로를 열었습니다: '+c.reason)}).catch(function(e){say('circuit-out',e.message)})};
$('close-circuit').onclick=function(){call('/admin/circuit',{open:false}).then(function(){say('circuit-out','회로를 닫았습니다.')}).catch(function(e){say('circuit-out',e.message)})};
var parts=['user','operator','direct','platform'];
$('load-split').onclick=function(){call('/admin/settings').then(function(d){parts.forEach(function(p){$('s-'+p).value=d.split_bps[p]});say('split-out','')}).catch(function(e){say('split-out',e.message)})};
$('save-split').onclick=function(){var v={};parts.forEach(function(p){v[p]=parseInt($('s-'+p).value,10)});
  call('/admin/settings',{split_bps:v},'PUT').then(function(){say('split-out','저장했습니다.')}).catch(function(e){say('split-out',e.message)})};
$('create').onclick=function(){$('create').disabled=true;call('/admin/campaigns',{advertiser:$('c-advertiser').value,product:$('c-product').value,
    bid_won:parseInt($('c-bid').value,10),categories:$('c-categories').value.split(',').map(function(x){return x.trim()}).filter(Boolean),
    title:$('c-title').value,body:$('c-body').value,question:$('c-question').value,answer:$('c-answer').value,public_url:$('c-url').value})
  .then(function(c){say('campaign-out','만들었습니다: '+c.id+'. 충전해야 제안에 나갑니다.');list()}).catch(function(e){say('campaign-out',e.message)})
  .finally(function(){$('create').disabled=false})};
function action(label,fn,secondary){var b=document.createElement('button');b.textContent=label;if(secondary)b.className='secondary';b.onclick=fn;return b}
function list(){var table=$('campaigns'),body=table.querySelector('tbody');say('campaign-out','불러오는 중...');
  call('/admin/campaigns').then(function(d){body.textContent='';table.hidden=!d.campaigns.length;say('campaign-out',d.campaigns.length?'':'캠페인이 없습니다.');
    d.campaigns.forEach(function(c){var tr=document.createElement('tr');
      [c.advertiser+' · '+c.title+'\n'+c.id,c.product,won(c.bid_won),won(c.escrow_won),c.status==='active'?'진행':'중지'].forEach(function(t){var td=document.createElement('td');td.textContent=t;tr.appendChild(td)});
      var td=document.createElement('td'),amount=document.createElement('input');amount.placeholder='충전액(원)';amount.inputMode='numeric';amount.style.width='110px';
      var note=document.createElement('div');note.className='out';
      var done=function(m){return function(){note.textContent=m;list()}},fail=function(e){note.textContent=e.message};
      td.appendChild(amount);
      td.appendChild(action('충전',function(){call('/admin/campaigns/fund',{campaign_id:c.id,amount_won:parseInt(amount.value,10),idempotency_key:key()}).then(done('충전했습니다.')).catch(fail)}));
      td.appendChild(action(c.status==='active'?'중지':'재개',function(){call('/admin/campaigns/status',{campaign_id:c.id,status:c.status==='active'?'paused':'active'}).then(done('바꿨습니다.')).catch(fail)},true));
      td.appendChild(action('환불',function(){call('/admin/campaigns/refund',{campaign_id:c.id,idempotency_key:key()}).then(done('에스크로를 돌려주고 중지했습니다.')).catch(fail)},true));
      td.appendChild(action('보고서',function(){call('/admin/campaigns/report?campaign_id='+encodeURIComponent(c.id)).then(function(r){
        note.textContent='승인 노출 '+r.approved_views+' (사람 '+r.people+') · 후원 실행 시작 '+r.sponsored_runs_started+' / 성공 '+r.sponsored_runs_succeeded+' · 에이전트 수신 '+r.agent_receipts}).catch(fail)},true));
      td.appendChild(note);tr.appendChild(td);body.appendChild(tr)})}).catch(function(e){say('campaign-out',e.message)})}
$('load-campaigns').onclick=list;
function steps(){return $('t-steps').value.split(',').map(function(x){return x.trim()}).filter(Boolean).map(function(x){var p=x.toLowerCase().split('x');return {resource_id:parseInt(p[0],10),calls_per_run:parseInt(p[1]||'1',10)}})}
function products(){var box=$('t-out');box.textContent='불러오는 중...';call('/admin/test-products').then(function(d){box.textContent=d.test_products.length?'':'시험 상품이 없습니다.';
  d.test_products.forEach(function(p){var row=document.createElement('div');row.className='row';var t=document.createElement('span');
    t.textContent=p.id+' · '+p.name+' · '+(p.status==='active'?'사용 중':'보관')+' · '+p.steps.map(function(s){return s.resource_id+'x'+s.calls_per_run}).join(', ');row.appendChild(t);
    if(p.status==='active')row.appendChild(action('보관',function(){call('/admin/test-products/archive',{id:p.id}).then(products).catch(function(e){t.textContent=e.message})},true));
    box.appendChild(row)})}).catch(function(e){box.textContent=e.message})}
$('t-list').onclick=products;
function invites(){var box=$('i-out');box.textContent='불러오는 중...';call('/admin/invites').then(function(d){box.textContent=d.invites.length?'':'초대가 없습니다.';
  d.invites.forEach(function(v){var row=document.createElement('div');row.className='row';var t=document.createElement('span');
    t.textContent=v.customer_id+' · '+(v.status==='invited'?'초대됨':'거둠')+(v.note?' · '+v.note:'');row.appendChild(t);
    if(v.status==='invited')row.appendChild(action('거두기',function(){call('/admin/invites/revoke',{customer_id:v.customer_id}).then(invites).catch(function(e){t.textContent=e.message})},true));
    box.appendChild(row)})}).catch(function(e){box.textContent=e.message})}
$('i-list').onclick=invites;
$('a-list').onclick=function(){say('a-out','불러오는 중...');call('/admin/audits').then(function(d){
  say('a-out',d.audits.length?d.audits.map(function(a){return new Date(a.created_at*1000).toLocaleString('ko-KR')+' · '+(a.inconclusive?'판정 불가':a.passed?'통과':'실패')+
    ' · 같음 '+a.counts.same+', 바뀜 '+a.counts.changed+', 흔들림 '+a.counts.unstable+', 오류 '+a.counts.error+(a.changed_queries.length?' · 바뀐 질문: '+a.changed_queries.join(' / '):'')}).join('\n'):'감사 기록이 없습니다.')})
  .catch(function(e){say('a-out',e.message)})};
$('i-add').onclick=function(){call('/admin/invites',{customer_id:$('i-id').value.trim(),note:$('i-note').value}).then(invites).catch(function(e){say('i-out',e.message)})};
$('t-create').onclick=function(){$('t-create').disabled=true;call('/admin/test-products',{name:$('t-name').value,description:$('t-desc').value,steps:steps()})
  .then(function(p){say('t-out','만들었습니다: '+p.id);setTimeout(products,300)}).catch(function(e){say('t-out',e.message)}).finally(function(){$('t-create').disabled=false})};
$('complete').onclick=function(){var ok=$('x-ok').checked,digest='sha256:'+'0'.repeat(64);
  call('/admin/executions/complete',{execution_id:$('x-id').value.trim(),ok:ok,result_digest:ok?digest:null}).then(function(r){say('ops-out',r.status==='succeeded'?'성공 처리했습니다. 제공자 지급 예정에 넣었습니다.':'실패 처리했습니다. 코인·실행권을 돌려줬습니다.')}).catch(function(e){say('ops-out',e.message)})};
$('settle-runs').onclick=function(){var ids=$('r-ids').value.split(',').map(function(x){return x.trim()}).filter(Boolean);
  call('/admin/executions/settle-from-runs',{execution_id:$('x-id').value.trim(),run_ids:ids}).then(function(r){
    say('ops-out',r.status==='waiting'?'아직 실행 중인 기록이 있습니다: '+r.run:'정산: '+r.status+' · 지급 '+won(r.paid_won)+' · 환불 '+won(r.refunded_won)+' · 단계별 성공 호출 '+r.line_calls_succeeded.join(', '))})
  .catch(function(e){say('ops-out',e.message)})};
$('settle').onclick=function(){call('/admin/settle',{provider:$('p-id').value.trim(),idempotency_key:key()}).then(function(r){say('ops-out',r.status==='settled'?'가상 정산 '+won(r.won):'지급할 금액이 없습니다.')}).catch(function(e){say('ops-out',e.message)})};
$('sweep').onclick=function(){call('/admin/sweep-dormant',{}).then(function(r){say('ops-out','회수한 지갑 '+r.swept_wallets+'개, '+r.coins+'코인')}).catch(function(e){say('ops-out',e.message)})};
})();
"""
