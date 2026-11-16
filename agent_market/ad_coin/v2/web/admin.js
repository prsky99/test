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
  function reasonField(card, label = '거절 사유') {
    let input = card.querySelector('input');
    if (!input) { input = document.createElement('input'); input.maxLength = 200; input.placeholder = label + '(3자 이상)';
      input.setAttribute('aria-label', label); card.insertBefore(input, card.querySelector('.actions')); }
    return input;
  }
  // 11-15: 검사를 통과한 신청은 바로 승인되고, 여기에는 검사에 걸린 신청만 옵니다.
  const FLAGS = {restricted_class: '판매하지 않거나 사람 확인이 필요한 분류의 단어', steering: '에이전트를 조종하는 문구',
    imperative: '명령형으로 시작', hidden_characters: '숨은 문자', https_url_required: 'https 주소 아님',
    not_public: '공개 주소 아님', blocklisted: '차단 목록에 있음', blocklist_unavailable: '차단 목록 없음(출처 미정)',
    young_domain: '등록 30일 미만 도메인', domain_age_unknown: '도메인 등록일 모름', advertiser_name: '광고주 이름 검사 불통과'};
  // 11-15: 검사를 통과한 신청·캠페인·제안은 자동으로 승인되고, 여기에는 걸린 것만 이유와 함께 옵니다.
  function flagText(flags) { return (flags || []).map(f => { const [field, why] = f.includes(':') ? f.split(':') : ['', f];
    return (field ? field + ' ' : '') + (FLAGS[why] || why); }).join(', '); }
  async function loadApplications(done = '') {
    text('applications-status', '불러오는 중입니다.');
    try {
      const {items} = await get('/applications');
      $('application-list').replaceChildren(...items.map(item => row(
        [item.display_name, item.website_url || item.listing_url || '주소 없음', '걸린 이유: ' + (flagText(item.flags) || '없음(11-15 이전 신청)'),
         '신청 ' + new Date(item.applied_ms).toLocaleString('ko-KR')],
        [['승인', true, async (b) => { b.disabled = true; try {
            const r = await post('/applications/' + item.application_id + '/decision', {approve: true});
            await loadApplications('승인했습니다. 환영 코인은 첫 USDC 결제가 확인되면 지급됩니다.'); } catch (e) { b.disabled = false; text('applications-status', reason(e.status)); } }],
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
        [item.name, item.text, '분류 ' + item.task_categories.join(', ') + ' · 지역 ' + item.regions.join(', '),
         '자동 심사에서 걸린 이유: ' + (flagText(item.auto_flags) || '아직 자동 심사 전')],
        [['통과', true, async (b) => { b.disabled = true; try {
            await post('/reviews/' + item.review_id + '/decision', {verdict: 'eligible', reason_code: 'operator_checked'});
            await loadReviews('통과시켰습니다.'); } catch (e) { b.disabled = false; text('reviews-status', reason(e.status)); } }],
         ['반려', false, async (b) => { b.disabled = true; try {
            await post('/reviews/' + item.review_id + '/decision', {verdict: 'rejected', reason_code: 'policy_mismatch'});
            await loadReviews('반려했습니다.'); } catch (e) { b.disabled = false; text('reviews-status', reason(e.status)); } }]])));
      text('reviews-status', done || (items.length ? '' : '심사 대기 캠페인이 없습니다.'));
    } catch (e) { text('reviews-status', reason(e.status)); }
  }
  const NOTES = {amount_mismatch: '금액이 견적과 다름', ambiguous_payer: '송금자가 여럿', sanctions_match: '제재 목록에 있음',
    sanctions_unavailable: '제재 목록 확인 불가', krw_rate_unavailable: '원화 시세 없음', late_payment: '견적 만료 뒤 송금',
    reorg: '체인 재조직으로 결제 재확인 필요', placements_released: '계획의 날짜 자리가 풀림(환불 필요로 처리)'};
  // F12: every manual decision needs a reason (3-200 characters); it is kept with the payment records.
  function paidReason(card) {
    let input = card.querySelector('input[name="paid-reason"]');
    if (!input) { input = document.createElement('input'); input.name = 'paid-reason'; input.maxLength = 200;
      input.placeholder = '처리 사유(3자 이상, 결제 기록에 남음)'; input.setAttribute('aria-label', '처리 사유');
      card.insertBefore(input, card.querySelector('.actions')); }
    return input;
  }
  async function loadPaid(done = '') {
    text('paid-status', '불러오는 중입니다.');
    try {
      // 11-16: plans (one payment for several placements) wait here too, with the same decisions
      const [{items}, plans] = await Promise.all([get('/paid-bookings'),
        get('/paid-plans').then(r => r.items).catch(() => [])]);
      const all = [...items, ...plans.map(p => ({...p, quoted_usdc: p.amount_usdc, plan: true}))];
      $('paid-list').replaceChildren(...all.map(item => {
        const SCREEN = {clear: '해당 없음', match: '제재 목록에 있음', unavailable: '확인 불가'};
        const lines = [item.amount_usdc + ' USDC · ' + (item.state === 'review' ? '검토' : '환불 필요') +
          (item.note ? ' · ' + (NOTES[item.note] || item.note) : ''),
          '받은 금액 ' + (item.received_usdc || '확인 필요') + ' / 견적 ' + (item.quoted_usdc || item.amount_usdc) + ' USDC' +
          (item.refund_cap_usdc ? ' · 환불 상한 ' + item.refund_cap_usdc : ''),
          '송금자 ' + (item.payer || '—') + ' · 제재 대조 ' + (SCREEN[item.sanctions] || '—'), '거래 ' + (item.tx_hash || '—')];
        if (item.plan) lines.unshift('맞춤 계획 · 자리 ' + item.placements + '개 (' + item.items.map(i => i.day + ' ' + i.task_category + '/' + i.region).join(', ') + ')');
        const decide = (body, okText) => async (b, card) => {
          const why = paidReason(card);
          if (why.value.trim().length < 3) { why.focus(); text('paid-status', '처리 사유를 3자 이상 적으세요.'); return; }
          const ack = card.querySelector('input[name="sanctions-ack"]');
          b.disabled = true; try {
          const sent = {...body, reason: why.value.trim(), sanctions_ack: !!(ack && ack.checked)};
          if (item.plan) await post('/paid-plans/' + item.id + '/decision', sent);
          else await post('/paid-bookings/' + item.id + '/decision', sent);
          await loadPaid(okText); }
          catch (e) { b.disabled = false; text('paid-status', reason(e.status)); } };
        const actions = item.state === 'review'
          ? [['확정', true, decide({action: 'clear'}, '확정했습니다.')], ['환불 필요', false, decide({action: 'refund'}, '환불 필요로 옮겼습니다.')]]
          : [['환불함', true, async (b, card) => { let input = card.querySelector('input[name="refund-tx"]');
              if (!input) { input = document.createElement('input'); input.name = 'refund-tx'; input.placeholder = '환불 거래 해시 0x…';
                input.setAttribute('aria-label', '환불 거래 해시'); card.insertBefore(input, card.querySelector('.actions')); input.focus(); return; }
              await decide({action: 'refunded', refund_tx_hash: input.value.trim()}, '환불을 기록했습니다.')(b, card); }]];
        const card = row(lines, actions);
        paidReason(card);
        if (item.state === 'review' && item.sanctions && item.sanctions !== 'clear') {
          // R35: clearing a sender that is not 'clear' needs this tick and a reason of at least 20 characters.
          const label = document.createElement('label'); const box = document.createElement('input');
          box.type = 'checkbox'; box.name = 'sanctions-ack';
          label.append(box, ' 제재 대조 결과를 직접 확인했고 사유를 20자 이상 적었습니다');
          card.insertBefore(label, card.querySelector('.actions'));
        }
        return card;
      }));
      text('paid-status', done || (items.length ? '' : '검토·환불할 결제가 없습니다.'));
    } catch (e) { text('paid-status', e.status === 404 ? 'USDC 결제가 꺼져 있습니다.' : reason(e.status)); }
  }
  // R33: the exact line agents will read is shown before an operator approves an offer.
  async function loadOffers(done = '') {
    text('offers-status', '불러오는 중입니다.');
    try {
      const {items} = await get('/sponsored-offers');
      $('offer-list').replaceChildren(...items.map(item => {
        const lines = ['에이전트가 읽을 줄: ' + item.preview, '광고주 이름 ' + item.advertiser +
          (item.advertiser_name_ok ? '' : ' · 이름이 검사를 통과하지 못해 승인할 수 없음'),
          '주소 ' + item.offer.endpoint + ' · 도구 ' + (item.offer.tool || '—'),
          '자동 심사에서 걸린 이유: ' + (flagText(item.auto_flags) || '아직 자동 심사 전')];
        const decide = (approve, okText) => async (b, card) => {
          const why = reasonField(card);
          if (!approve && why.value.trim().length < 3) { why.focus(); text('offers-status', '거절 사유를 3자 이상 적으세요.'); return; }
          b.disabled = true;
          try { await post('/sponsored-offers/' + item.campaign_id + '/decision', {approve, reason: why.value.trim()});
            await loadOffers(okText); }
          catch (e) { b.disabled = false; text('offers-status', reason(e.status)); } };
        return row(lines, [['승인', true, decide(true, '승인했습니다.')], ['거절', false, decide(false, '거절했습니다.')]]);
      }));
      text('offers-status', done || (items.length ? '' : '심사할 제안이 없습니다.'));
    } catch (e) { text('offers-status', reason(e.status)); }
  }
  $('load-offers').addEventListener('click', () => loadOffers());
  $('load-paid').addEventListener('click', () => loadPaid());
  $('export-paid').addEventListener('click', () => {
    const month = $('paid-month').value.trim();
    if (!/^20[0-9]{2}-(0[1-9]|1[0-2])$/.test(month)) { text('paid-status', '월을 2026-11 형식으로 적으세요.'); return; }
    window.location.href = API + '/paid-bookings/export?month=' + month;
  });
  const KO = {advertiser_applied: '신청', advertiser_approved: '승인', advertiser_rejected: '거절', coins_granted: '코인 지급',
    sponsored_booked: '코인 예약', sponsored_refunded: '코인 환불'};
  async function loadOne() {
    const id = $('one-id').value.trim();
    if (!/^[0-9a-f-]{36}$/i.test(id)) { text('one-status', '광고주 ID(36자)를 넣으세요.'); return; }
    text('one-status', '불러오는 중입니다.');
    try {
      const h = await get('/advertisers/' + id + '/history');
      const day = ms => new Date(ms).toISOString().slice(0, 10);
      const block = (title, lines) => row([title, ...(lines.length ? lines : ['없음'])], []);
      $('one-list').replaceChildren(
        row(['상태 ' + (h.status === 'active' ? '활성' : '정지·대기') + ' · 코인 잔액 ' + h.coin_balance],
          h.status === 'active' ? [['광고 내리기', false, async (b, card) => { const input = reasonField(card, '내리는 사유');
            if (input.value.trim().length < 3) { input.focus(); text('one-status', '내리는 사유를 3자 이상 적으세요.'); return; }
            b.disabled = true; try { const r = await post('/advertisers/' + id + '/takedown', {reason: input.value.trim()});
              text('one-status', '내렸습니다. 광고주 정지, 캠페인 ' + r.paused_campaigns.length + '개 정지, 제안 ' + r.offers_withdrawn + '개 회수.');
              await loadOne(); } catch (e) { b.disabled = false; text('one-status', reason(e.status)); } }]] : []),
        block('기록(최근 90일)', h.events.map(e => new Date(e.at_ms).toLocaleString('ko-KR') + ' · ' + (KO[e.event] || e.event))),
        block('캠페인', h.campaigns.map(c => c.name + ' · ' + c.state + ' · ' + c.approval)),
        block('코인 예약', h.coin_bookings.map(b => day(b.day_ms) + ' · ' + b.category + '/' + b.region + ' · ' + b.coins + '코인 · ' + b.state + ' · ' + b.id)),
        block('USDC 결제', h.paid_bookings.map(p => day(p.day_ms) + ' · ' + (Number(p.amount_units) / 1e6).toFixed(6) + ' USDC · ' + p.state +
          (p.tx_hash ? ' · 거래 ' + p.tx_hash : '') + (p.refund_tx_hash ? ' · 환불 ' + p.refund_tx_hash : '') + ' · ' + p.id)));
      text('one-status', '');
    } catch (e) { text('one-status', e.status === 404 ? '그 ID의 광고주가 없습니다.' : reason(e.status)); }
  }
  $('load-one').addEventListener('click', loadOne);
  $('load-applications').addEventListener('click', loadApplications);
  $('load-reviews').addEventListener('click', loadReviews);
})();
