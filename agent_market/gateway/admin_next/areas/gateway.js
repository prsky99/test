import {gatewayDetails} from './insights.js';
import {openIOTransforms} from './io-transforms.js';
// ③ 게이트웨이·실행: 성공률, 실패 코드, 에이전트별 호출, 최근 호출 진주 줄 (design 7).
let hours = 24;
const CODES = {UPSTREAM_TOOL_ERROR: '상대 도구 오류', UPSTREAM_TIMEOUT: '시간 초과', UPSTREAM_NETWORK: '연결 실패', UPSTREAM_PROTOCOL: '프로토콜 오류',
  SCHEMA_CHANGED: '스키마 변경', CAPACITY_EXCEEDED: '동시 실행 초과', POLICY_DENIED: '정책 거부', EXECUTION_FAILED: '실행 실패',
  AUTHORITY_OR_OUTCOME_UNCONFIRMED: '결과 미확인', UPSTREAM_FAILURE: '단계 실패'};

export async function render(main, ctx) {
  const {ui, api} = ctx;
  const body = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(6));
  const fresh = ui.el('span');
  const range = ui.el('select', {'aria-label': '기간'}, [[1, '최근 1시간'], [6, '최근 6시간'], [24, '최근 24시간'], [168, '최근 7일']].map(([value, text]) => ui.el('option', {value: String(value), text})));
  range.value = String(hours);

  const paint = result => {
    const data = result.data || {};
    fresh.replaceChildren(ui.freshness(result.at, api.GRADES.list.stale));
    const kpi = (label, value, note) => ui.el('div', {class: 'adm-card adm-kpi'}, ui.el('p', {class: 'adm-eyebrow', text: label}),
      ui.el('div', {class: 'adm-value adm-num', text: value}), ui.el('p', {text: note}));
    const total = (data.error_codes || []).reduce((sum, row) => sum + row.n, 0);
    const codes = (data.error_codes || []).length ? ui.el('ul', {class: 'adm-bars'}, data.error_codes.slice(0, 8).map(row =>
      ui.el('li', {}, ui.el('span', {text: (CODES[row.code] || row.code) + ' (' + row.code + ')'}),
        ui.el('span', {class: 'adm-bar', dataset: {tone: 'bad'}, 'aria-hidden': 'true'}, ui.el('i', {style: {width: (total ? row.n / total * 100 : 0).toFixed(1) + '%'}})),
        ui.el('span', {class: 'adm-num', text: ui.number(row.n)})))) : ui.empty('이 기간에 실패 코드가 없습니다.');
    const timeline = ui.el('div', {class: 'adm-timeline adm-strand', 'aria-label': '최근 호출 ' + (data.timeline || []).length + '건'},
      (data.timeline || []).slice().reverse().map(item => ui.pearl(item.status === 'succeeded' ? 'ok' : item.status === 'unknown' ? 'warn' : 'bad',
        '에이전트 ' + item.id + ' ' + (item.status || '') + (item.code ? ' ' + item.code : ''))));
    const agents = (data.agents || []).length ? ui.table([
      {label: '에이전트', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(row.success_rate == null ? undefined : row.success_rate < .9 ? 'bad' : 'ok'), ui.el('span', {text: row.name}))},
      {label: '프로토콜', render: row => (row.kind || '').toUpperCase() || '—'},
      {label: '호출', class: 'adm-num', render: row => ui.number(row.calls)},
      {label: '성공률', class: 'adm-num', render: row => ui.percent(row.success_rate)},
      {label: 'p95', class: 'adm-num', render: row => ui.ms(row.p95_ms)},
      {label: '최근 실패', render: row => row.last_error ? (CODES[row.last_error] || row.last_error) : '—'},
    ], data.agents, {onSelect: row => ctx.navigate('#/catalog?q=' + encodeURIComponent(row.name)), caption: '에이전트별 호출'}) : ui.empty('이 기간에 에이전트 호출이 없습니다.');
    body.replaceChildren(
      ui.el('section', {class: 'adm-grid adm-kpis'},
        kpi('실행', ui.number(data.operations), '성공 ' + ui.number(data.succeeded)),
        kpi('성공률', ui.percent(data.success_rate), '정책 거부·실패·미확인 포함'),
        kpi('지연 p50', ui.ms(data.p50_ms), '에이전트 호출 기준'),
        kpi('지연 p95', ui.ms(data.p95_ms), '느린 5% 경계')),
      ui.el('div', {class: 'adm-grid adm-two'},
        ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '실패 코드'}), codes),
        ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '실행 경로'}), (data.by_source || []).length ? ui.table([
          {label: '경로', key: 'source'}, {label: '실행', class: 'adm-num', render: row => ui.number(row.total)},
          {label: '성공률', class: 'adm-num', render: row => ui.percent(row.total ? row.succeeded / row.total : null)}], data.by_source) : ui.empty('실행 기록이 없습니다.'))),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '최근 호출'}), ui.el('p', {class: 'adm-muted', text: '왼쪽부터 오래된 순서입니다. 진주 테두리는 결과(정상·미확인·실패)입니다.'}),
        (data.timeline || []).length ? timeline : ui.empty('최근 호출이 없습니다.')),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '에이전트별 호출 (상위 20)'}), agents));
    if ((data.timeline || []).length) requestAnimationFrame(() => ui.stringPearls(timeline, '.adm-pearl'));
  };

  async function load(force = false) {
    const path = '/admin/api/v2/gateway/summary?hours=' + hours;
    const result = await api.read(path, {grade: 'list', force, tags: ['gateway'], onFresh: fresh => { if (ctx.isCurrent() && path.endsWith('=' + hours)) paint(fresh); }});
    if (ctx.isCurrent()) paint(result);
  }
  range.addEventListener('change', () => { hours = Number(range.value); body.replaceChildren(ui.skeleton(6)); load().catch(error => body.replaceChildren(ui.empty(error.message))); });
  const refresh = ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load(true).catch(error => body.replaceChildren(ui.empty(error.message)))}, ui.icon('refresh'), '새로고침');
  const controls = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '실행 제어'}));
  main.replaceChildren(
    ui.el('div', {class: 'adm-head'}, ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'Gateway'}), ui.el('h1', {text: '게이트웨이·실행'})),
      ui.el('div', {class: 'adm-filters'}, range, fresh, refresh)),
    ui.el('p', {class: 'adm-muted', text: 'Chat·Test·워크스페이스·SDK 앱에서 에이전트를 부른 기록입니다.'}),
    controls, body);
  if(ctx.bootstrap()?.me?.role!=='viewer'){const details=ui.el('section',{class:'adm-card'});main.append(details);const loadDetails=()=>gatewayDetails(details,ctx,hours);range.addEventListener('change',loadDetails);refresh.addEventListener('click',loadDetails);void loadDetails();}
  await Promise.all([load(), paintControls(controls, ctx)]);
}

// Kill switches (superadmin): each change shows its effect, asks a reason and checks the current revision.
const SWITCHES = [
  ['execution', 'invoke_enabled', '에이전트 호출', 'Chat·Test·워크스페이스가 에이전트를 부르는 모든 실행'],
  ['execution', 'workflow_enabled', '워크플로 실행', '공개·관리자 워크플로 실행'],
  ['execution', 'delivery_enabled', '결과 전달', '알림·웹훅으로 결과를 보내는 기능'],
  ['fallback', 'enabled', '대체 실행', '원래 에이전트가 실패할 때 정보성 대체 에이전트로 이어 실행'],
];
export async function paintControls(section, ctx, force = false) {
  const {ui, api} = ctx;
  const me = (ctx.bootstrap() || {}).me || {};
  const heading = ui.el('h2', {text: '실행 제어'});
  if (me.role !== 'superadmin') { section.replaceChildren(heading, ui.el('p', {class: 'adm-muted', text: '실행 제어는 최고관리자만 보고 바꿀 수 있습니다.'})); return; }
  let result;
  try { result = await api.read('/admin/api/v2/gateway/controls', {grade: 'detail', force, tags: ['gateway:controls']}); }
  catch (error) { if (error.status === 401) throw error; section.replaceChildren(heading, ui.empty(error.message)); return; }
  const data = result.data || {};
  const readiness = data.fallback?.activation;
  const readinessReasons = {NO_POLICY: '승인된 폴백 정책이 없습니다.', NO_ELIGIBLE_CANARY: '현재 유효한 Canary 정책이 없습니다.',
    EXECUTION_PAUSED: '호출 또는 워크플로 실행 제어가 중지됐습니다.', CANARY_REQUIRED: 'Shadow 확인 후 Canary 전환이 필요합니다.',
    POLICY_EXPIRED: '정책이 만료됐습니다.', CANARY_EXHAUSTED: 'Canary 실행 한도에 도달했습니다.',
    DEFINITION_CHANGED: '워크플로 정의가 변경됐거나 비활성 상태입니다.', SHADOW_REQUIRED: '현재 조합의 성공한 Shadow 기록이 필요합니다.',
    PAIR_REVIEW_REQUIRED: '연결·계약·실행 증거와 공유 의존성을 다시 확인해야 합니다.'};
  const rows = SWITCHES.map(([target, key, label, scope]) => {
    const state = target === 'execution' ? data.execution || {} : data.fallback || {};
    const on = Boolean(state[key]);
    const button = ui.el('button', {class: 'adm-btn' + (on ? ' danger' : ' primary'), type: 'button', 'aria-label': label + (on ? ' 끄기' : ' 켜기'),
      onclick: async () => {
        // Releasing an execution switch is a reviewed command (design 4.3); stopping applies at once.
        const reviewed = target === 'execution' && !on;
        const answer = await ui.confirmChange({title: label + (on ? ' 끄기' : ' 켜기'), summary: scope + '을(를) ' + (on ? '멈춥니다.' : '다시 허용합니다.'),
          effect: on ? '진행 중인 요청은 끝까지 처리되고, 새 요청부터 거부됩니다. 다시 켤 수 있습니다.'
            : reviewed ? '다시 켜기는 승인 요청으로 등록됩니다. 15분 안에 다른 최고관리자가 적용해야 하며, 최고관리자가 1명이면 10분 내 로그인한 본인이 확인 후 적용합니다.'
            : '켜는 즉시 새 요청을 받습니다.',
          confirmLabel: on ? '끄기' : reviewed ? '승인 요청' : '켜기', danger: on});
        if (!answer) return;
        const next = target === 'execution'
          ? {invoke_enabled: Boolean(data.execution.invoke_enabled), workflow_enabled: Boolean(data.execution.workflow_enabled), delivery_enabled: Boolean(data.execution.delivery_enabled), revision: data.execution.revision, [key]: !on}
          : {enabled: !on, revision: data.fallback.revision};
        try {
          const saved = await api.write('/admin/api/v2/gateway/controls', {target, state: next, reason: answer.reason});
          ui.toast(saved && saved.review ? label + ' 켜기 승인 요청을 만들었습니다. 아래 승인 대기에서 적용하세요.' : label + (on ? '을(를) 껐습니다.' : '을(를) 켰습니다.'));
        } catch (error) { ui.toast(error.message, 'bad'); }
        await paintControls(section, ctx, true);
      }}, on ? '끄기' : '켜기');
    if (target === 'fallback' && !on && readiness && !readiness.can_enable) button.disabled = true;
    return ui.el('div', {class: 'adm-switch'}, ui.el('div', {}, ui.el('strong', {}, ui.pearl(on ? 'ok' : 'bad'), ' ', label, ' · ', on ? '켜짐' : '꺼짐'), ui.el('small', {text: scope})), button);
  });
  const activation = ui.el('div', {class: 'adm-card', 'aria-label': '대체 실행 활성화 준비 상태'},
    ui.el('strong', {text: '대체 실행 준비 상태'}),
    ui.el('button', {type: 'button', class: 'adm-btn', text: '입출력 변환 검토', onclick: () => openIOTransforms(ctx)}),
    ui.el('p', {text: !readiness ? '준비 상태를 확인할 수 없습니다. 새로고침 후 확인하세요.' : readiness.can_enable
      ? `현재 조건을 통과한 Canary 정책 ${readiness.eligible_policies}개. 실행별 입력 공유 동의와 표본 비율·한도가 적용됩니다.`
      : readinessReasons[readiness.reason] || '현재 활성화 조건을 확인하세요.'}),
    ui.el('p', {class: 'adm-muted', text: '주소가 다르다는 사실만으로 장애 독립성이 증명되지는 않습니다. 원천·상위 API·계정 및 한도 공유 여부를 별도로 검토해야 합니다.'}),
    ...(readiness?.policies || []).filter(p => !p.eligible).slice(0, 20).map(p => ui.el('p', {text:
      `워크플로 ${p.workflow_id}: ${readinessReasons[p.reason] || '재검토 필요'}`})),
    ...(readiness?.truncated ? [ui.el('p', {text: '최대 100개 정책을 확인했습니다. 나머지는 미검사 상태입니다.'})] : []));
  const reviews = ui.el('div', {'aria-live': 'polite'});
  section.replaceChildren(heading, ui.el('p', {class: 'adm-muted', text: '모든 변경은 사유와 함께 감사 기록에 남고, 다른 관리자가 먼저 바꿨으면 저장되지 않습니다.'}),
    ui.freshness(result.at, api.GRADES.detail.stale), ui.el('div', {class: 'adm-switches'}, rows), activation, reviews);
  await paintReviews(reviews, ctx, () => paintControls(section, ctx, true));
}

// Reviewed commands waiting for a second superadmin (or the sole superadmin after a fresh login).
const REVIEW_STATE = {pending: ['warn', '승인 대기'], approved: ['warn', '적용 중'], applied: ['ok', '적용됨'], failed: ['bad', '적용 실패'], unknown: ['warn','결과 확인 필요'],
  cancelled: ['off', '철회됨'], expired: ['off', '만료'], restore_review_required: ['bad', '복원 후 재검토 필요'], integrity_review_required: ['bad', '무결성 확인 필요']};
const FLAGS = [['invoke_enabled', '호출'], ['workflow_enabled', '워크플로'], ['delivery_enabled', '전달']];
export async function paintReviews(holder, ctx, repaint) {
  const {ui, api} = ctx;
  let result;
  try { result = await api.read('/admin/api/v2/reviews', {grade: 'detail', force: true, tags: ['reviews']}); }
  catch (error) {
    if (error.status === 401) throw error;
    holder.replaceChildren(ui.el('p', {class: 'adm-muted', text: error.message}));
    return;
  }
  const data = result.data || {}, items = (data.items || []);
  if (data.available === false) {
    holder.replaceChildren(ui.el('p', {class: 'adm-muted', text: '승인 저장소가 준비되지 않아 켜기 요청을 만들 수 없습니다. 운영자가 승인 저장소 마이그레이션을 먼저 실행해야 합니다.'}));
    return;
  }
  const minutes = row => Math.max(0, Math.ceil((row.expires - Date.now() / 1000) / 60));
  const act = async (row, action) => {
    const self = row.requested_by === data.me, approve = action === 'approve';
    const answer = await ui.confirmChange(approve
      ? {title: '검토 후 적용 · ' + (row.label || '승인 명령'), summary: row.kind === 'public_service_change' ? '요청된 공개 서비스 변경: '+JSON.stringify(row.payload,null,2) : row.kind === 'admin_account_change' ? '요청된 관리자 계정 변경을 적용하고 권한·비밀번호 변경 시 기존 세션을 종료합니다.' : row.kind === 'retention_policy' ? '승인하면 이 기간보다 오래된 행을 작은 묶음으로 계속 지웁니다. 지운 행은 되돌릴 수 없습니다.' : '요청된 실행 제어 값을 지금 적용합니다.',
         effect: row.kind === 'public_service_change' ? '게시·보안 완화·동의된 단건 알림에 영향을 줍니다. 아래 정확한 변경 내용을 검토하세요. 결과가 불명확하면 현재 기록을 확인하고 자동 재실행하지 않습니다.' : row.kind === 'retention_policy' ? '상태 확인 원본은 일별 요약이 끝난 날만 지웁니다. 백업이 있는지 다시 확인하세요.' : '다른 관리자가 그 사이 제어를 바꿨다면 적용되지 않고 실패로 기록됩니다.',
         confirmLabel: '적용', danger: true, acknowledge: self ? '본인 요청을 단독 검토합니다. 활성 최고관리자가 1명이고 10분 이내 로그인한 경우에만 허용됩니다.' : null}
      : {title: '승인 요청 철회', summary: '이 요청을 더 이상 적용할 수 없게 합니다.', confirmLabel: '철회'});
    if (!answer) return;
    try {
      const done = await api.write('/admin/api/v2/reviews/' + row.id + '/' + action,
        {revision: row.revision, reason: answer.reason, ...(approve && self ? {acknowledge: answer.acknowledged} : {})});
      const status = done && done.item && done.item.status;
      ui.toast(status === 'applied' ? '적용했습니다 · 감사 기록에 남았습니다.' : status === 'unknown' ? '적용 결과를 확인할 수 없습니다. 현재 기록을 점검하세요. 자동 재실행하지 않습니다.' : status === 'failed' ? '요청을 적용하지 못했습니다. 대상 상태와 권한을 확인하고 새 요청을 작성하세요.' : '요청을 철회했습니다.', ['failed','unknown'].includes(status) ? 'bad' : 'ok');
    } catch (error) { ui.toast(error.message, 'bad'); }
    await repaint();
  };
  holder.replaceChildren(ui.el('h3', {text: '승인 대기 · 최근 요청 (계정·실행 제어·보존·공개 서비스)'}), items.length ? ui.el('ul', {class: 'adm-reviews'}, items.map(row => {
    const [tone, label] = REVIEW_STATE[row.status] || [undefined, row.status];
    const flags = row.kind === 'public_service_change' ? [row.payload?.domain,row.payload?.action,JSON.stringify(row.payload?.target || row.payload?.watch || '')].join(' · ') : row.kind === 'admin_account_change' ? accountChangeLabel(row.payload) : row.kind === 'retention_policy'
      ? (row.payload ? row.payload.table + ' → ' + (row.payload.days == null ? '자동 정리 중지' : row.payload.days + '일 보존') : '')
      : FLAGS.map(([key, name]) => name + ' ' + (row.payload && row.payload[key] ? '켜짐' : '꺼짐')).join(' · ');
    const pending = row.status === 'pending';
    return ui.el('li', {class: 'adm-switch'},
      ui.el('div', {}, ui.el('strong', {}, ui.pearl(tone), ' ', row.label || '실행 킬스위치 해제', ' · ', label),
        ui.el('small', {text: (row.payload ? flags + ' · ' : '') + '요청자 ' + row.requested_by + (row.requested_by === data.me ? ' (나)' : '') + (pending ? ' · ' + minutes(row) + '분 남음' : '')})),
      ui.el('div', {class: 'adm-actions'},
        pending && data.can_approve ? ui.el('button', {class: 'adm-btn danger', type: 'button', onclick: () => act(row, 'approve')}, '검토 후 적용') : null,
        pending && (data.can_approve || row.requested_by === data.me) ? ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => act(row, 'cancel')}, '철회') : null));
  })) : ui.el('p', {class: 'adm-muted', text: '승인 대기 중인 요청이 없습니다.'}));
}

// Filters belong to the current individual staff session.
export function reset() { hours = 24; }

function accountChangeLabel(payload) {
  if (!payload) return '';
  const action = {create: '생성', update: '수정', delete: '삭제'}[payload.action] || payload.action;
  const names = {name: '이름', role: '권한', active: '활성 상태'};
  const changes = Object.entries(payload.changes || {}).map(([key, value]) =>
    (names[key] || key) + ' ' + (payload.before ? String(payload.before[key]) + ' → ' : '') + String(value));
  if (payload.password_reset) changes.push('비밀번호 설정');
  return payload.username + ' · ' + action + (changes.length ? ' · ' + changes.join(' · ') : '');
}
