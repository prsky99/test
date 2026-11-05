"""AI AD Coin operator console (Korean: the admin side stays Korean; admin token).

It uses the Agent Concierge "Pearl Connection" design system as it is (shared files
under /new/en/assets, the workspace shell and shared components; no page-local
styles). The admin console's own stylesheet lives on the private admin host, so this
page uses the public files, which carry the same pearl tokens. Fixed text renders at
once; each panel loads when its button is pressed and the status panel fetches its
two sources in parallel. No dialogs or full-screen loading."""
from .advertiser_page import ICON

VIEWS = (('status', '상태·재원', 'home'), ('review', '광고 검토·광고주', 'megaphone'), ('audit', '후원 감사', 'chart'),
         ('invites', '초대', 'team'), ('split', '배분율', 'receipt'), ('campaigns', '시험 캠페인', 'plus'),
         ('products', '시험 상품', 'plus'), ('ops', '실행·정산', 'receipt'))

SIDEBAR = ''.join(
    '<a class="side-item%s" href="#%s" data-view-link="%s"%s>%s%s</a>\n' % (
        ' active' if key == 'status' else '', key, key, ' aria-current="page"' if key == 'status' else '', ICON[icon], label)
    for key, label, icon in VIEWS)

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, noarchive">
<meta name="referrer" content="no-referrer">
<title>AI AD Coin 운영 | Agent Concierge</title>
<link rel="icon" href="/new/en/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/new/en/assets/styles.css">
<link rel="stylesheet" href="/new/en/assets/necklace.css">
<link rel="stylesheet" href="/new/en/assets/pearl-live.css">
<script src="/new/en/assets/app.js" defer></script>
<script src="/ad-coin/admin.js" defer></script>
</head>
<body data-page="ad-coin-admin">
<a class="sr-only skip-link" href="#main">본문으로 건너뛰기</a>
<header class="ws-top">
<div class="container header-inner">
<a class="brand" href="/new/en/index.html"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>
<span class="small mobile-hidden">AI AD Coin 운영</span>
<div class="header-actions">
{sun}<button class="theme-toggle" type="button" data-action="theme" aria-label="어두운 테마 전환" aria-pressed="false"></button>{moon}
</div>
</div>
</header>
<div class="container ws-layout">
<aside class="ws-sidebar" aria-label="AI AD Coin 운영 메뉴">
<p class="caption">AI AD Coin 운영</p>
<div class="row"><span class="badge warning">시험 모드</span></div>
<hr class="divider">
{sidebar}</aside>
<main class="ws-main" id="main">
<div class="page-heading">
<p class="eyebrow">AI AD Coin · 운영</p>
<h1>후원과 코인 운영</h1>
<p class="lead">시험 모드입니다. 예산·코인·정산은 모두 가상 값이고, 결제와 실제 광고주 집행은 닫혀 있습니다. 광고는 자체 시험 캠페인만 씁니다.</p>
</div>

<section class="card" aria-labelledby="token-h">
<h2 id="token-h">관리자 토큰</h2>
<p class="caption">이 탭에만 보관합니다.</p>
<div class="field"><label for="token">토큰</label><input id="token" type="password" autocomplete="off"></div>
<div class="actions"><button type="button" class="btn primary" id="save">사용</button></div>
<p class="caption" id="token-status" role="status" aria-live="polite"></p>
</section>

<section class="view stack" data-view="status" aria-labelledby="status-h">
<section class="card">
<h2 id="status-h">상태와 재원</h2>
<p>보관 중인 사용자·광고주 몫이 예치금(가상 신탁 잔액)을 넘으면 회로가 열려 새 후원 제안이 멈춥니다.</p>
<div class="actions"><button type="button" class="btn primary" id="load-status">불러오기</button></div>
<div id="status" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>회로</h2>
<div class="field"><label for="circuit-reason">회로를 여는 이유</label><input id="circuit-reason"></div>
<div class="actions"><button type="button" class="btn danger" id="open-circuit">회로 열기</button><button type="button" class="btn" id="close-circuit">회로 닫기</button></div>
<div id="circuit-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="review" aria-labelledby="review-h" hidden>
<section class="card">
<h2 id="review-h">광고 검토</h2>
<p>자동 검토에서 사람이 볼 광고(민감한 주장, 웹사이트 밖 공개 사본, 이의 제기)가 여기 쌓입니다.</p>
<div class="actions"><button type="button" class="btn primary" id="v-queue">검토 대기열</button></div>
<div id="v-out" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>광고주 관리</h2>
<p>광고주를 인증하면 하루 2만 원 제한이 풀립니다.</p>
<div class="field"><label for="v-adv">광고주 ID</label><input id="v-adv" placeholder="adv_..."></div>
<div class="field"><label for="v-state">인증 상태</label><select id="v-state"><option value="verified">인증</option><option value="unverified">미인증</option><option value="rejected">거절</option></select></div>
<div class="actions"><button type="button" class="btn" id="v-verify">인증 상태 저장</button></div>
<div class="field"><label for="v-acct">계정 상태</label><select id="v-acct"><option value="active">활성</option><option value="suspended">정지</option></select></div>
<div class="actions"><button type="button" class="btn" id="v-status">계정 상태 저장</button></div>
<hr class="divider">
<h3>무효 노출 환불</h3>
<div class="field"><label for="v-resv">무효로 볼 예약 ID</label><input id="v-resv" placeholder="h_..."></div>
<div class="field"><label for="v-reason">이유</label><input id="v-reason"></div>
<div class="actions"><button type="button" class="btn danger" id="v-invalid">무효 처리·환불</button></div>
<div class="field"><label for="v-reserve">환불 준비금(원)</label><input id="v-reserve" inputmode="numeric"></div>
<div class="actions"><button type="button" class="btn" id="v-fund">준비금 충전(가상)</button></div>
<div id="v-ops" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="audit" aria-labelledby="audit-h" hidden>
<section class="card">
<h2 id="audit-h">후원 감사</h2>
<p>매달 같은 질문을 후원 끔·켬·끔으로 돌려 추천 상위 3개가 바뀌는지 봅니다. 바뀐 질문이 하나라도 있으면 회로가 열려 후원 제안이 멈춥니다.</p>
<div class="actions"><button type="button" class="btn primary" id="a-list">감사 기록</button></div>
<div id="a-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view" data-view="invites" aria-labelledby="invites-h" hidden>
<div class="split">
<section class="card">
<h2 id="invites-h">초대 목록</h2>
<p>초대를 거두면 그 사람의 에이전트 키도 함께 멈춥니다.</p>
<div class="actions"><button type="button" class="btn primary" id="i-list">목록</button></div>
<div id="i-out" role="status" aria-live="polite"></div>
</section>
<aside class="card">
<h2>초대하기</h2>
<p class="caption">고객 로그인 계정 ID로 초대합니다. 사용자는 AI AD Coin 화면의 "Check my account"에서 자기 계정 ID를 볼 수 있습니다.</p>
<div class="field"><label for="i-id">계정 ID</label><input id="i-id"></div>
<div class="field"><label for="i-note">메모(선택)</label><input id="i-note"></div>
<button type="button" class="btn primary block" id="i-add">초대</button>
</aside>
</div>
</section>

<section class="view stack" data-view="split" aria-labelledby="split-h" hidden>
<section class="card">
<h2 id="split-h">배분율(만분율)</h2>
<p>합계 10000. 사용자 몫은 4000 이상, 운영자+직접비는 4000 이하여야 합니다.</p>
<div class="field"><label for="s-user">사용자</label><input id="s-user" inputmode="numeric"></div>
<div class="field"><label for="s-operator">운영자</label><input id="s-operator" inputmode="numeric"></div>
<div class="field"><label for="s-direct">직접비</label><input id="s-direct" inputmode="numeric"></div>
<div class="field"><label for="s-platform">플랫폼</label><input id="s-platform" inputmode="numeric"></div>
<div class="actions"><button type="button" class="btn" id="load-split">현재 값</button><button type="button" class="btn primary" id="save-split">저장</button></div>
<div id="split-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="campaigns" aria-labelledby="campaigns-h" hidden>
<section class="card">
<h2 id="campaigns-h">시험 캠페인</h2>
<div class="actions"><button type="button" class="btn primary" id="load-campaigns">목록</button></div>
<div id="campaign-out" role="status" aria-live="polite"></div>
<div class="table-wrap status-table"><table class="data-table" id="campaigns" hidden><thead><tr>
<th>캠페인</th><th>상품</th><th>입찰가</th><th>에스크로</th><th>상태</th><th><span class="sr-only">열기</span></th></tr></thead><tbody></tbody></table></div>
</section>
<section class="card" id="c-detail" hidden aria-labelledby="c-detail-title">
<p class="eyebrow" id="c-detail-id"></p>
<h2 id="c-detail-title"></h2>
<div class="field"><label for="c-fund">충전액(원, 가상)</label><input id="c-fund" inputmode="numeric" placeholder="50000"></div>
<div class="actions"><button type="button" class="btn primary" id="c-fund-go">충전</button><button type="button" class="btn" id="c-toggle">중지</button><button type="button" class="btn" id="c-report">보고서</button><button type="button" class="btn danger" id="c-refund">환불·중지</button></div>
<div id="c-note" role="status" aria-live="polite"></div>
</section>
<section class="card">
<h2>새 시험 캠페인</h2>
<div class="field"><label for="c-advertiser">광고주(시험)</label><input id="c-advertiser" value="House test"></div>
<div class="field"><label for="c-product">상품</label><select id="c-product"><option value="S1">S1 작업 후원</option><option value="P2">P2 노출+확인</option><option value="B1">B1 서명 오퍼(에이전트)</option></select></div>
<div class="field"><label for="c-bid">입찰가(원)</label><input id="c-bid" inputmode="numeric" value="1500"></div>
<div class="field"><label for="c-categories">범주(쉼표)</label><input id="c-categories" value="deep_research"></div>
<div class="field"><label for="c-title">제목(영어)</label><input id="c-title"></div>
<div class="field"><label for="c-body">본문(영어)</label><input id="c-body"></div>
<div class="field"><label for="c-question">확인 문항(영어)</label><input id="c-question"></div>
<div class="field"><label for="c-answer">정답</label><input id="c-answer"></div>
<div class="field"><label for="c-url">공개 사본 URL(https)</label><input id="c-url" value="https://agentconcierge.biz/ad-coin/test-offer"></div>
<div class="actions"><button type="button" class="btn primary" id="create">만들기</button></div>
</section>
</section>

<section class="view stack" data-view="products" aria-labelledby="products-h" hidden>
<section class="card">
<h2 id="products-h">시험 상품</h2>
<p>실제 카탈로그 에이전트로 만든 숨김 워크플로 상품입니다. 공개 워크플로 목록에는 나가지 않고, 실행은 시뮬레이션입니다. 돈을 옮기거나 상태를 바꾸는 것처럼 보이는 에이전트, 코인을 받을 수 없는 유료 에이전트는 거부합니다.</p>
<div class="field"><label for="t-name">이름(영어)</label><input id="t-name" placeholder="Market brief"></div>
<div class="field"><label for="t-desc">설명(영어)</label><input id="t-desc"></div>
<div class="field"><label for="t-steps">단계(ID x 실행당 호출 수, 쉼표)</label><input id="t-steps" placeholder="74x5, 484x2, 32926x1"></div>
<div class="actions"><button type="button" class="btn primary" id="t-create">만들기</button><button type="button" class="btn" id="t-list">목록</button></div>
<div id="t-out" role="status" aria-live="polite"></div>
</section>
</section>

<section class="view stack" data-view="ops" aria-labelledby="ops-h" hidden>
<section class="card">
<h2 id="ops-h">실행·정산(시뮬레이션)</h2>
<div class="field"><label for="x-id">AI AD Coin 실행 ID</label><input id="x-id" placeholder="x_..."></div>
<label class="check"><input id="x-ok" type="checkbox" checked><span>성공</span></label>
<div class="actions"><button type="button" class="btn" id="complete">실행 완료 처리</button></div>
<div class="field"><label for="r-ids">공개 워크플로 실행 ID(쉼표, 견적의 실행 횟수만큼)</label><input id="r-ids"></div>
<div class="actions"><button type="button" class="btn" id="settle-runs">실행 기록으로 정산</button></div>
<div class="note">{info}<p>공개 워크플로 실행권·코인 결제는 실제 실행 기록으로 정산합니다. 단계별로 성공한 호출만 지급하고 나머지는 낸 쪽에 돌려줍니다. 고객 비공개 흐름은 고객 본인 세션에서 정산합니다.</p></div>
<div class="field"><label for="p-id">제공자 ID</label><input id="p-id" placeholder="예: r123"></div>
<div class="actions"><button type="button" class="btn" id="settle">가상 정산</button><button type="button" class="btn" id="sweep">휴면 에이전트 지갑 회수</button></div>
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
function action(label,fn,plain,danger){var b=document.createElement('button');b.type='button';b.textContent=label;
  b.className='btn small'+(plain?'':' primary')+(danger?' danger':'');b.onclick=fn;return b}
var picked=null;
function list(){var table=$('campaigns'),body=table.querySelector('tbody');say('campaign-out','불러오는 중...');
  call('/admin/campaigns').then(function(d){body.textContent='';table.hidden=!d.campaigns.length;say('campaign-out',d.campaigns.length?'':'캠페인이 없습니다.');
    d.campaigns.forEach(function(c){var tr=document.createElement('tr');
      [c.advertiser+' · '+c.title,c.product,won(c.bid_won),won(c.escrow_won)].forEach(function(t){var td=document.createElement('td');td.textContent=t;tr.appendChild(td)});
      var st=document.createElement('td'),b=document.createElement('span');b.className='badge'+(c.status==='active'?' success':'');b.textContent=c.status==='active'?'진행':'중지';st.appendChild(b);tr.appendChild(st);
      var td=document.createElement('td');td.appendChild(action('열기',function(){open(c)},true));tr.appendChild(td);
      body.appendChild(tr);if(picked&&picked.id===c.id)open(c)})}).catch(function(e){say('campaign-out',e.message)})}
function open(c){picked=c;$('c-detail').hidden=false;$('c-detail-id').textContent=c.product+' · '+c.id;$('c-detail-title').textContent=c.advertiser+' · '+c.title;
  $('c-toggle').textContent=c.status==='active'?'중지':'재개'}
function done(m){return function(){say('c-note',m);list()}}
function fail(e){say('c-note',e.message)}
$('c-fund-go').onclick=function(){call('/admin/campaigns/fund',{campaign_id:picked.id,amount_won:parseInt($('c-fund').value,10),idempotency_key:key()}).then(done('충전했습니다.')).catch(fail)};
$('c-toggle').onclick=function(){call('/admin/campaigns/status',{campaign_id:picked.id,status:picked.status==='active'?'paused':'active'}).then(done('바꿨습니다.')).catch(fail)};
$('c-refund').onclick=function(){call('/admin/campaigns/refund',{campaign_id:picked.id,idempotency_key:key()}).then(done('에스크로를 돌려주고 중지했습니다.')).catch(fail)};
$('c-report').onclick=function(){call('/admin/campaigns/report?campaign_id='+encodeURIComponent(picked.id)).then(function(r){
  say('c-note','승인 노출 '+r.approved_views+' (사람 '+r.people+') · 후원 실행 시작 '+r.sponsored_runs_started+' / 성공 '+r.sponsored_runs_succeeded+' · 에이전트 수신 '+r.agent_receipts)}).catch(fail)};
$('load-campaigns').onclick=list;
function steps(){return $('t-steps').value.split(',').map(function(x){return x.trim()}).filter(Boolean).map(function(x){var p=x.toLowerCase().split('x');return {resource_id:parseInt(p[0],10),calls_per_run:parseInt(p[1]||'1',10)}})}
function products(){var box=$('t-out');say('t-out','불러오는 중...');call('/admin/test-products').then(function(d){say('t-out',d.test_products.length?'':'시험 상품이 없습니다.');
  d.test_products.forEach(function(p){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=p.id+' · '+p.name+' · '+(p.status==='active'?'사용 중':'보관')+' · '+p.steps.map(function(s){return s.resource_id+'x'+s.calls_per_run}).join(', ');row.appendChild(t);
    if(p.status==='active')row.appendChild(action('보관',function(){call('/admin/test-products/archive',{id:p.id}).then(products).catch(function(e){t.textContent=e.message})},true));
    box.appendChild(row)})}).catch(function(e){say('t-out',e.message)})}
$('t-list').onclick=products;
function invites(){var box=$('i-out');say('i-out','불러오는 중...');call('/admin/invites').then(function(d){say('i-out',d.invites.length?'':'초대가 없습니다.');
  d.invites.forEach(function(v){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=v.customer_id+' · '+(v.status==='invited'?'초대됨':'거둠')+(v.note?' · '+v.note:'');row.appendChild(t);
    if(v.status==='invited')row.appendChild(action('거두기',function(){call('/admin/invites/revoke',{customer_id:v.customer_id}).then(invites).catch(function(e){t.textContent=e.message})},true,true));
    box.appendChild(row)})}).catch(function(e){say('i-out',e.message)})}
$('i-list').onclick=invites;
function queue(){say('v-out','불러오는 중...');call('/admin/reviews').then(function(d){var box=$('v-out');say('v-out',d.queue.length?'':'검토할 광고가 없습니다.');
  d.queue.forEach(function(q){var row=document.createElement('div');row.className='history-row';var t=document.createElement('span');
    t.textContent=q.advertiser+' · '+q.title+' — '+q.body+' · '+q.public_url+(q.note?' · '+q.note:'');row.appendChild(t);
    [['eligible','승인'],['eligible_limited','제한 승인'],['disapproved','비승인']].forEach(function(d){row.appendChild(action(d[1],function(){
      call('/admin/reviews/decide',{creative_id:q.creative_id,decision:d[0]}).then(queue).catch(function(e){t.textContent=e.message})},d[0]!=='eligible',d[0]==='disapproved'))});
    box.appendChild(row)})}).catch(function(e){say('v-out',e.message)})}
$('v-queue').onclick=queue;
$('v-verify').onclick=function(){call('/admin/advertisers/verification',{advertiser_id:$('v-adv').value.trim(),verification:$('v-state').value}).then(function(a){say('v-ops',a.name+': '+a.verification)}).catch(function(e){say('v-ops',e.message)})};
$('v-status').onclick=function(){call('/admin/advertisers/status',{advertiser_id:$('v-adv').value.trim(),status:$('v-acct').value}).then(function(a){say('v-ops',a.name+': '+a.status)}).catch(function(e){say('v-ops',e.message)})};
$('v-invalid').onclick=function(){call('/admin/invalid-activity',{reservation_id:$('v-resv').value.trim(),reason:$('v-reason').value||'invalid'}).then(function(r){say('v-ops','환불 '+won(r.refunded_won)+' (사용자 코인은 그대로)')}).catch(function(e){say('v-ops',e.message)})};
$('v-fund').onclick=function(){call('/admin/platform-reserve',{amount_won:parseInt($('v-reserve').value,10),idempotency_key:key()}).then(function(r){say('v-ops','환불 준비금 '+won(r.reserve_won))}).catch(function(e){say('v-ops',e.message)})};
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
function show(view){if(!document.querySelector('[data-view="'+view+'"]'))view='status';
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(v){v.hidden=v.dataset.view!==view});
  Array.prototype.forEach.call(document.querySelectorAll('[data-view-link]'),function(a){var on=a.dataset.viewLink===view;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')})}
window.addEventListener('hashchange',function(){show(location.hash.slice(1))});
show(location.hash.slice(1)||'status');
})();
"""
