import {incident} from './customer-management.js';
import {securityRules} from './public-operations.js';
// ⑥ 보안·감사: 관리자 감사 기록(변경 사유 포함), 접속 보안 상태·이벤트, 워크스페이스 사고·감사. 읽기 전용.
const TABS = [['audit', '관리자 감사'], ['access', '접속 보안'], ['rules', '보안 규칙·승인'], ['incidents', '사고·운영 감사']];
const THREAT = {normal: ['ok', '정상'], elevated: ['warn', '경계'], under_attack: ['bad', '공격 대응 중']};
const memory = {tab: 'audit', action: '', username: '', offset: 0};
const when = value => typeof value === 'number' && value > 0 ? new Date(value * 1000).toLocaleString('ko-KR', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '—';

function detailText(raw) {
  // Audit details are stored text; show the reason first when the change came from the renewed console.
  let value = raw;
  try { value = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch {}
  if (value && typeof value === 'object') {
    const {reason, via, ...rest} = value;
    const others = Object.keys(rest).length ? JSON.stringify(rest) : '';
    return [reason ? '사유: ' + reason : '', others].filter(Boolean).join(' · ') || '—';
  }
  return raw ? String(raw).slice(0, 240) : '—';
}

export async function render(main, ctx) {
  const {ui, rest} = ctx;
  if (TABS.some(([id]) => id === rest[0])) memory.tab = rest[0];
  const body = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(6));
  main.replaceChildren(
    ui.el('div', {class: 'adm-head'}, ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'Security'}), ui.el('h1', {text: '보안·감사'})),
      ui.el('a', {class: 'adm-btn', href: '#/security/rules'}, ui.icon('external'), '보안 규칙·승인')),
    ui.el('div', {class: 'adm-tabs', role: 'tablist', 'aria-label': '보안·감사 보기'}, TABS.map(([id, label]) =>
      ui.el('a', {role: 'tab', href: '#/security/' + id, 'aria-selected': String(memory.tab === id), class: 'adm-tab'}, ui.pearl(memory.tab === id ? 'ok' : undefined), label))),
    body);
  try { await VIEWS[memory.tab](body, ctx); }
  catch (error) { if (error.status === 401) throw error; body.replaceChildren(ui.empty(error.status === 403 ? '이 정보를 볼 권한이 없습니다.' : error.message)); }
}

const VIEWS = {
  rules: securityRules,
  async audit(body, ctx) {
    const {ui, api} = ctx;
    const action = ui.el('input', {type: 'search', value: memory.action, maxlength: '60', 'aria-label': '작업 코드', placeholder: '작업 코드 (예: AGENT_DEACTIVATE)'});
    const user = ui.el('input', {type: 'search', value: memory.username, maxlength: '60', 'aria-label': '관리자 아이디', placeholder: '관리자 아이디'});
    const holder = ui.el('div');
    const load = async () => {
      const search = new URLSearchParams({limit: '50', offset: String(memory.offset)});
      if (memory.action) search.set('action', memory.action);
      if (memory.username) search.set('username', memory.username);
      const result = await api.read('/admin/api/audit/logs?' + search, {grade: 'list', tags: ['security']});
      if (!ctx.isCurrent()) return;
      const logs = result.data.logs || [], total = result.data.count || 0;
      const page = Math.floor(memory.offset / 50) + 1, pages = Math.max(1, Math.ceil(total / 50));
      holder.replaceChildren(logs.length ? ui.table([
        {label: '시각', render: row => when(row.at)},
        {label: '관리자', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(row.status === 'SUCCESS' ? 'ok' : 'bad'), ui.el('span', {text: row.username + ' (' + row.role + ')'}))},
        {label: '작업', render: row => row.action_name + ' · ' + row.action},
        {label: '대상', render: row => row.target || '—'},
        {label: '사유·내용', render: row => detailText(row.details)},
      ], logs, {caption: '관리자 감사 기록'}) : ui.empty('조건에 맞는 감사 기록이 없습니다.'),
        ui.el('div', {class: 'adm-pager'}, ui.el('span', {class: 'adm-muted adm-num', text: ui.number(total) + '건 중 ' + page + '/' + pages + '쪽'}),
          ui.el('button', {class: 'adm-btn', type: 'button', disabled: page <= 1, onclick: () => { memory.offset -= 50; load(); }}, '이전'),
          ui.el('button', {class: 'adm-btn', type: 'button', disabled: page >= pages, onclick: () => { memory.offset += 50; load(); }}, '다음')));
    };
    let typing = 0;
    for (const [input, key] of [[action, 'action'], [user, 'username']])
      input.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { memory[key] = input.value.trim(); memory.offset = 0; load().catch(() => {}); }, 350); });
    body.replaceChildren(ui.el('div', {class: 'adm-filters'}, action, user), holder);
    await load();
  },
  async access(body, ctx) {
    const {ui, api} = ctx;
    const [status, events] = await Promise.all([
      api.read('/admin/api/security/status', {grade: 'live', tags: ['security']}),
      api.read('/admin/api/security/events?limit=50', {grade: 'list', tags: ['security']})]);
    const s = status.data || {}, [tone, label] = THREAT[s.threat_level] || [undefined, s.threat_level || '확인 불가'];
    const kpi = (name, value, note, mark) => ui.el('div', {class: 'adm-card adm-kpi'}, ui.el('p', {class: 'adm-eyebrow', text: name}),
      ui.el('div', {class: 'adm-value adm-num'}, mark || null, ' ', value), ui.el('p', {text: note}));
    const list = events.data.events || [];
    body.replaceChildren(
      ui.el('div', {class: 'adm-filters'}, ui.freshness(status.at, api.GRADES.live.stale)),
      ui.el('section', {class: 'adm-grid adm-kpis'},
        kpi('위협 수준', label, '점수 ' + (s.threat_score ?? '—'), ui.pearl(tone)),
        kpi('처리 중 요청', ui.number(s.in_flight_requests), '동시 처리 한도 ' + ui.number(s.max_concurrent_requests)),
        kpi('접속 IP', ui.number(s.active_ips_count), '최근 활동'),
        kpi('긴급 방어', s.under_attack_mode ? '켜짐' : '꺼짐', '요청 속도 배수 ' + (s.rate_multiplier ?? '—'))),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '최근 보안 이벤트'}), list.length ? ui.table([
        {label: '시각', render: row => when(row.at)}, {label: '유형', render: row => row.event_type},
        {label: 'IP', key: 'ip'}, {label: '경로', render: row => (row.method || '') + ' ' + (row.path || '')},
        {label: '내용', render: row => String(row.detail || '—').slice(0, 120)},
      ], list, {caption: '보안 이벤트'}) : ui.empty('최근 보안 이벤트가 없습니다.')));
  },
  async incidents(body, ctx) {
    const {ui, api} = ctx;
    const base = '/admin/api/v2/customers/operations';
    const [incidents, audit, options] = await Promise.all([api.read(base + '/incidents', {grade: 'list', tags: ['security']}), api.read(base + '/audit', {grade: 'sensitive', tags: ['security']}).catch(error => { if (error.status === 403) return {data: {audit: [], denied: true}}; throw error; }), api.read(base+'/options',{grade:'sensitive'})]);
    const items = incidents.data.incidents || [], records = audit.data.audit || [];
    body.replaceChildren(
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '사고'}), options.data.can_support ? ui.el('button',{class:'adm-btn',type:'button',text:'장애 등록',onclick:()=>incident(ctx)}) : null, items.length ? ui.table([
        {label: '사고', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(row.status === 'resolved' || row.status === 'closed' ? 'off' : 'bad'), ui.el('span', {text: row.summary || row.title || row.id}))},
        {label: '상태', render: row => row.status || '—'}, {label: '심각도', render: row => row.severity || '—'}, {label: '최근 변경', render: row => when(row.updated)},
      ], items, {caption: '사고',onSelect:row=>{if(options.data.can_support && row.status!=='resolved')incident(ctx,row);}}) : ui.empty('기록된 사고가 없습니다.')),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '워크스페이스 운영 감사'}), records.length ? ui.table([
        {label: '시각', render: row => when(row.created)}, {label: '관리자', render: row => String(row.actor ?? row.staff_id ?? '—')},
        {label: '작업', render: row => row.action || row.kind || '—'}, {label: '대상', render: row => row.object_id || row.target || '—'},
      ], records.slice(0, 50), {caption: '운영 감사'}) : ui.empty(audit.data.denied ? '운영 감사는 최고관리자만 열람할 수 있습니다.' : '운영 감사 기록이 없습니다.')));
  },
};

// Filters belong to the current individual staff session.
export function reset() { Object.assign(memory, {tab: 'audit', action: '', username: '', offset: 0}); }
