(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const API = '/api/ad-coin/v2/admin';
  const text = (id, value) => { $(id).textContent = value; };

  function coins(atoms, perCoin) {
    // Exact integer arithmetic: atoms can exceed Number's safe range.
    const value = BigInt(atoms), unit = BigInt(perCoin);
    const whole = value / unit, rest = (value < 0n ? -value : value) % unit;
    const head = whole.toLocaleString('ko-KR');
    if (rest === 0n) return head;
    return head + '.' + rest.toString().padStart(String(perCoin).length - 1, '0').replace(/0+$/, '');
  }
  function reason(status) {
    if (status === 401) return '로그인이 필요합니다. 운영자 계정으로 로그인한 뒤 다시 누르세요.';
    if (status === 403) return '운영자 권한(platform.operate)이 있는 계정만 볼 수 있습니다.';
    if (status === 404) return 'v2가 꺼져 있습니다.';
    return '불러오지 못했습니다. 잠시 뒤 다시 누르세요.';
  }
  async function get(path) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(API + path, {credentials: 'same-origin', cache: 'no-store',
        redirect: 'error', signal: controller.signal});
      if (!response.ok) throw {status: response.status};
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function showHoldings(data) {
    const c = data.coins, unit = c.atoms_per_coin;
    text('held', coins(c.platform_holdings_atoms, unit));
    text('growth', coins(c.growth_budget_atoms, unit));
    text('revenue', coins(c.coin_revenue_atoms, unit));
    text('issued', coins(c.issued_atoms, unit));
    text('holdings-status', '');
  }
  function showReconcile(data) {
    const ok = data.status === 'balanced';
    $('recon-badge').className = 'badge ' + (ok ? 'success' : 'warning');
    text('recon-badge', ok ? '일치' : '불일치');
    text('accounts', Number(data.audit.accounts_checked).toLocaleString('ko-KR'));
    text('checked-at', new Date(data.reconciliation.timestamp_ms).toLocaleString('ko-KR'));
    const list = $('issues');
    list.replaceChildren(...data.reconciliation.issues.map(issue => {
      const item = document.createElement('li');
      item.textContent = typeof issue === 'string' ? issue : JSON.stringify(issue);
      return item;
    }));
    text('recon-status', ok ? '' : '대사가 맞지 않습니다. 아래 항목을 확인하세요.');
  }
  async function load() {
    const button = $('load');
    button.disabled = true;
    text('state', '불러오는 중입니다.');
    text('holdings-status', '불러오는 중입니다.');
    text('recon-status', '불러오는 중입니다.');
    // The two sources are independent, so they load in parallel and fail separately.
    const [overview, recon] = await Promise.allSettled([get('/overview'), get('/reconcile')]);
    if (overview.status === 'fulfilled') showHoldings(overview.value);
    else text('holdings-status', reason(overview.reason && overview.reason.status));
    if (recon.status === 'fulfilled') showReconcile(recon.value);
    else text('recon-status', reason(recon.reason && recon.reason.status));
    text('state', '마지막으로 불러온 시각: ' + new Date().toLocaleString('ko-KR'));
    button.disabled = false;
  }
  $('load').addEventListener('click', load);

  let csrf = null;
  async function siteCsrf() {
    if (csrf) return csrf;
    const response = await fetch('/api/customer-auth/session', {credentials: 'same-origin', cache: 'no-store'});
    const value = response.ok ? await response.json() : null;
    csrf = typeof value?.session?.csrf_token === 'string' ? value.session.csrf_token : null;
    if (!csrf) throw {status: 401};
    return csrf;
  }
  async function post(path, body) {
    const response = await fetch(API + path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      redirect: 'error', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': await siteCsrf()},
      body: JSON.stringify(body)});
    if (!response.ok) throw {status: response.status};
    return response.json();
  }
  function row(lines, actions) {
    const card = document.createElement('article'); card.className = 'card';
    for (const line of lines) { const p = document.createElement('p'); p.textContent = line; card.append(p); }
    const bar = document.createElement('div'); bar.className = 'actions'; card.append(bar);
    for (const [label, primary, action] of actions) {
      const b = document.createElement('button'); b.type = 'button'; b.className = primary ? 'btn primary' : 'btn';
      b.textContent = label; b.addEventListener('click', () => action(b, card)); bar.append(b);
    }
    return card;
  }
  function reasonField(card) {
    let input = card.querySelector('input');
    if (!input) { input = document.createElement('input'); input.maxLength = 200; input.placeholder = '거절 사유(3자 이상)';
      input.setAttribute('aria-label', '거절 사유'); card.insertBefore(input, card.querySelector('.actions')); }
    return input;
  }
  async function loadApplications(done = '') {
    text('applications-status', '불러오는 중입니다.');
    try {
      const {items} = await get('/applications');
      $('application-list').replaceChildren(...items.map(item => row(
        [item.display_name, item.listing_url, '신청 ' + new Date(item.applied_ms).toLocaleString('ko-KR')],
        [['승인', true, async (b) => { b.disabled = true; try {
            const r = await post('/applications/' + item.application_id + '/decision', {approve: true});
            await loadApplications(r.welcome.granted_atoms === '0' ? '승인했습니다. 성장 예산이 없어 환영 지급은 하지 않았습니다.' : '승인하고 환영 지급을 했습니다.'); } catch (e) { b.disabled = false; text('applications-status', reason(e.status)); } }],
         ['거절', false, async (b, card) => { const input = reasonField(card);
            if (input.value.trim().length < 3) { input.focus(); text('applications-status', '거절 사유를 3자 이상 적으세요.'); return; }
            b.disabled = true; try { await post('/applications/' + item.application_id + '/decision', {approve: false, reason: input.value.trim()});
            await loadApplications('거절했습니다.'); } catch (e) { b.disabled = false; text('applications-status', reason(e.status)); } }]])));
      text('applications-status', done || (items.length ? '' : '대기 중인 신청이 없습니다.'));
    } catch (e) { text('applications-status', reason(e.status)); }
  }
  async function loadReviews(done = '') {
    text('reviews-status', '불러오는 중입니다.');
    try {
      const {items} = await get('/reviews');
      $('review-list').replaceChildren(...items.map(item => row(
        [item.name, item.text, '분류 ' + item.task_categories.join(', ') + ' · 지역 ' + item.regions.join(', ')],
        [['통과', true, async (b) => { b.disabled = true; try {
            await post('/reviews/' + item.review_id + '/decision', {verdict: 'eligible', reason_code: 'operator_checked'});
            await loadReviews('통과시켰습니다.'); } catch (e) { b.disabled = false; text('reviews-status', reason(e.status)); } }],
         ['반려', false, async (b) => { b.disabled = true; try {
            await post('/reviews/' + item.review_id + '/decision', {verdict: 'rejected', reason_code: 'policy_mismatch'});
            await loadReviews('반려했습니다.'); } catch (e) { b.disabled = false; text('reviews-status', reason(e.status)); } }]])));
      text('reviews-status', done || (items.length ? '' : '심사 대기 캠페인이 없습니다.'));
    } catch (e) { text('reviews-status', reason(e.status)); }
  }
  $('load-applications').addEventListener('click', loadApplications);
  $('load-reviews').addEventListener('click', loadReviews);
})();
