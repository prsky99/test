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
    const t = c.x402_test;
    $('x402-badge').className = 'badge ' + (t.eligible ? 'success' : 'warning');
    text('x402-badge', t.eligible ? '시험 가능' : '조건 미달');
    text('remaining', coins(t.remaining_atoms, unit));
    text('limit', coins(t.spend_limit_atoms, unit));
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
})();
