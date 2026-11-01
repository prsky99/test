import {assignments} from './insights.js';
import * as specialists from './specialists.js';
import * as staffWorkspaces from './staff-workspaces.js';
import * as management from './customer-management.js';
// ④ 고객·워크스페이스: 워크스페이스 통합관리(WAC) API를 읽어 탭으로 보여 준다. 케이스 응대와 명령 검토·철회를 여기서 한다.
const WAC = '/admin/api/v2/customers/operations';
const TABS = [['overview', '개요'], ['customers', '고객'], ['requests', '고객 요청'], ['organizations', '조직'], ['staff', '직원 작업공간'], ['specialists', '전문 관리'], ['assignments','케이스 배정'], ['cases', '지원 케이스'], ['commands', '승인 명령'], ['credits', '크레딧 정산'], ['events', 'AI·실행 이력']];
const ALERTS = {unknown_outcomes_require_review: '결과 미확인 실행 검토 필요', operational_observations_incomplete: '운영 관측 데이터 일부 누락',
  projection_stale: '이력 반영 지연', projection_backlog: '이력 처리 대기 누적', event_integrity_review_required: '이력 무결성 검토 필요', historical_backfill_incomplete: '과거 기록 이전 미완료', historical_source_integrity_review_required: '과거 기록 무결성 검토 필요'};
const KINDS = {credit_adjust: '크레딧 조정', account_restrict: '고객 계정 제한', sessions_revoke: '고객 세션 종료'};
const memory = {tab: 'overview', q: ''};
const CASE_STATUS = {new: '새 요청', triaged: '분류됨', in_progress: '처리 중', waiting_customer: '고객 답변 대기', waiting_internal: '내부 확인 대기', resolved: '해결', closed: '종료'};
const PRIORITY = {normal: '보통', high: '높음', urgent: '긴급'};
const REQUEST_KINDS = {inquiries: '문의', privacy: '개인정보 요청', cancellations: '수신 해지'};
const REQUEST_STATUS = {pending: '대기', in_progress: '처리 중', resolved: '해결', archived: '보관',
  received: '접수', pending_verification: '본인 확인 대기', processing: '처리 중', completed: '완료', declined: '거절'};
const requestMemory = {kind: 'inquiries', status: '', q: ''};

// Footer requests: inquiries and privacy requests are handled here with a reason; cancellations are read only.
async function requestsView(body, ctx) {
  const {ui, api} = ctx;
  const role = ((ctx.bootstrap() || {}).me || {}).role;
  if (!['superadmin', 'admin'].includes(role)) { body.replaceChildren(ui.empty('고객 요청 본문은 관리자 이상만 볼 수 있습니다.')); return; }
  const summary = await api.read('/admin/api/v2/requests/summary', {grade: 'live', force: true, tags: ['requests']}).then(r => r.data).catch(() => ({}));
  const kind = ui.el('select', {'aria-label': '요청 종류'}, Object.entries(REQUEST_KINDS).map(([value, text]) => ui.el('option', {value, text})));
  const status = ui.el('select', {'aria-label': '처리 상태'});
  const search = ui.el('input', {type: 'search', maxlength: '120', 'aria-label': '요청 검색', placeholder: '요청 ID·이메일·제목 검색', value: requestMemory.q});
  const holder = ui.el('div', {'aria-live': 'polite'});
  const statuses = () => {
    const keys = requestMemory.kind === 'inquiries' ? ['pending', 'in_progress', 'resolved', 'archived']
      : requestMemory.kind === 'privacy' ? ['received', 'pending_verification', 'processing', 'completed', 'declined'] : [];
    status.replaceChildren(ui.el('option', {value: '', text: '전체 상태'}), ...keys.map(key => ui.el('option', {value: key, text: REQUEST_STATUS[key]})));
    status.hidden = !keys.length; status.value = keys.includes(requestMemory.status) ? requestMemory.status : '';
  };
  let items = [], total = 0;
  let listGeneration=0;
  const load = async (cursor = null) => {
    const generation=++listGeneration;
    const query = new URLSearchParams({limit:'50'});if(cursor)query.set('cursor',cursor);
    if (requestMemory.status) query.set('status', requestMemory.status);
    if (requestMemory.q) query.set('q', requestMemory.q);
    const {data} = await api.read('/admin/api/v2/requests/' + requestMemory.kind + '?' + query, {grade: 'list', force: true, tags: ['requests']});
    if (!ctx.isCurrent()||generation!==listGeneration) return;
    items = cursor ? items.concat(data.items || []) : (data.items || []); if(data.total!=null)total=data.total;
    const title = row => row.subject || (row.request_type ? row.request_type : row.reason) || row.request_id || row.inquiry_id;
    ui.fill(holder, ui.el('p', {class: 'adm-muted adm-num', text: ui.number(total) + '건 중 ' + ui.number(items.length) + '건 표시'}),
      items.length ? ui.table([
        {label: '요청', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(['resolved', 'archived', 'completed', 'declined', 'reactivated'].includes(row.status) ? 'off' : 'warn'), ui.el('span', {text: String(title(row) || '—')}))},
        {label: '상태', render: row => REQUEST_STATUS[row.status] || row.status || '—'},
        {label: '연락처', render: row => row.email || row.token_masked || row.visitor_token_masked || '—'},
        {label: '접수', render: row => when(row.created_at)},
      ], items, {caption: REQUEST_KINDS[requestMemory.kind], onSelect: row => openRequest(ctx, requestMemory.kind, row, () => requestsView(body, ctx))}) : ui.empty('조건에 맞는 요청이 없습니다.'),
      data.next_cursor ? ui.el('div', {class: 'adm-more'}, ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load(data.next_cursor)}, '50건 더 보기')) : null);
  };
  kind.value = requestMemory.kind; statuses();
  kind.addEventListener('change', () => { requestMemory.kind = kind.value; requestMemory.status = ''; statuses(); load(); });
  status.addEventListener('change', () => { requestMemory.status = status.value; load(); });
  let typing = 0;
  search.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { requestMemory.q = search.value.trim(); load(); }, 350); });
  const inquiries = summary.inquiries || {}, privacy = summary.privacy || {}, cancellations = summary.cancellations || {};
  body.replaceChildren(
    ui.el('section', {class: 'adm-grid adm-kpis'},
      kpi(ui, '미해결 문의', ui.number((inquiries.pending || 0) + (inquiries.in_progress || 0)), '전체 ' + ui.number(inquiries.total)),
      kpi(ui, '미완료 개인정보 요청', ui.number((privacy.total || 0) - (privacy.completed || 0)), '완료 ' + ui.number(privacy.completed)),
      kpi(ui, '수신 해지', ui.number(cancellations.cancelled), '재활성화 ' + ui.number(cancellations.reactivated))),
    ui.el('div', {class: 'adm-filters'}, kind, status, search), holder);
  await load();
}

async function openRequest(ctx, kind, row, reload) {
  const {ui, api} = ctx;
  const id = row.inquiry_id || row.request_id;
  const content = ui.el('div');
  ui.drawer(REQUEST_KINDS[kind] + ' · ' + id, content, ['resolved', 'archived', 'completed', 'declined'].includes(row.status) ? 'off' : 'warn');
  const field = (label, value) => [ui.el('dt', {text: label}), ui.el('dd', {class: 'adm-message', text: String(value ?? '—')})];
  const facts = kind === 'inquiries'
    ? [['분류', row.category], ['이름', row.name], ['이메일', row.email], ['제목', row.subject], ['내용', row.message], ['답변', row.admin_response], ['처리자', row.resolved_by]]
    : kind === 'privacy'
      ? [['유형', row.request_type], ['이메일', row.email], ['방문자', row.visitor_token_masked], ['내용', row.details], ['검토 메모', row.notes], ['근거 해시', row.proof_hash], ['접수',when(row.created_at)], ['처리 기한',when(row.statutory_deadline)], ['완료',when(row.completed_at)], ['GPC 기록',row.gpc_detected ? '있음' : '없음']]
      : [['출처', row.source], ['방문자', row.token_masked], ['사유', row.reason], ['메모', row.notes]];
  const reread = ui.el('button',{class:'adm-btn',type:'button',text:'현재 요청 다시 조회',onclick:async()=>{
    const result=await api.read('/admin/api/v2/requests/'+kind+'?q='+encodeURIComponent(id),{grade:'sensitive',force:true});
    if (!ctx.isCurrent() || !content.isConnected) return;
    const current=(result.data.items || []).find(item=>(item.inquiry_id || item.request_id)===id);
    if (current) await openRequest(ctx,kind,current,reload);
  }});
  let form = null;
  if (kind !== 'cancellations') {
    const keys = kind === 'inquiries' ? ['pending', 'in_progress', 'resolved', 'archived'] : ['received', 'pending_verification', 'processing', 'completed', 'declined'];
    const status = ui.el('select', {'aria-label': '처리 상태'}, keys.map(key => ui.el('option', {value: key, text: REQUEST_STATUS[key]})));
    status.value = keys.includes(row.status) ? row.status : keys[0];
    if (kind === 'privacy' && row.status === 'completed') for (const option of status.options) option.disabled = option.value !== 'completed';
    const text = ui.el('textarea', {rows: '4', maxlength: kind === 'inquiries' ? '4000' : '2000', 'aria-label': kind === 'inquiries' ? '고객 답변' : '검토 메모'});
    const proof = kind === 'privacy' ? ui.el('input', {type: 'text', maxlength: '64', 'aria-label': '완료 근거 SHA-256', placeholder: '완료 시 근거 문서의 SHA-256 (64자)'}) : null;
    text.value = kind === 'privacy' ? (row.notes || '') : (row.admin_response || '');
    if (proof && /^[a-f0-9]{64}$/.test(row.proof_hash || '')) proof.value = row.proof_hash;
    const reason = ui.el('input', {type: 'text', maxlength: '300', 'aria-label': '변경 사유', placeholder: '변경 사유 (감사 기록, 4~300자)'});
    const note = ui.el('p', {class: 'adm-status', role: 'status', 'aria-live': 'polite'});
    const submit = ui.el('button', {class: 'adm-btn primary', type: 'submit', text: '저장'});
    form = ui.el('form', {class: 'adm-case-form', novalidate: true}, ui.el('h3', {text: '처리'}),
      ui.el('div', {class: 'adm-filters'}, status), text, proof, ui.el('div', {class: 'adm-filters'}, reason), note, ui.el('div', {class: 'adm-actions'}, submit));
    if (kind === 'privacy' && row.status === 'completed') note.textContent = '완료 상태는 되돌릴 수 없습니다. 검토 메모와 근거는 별도 사유로 보완할 수 있습니다.';
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (reason.value.trim().length < 4) { note.textContent = '변경 사유를 4자 이상 입력하세요.'; reason.focus(); return; }
      const value = text.value.trim();
      const payload = kind === 'inquiries'
        ? {status: status.value, reason: reason.value.trim(), ...(value ? {response: value} : {})}
        : {status: status.value, reason: reason.value.trim(), ...(value ? {notes: value} : {}), ...(proof.value.trim() ? {proof_hash: proof.value.trim().toLowerCase()} : {})};
      submit.disabled = true;
      try {
        await api.write('/admin/api/v2/requests/' + kind + '/' + encodeURIComponent(id), payload);
        ui.toast('처리 내용을 저장했습니다 · 감사 기록에 남았습니다.');
        await reload();
        content.closest('.adm-drawer')?.querySelector('header button')?.click();
      } catch (error) { note.textContent = error.message; submit.disabled = false; }
    });
  }
  ui.fill(content, ui.el('dl', {}, ...field('상태', REQUEST_STATUS[row.status] || row.status), ...facts.flatMap(([label, value]) => field(label, value)),
    ...field('접수', when(row.created_at))),
    reread,
    kind === 'privacy' ? ui.el('p',{class:'adm-muted',text:'접수 기록은 작업 완료의 증거가 아닙니다. 실제 처리 결과를 검토한 뒤 근거 SHA-256을 기록하세요.'}) : null,
    form || ui.el('p', {class: 'adm-muted', text: '관리자는 철회된 동의를 복원할 수 없습니다. 고객이 직접 다시 신청하고 주소를 검증해야 합니다.'}));
}

const caseTone = row => ['resolved', 'closed'].includes(row.status) ? 'off' : row.priority === 'urgent' ? 'bad' : row.priority === 'high' || row.status === 'new' ? 'warn' : 'ok';

// Support case: thread plus one reviewed action (status, priority and a reply or internal note) per submit.
async function openCase(ctx, row, options, reload) {
  const {ui, api} = ctx;
  const content = ui.el('div', {}, ui.skeleton(5));
  ui.drawer(row.subject || '지원 케이스', content, caseTone(row));
  const show = async () => {
    try {
      // Reading a case is itself audited by the server, so it is never served from cache.
      const {data} = await api.read(WAC + '/cases/' + encodeURIComponent(row.id), {grade: 'sensitive', force: true, tags: ['customers']});
      const item = data.case || row, messages = data.messages || [];
      const thread = ui.el('ol', {class: 'adm-thread-list', 'aria-label': '메시지 ' + messages.length + '건'}, messages.map(message => {
        const staff = String(message.author || '').startsWith('staff:'), internal = message.visibility === 'internal';
        return ui.el('li', {dataset: {side: staff ? 'staff' : 'customer', visibility: message.visibility}},
          ui.el('p', {class: 'adm-muted', text: (staff ? '운영팀 ' + message.author.slice(6) : '고객') + ' · ' + when(message.created) + (internal ? ' · 내부 메모(고객에게 보이지 않음)' : '')}),
          ui.el('p', {class: 'adm-message', text: message.body}));
      }));
      const field = (label, value) => [ui.el('dt', {text: label}), ui.el('dd', {text: String(value ?? '—')})];
      let form = null;
      if (options.can_support) {
        const select = (map, value, label) => { const node = ui.el('select', {'aria-label': label}, Object.entries(map).map(([key, text]) => ui.el('option', {value: key, text}))); node.value = value; return node; };
        const assigned = ui.el('input', {type:'number',min:'1',step:'1',value:item.assigned_to ?? '', 'aria-label':'담당 관리자 ID'});
        const status = select(CASE_STATUS, item.status, '상태'), priority = select(PRIORITY, item.priority, '우선순위');
        const message = ui.el('textarea', {rows: '4', maxlength: '4000', 'aria-label': '보낼 메시지'});
        const visibility = select({customer: '고객에게 답변', internal: '내부 메모'}, 'customer', '공개 범위');
        const note = ui.el('p', {class: 'adm-status', role: 'status', 'aria-live': 'polite'});
        const submit = ui.el('button', {class: 'adm-btn primary', type: 'submit', text: '저장'});
        form = ui.el('form', {class: 'adm-case-form', novalidate: true},
          ui.el('h3', {text: '응대'}), ui.el('div', {class: 'adm-filters'}, status, priority, visibility), ui.el('label', {text:'담당 관리자 ID'}, assigned), message, note, ui.el('div', {class: 'adm-actions'}, submit));
        visibility.addEventListener('change', () => { submit.textContent = visibility.value === 'internal' ? '내부 메모 저장' : '고객에게 보내기'; });
        visibility.dispatchEvent(new Event('change'));
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const text = message.value.trim();
          if (assigned.value && (!Number.isSafeInteger(Number(assigned.value)) || Number(assigned.value)<1)) { note.textContent='유효한 담당 관리자 ID를 입력하세요.';return; }
          if (!text) { note.textContent = '메시지를 입력하세요. 상태만 바꿀 때도 짧은 메모를 남깁니다.'; message.focus(); return; }
          submit.disabled = true;
          const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
          try {
            await api.write(WAC + '/cases/' + encodeURIComponent(item.id) + '/actions', {revision: item.revision, status: status.value, priority: priority.value,
              assigned_to: assigned.value ? Number(assigned.value) : null, message: text, visibility: visibility.value, request_id: id});
            ui.toast(visibility.value === 'internal' ? '내부 메모를 저장했습니다.' : '고객에게 답변을 보냈습니다.');
            api.invalidate('customers');
            await show(); await reload();
          } catch (error) {
            note.textContent = error.status === 409 ? '다른 운영자가 먼저 바꿨습니다. 최신 내용을 다시 불러왔습니다.' : error.message;
            if (error.status === 409) await show();
          } finally { submit.disabled = false; }
        });
      }
      ui.fill(content,
        ui.el('dl', {}, ...field('상태', CASE_STATUS[item.status] || item.status), ...field('우선순위', PRIORITY[item.priority] || item.priority),
          ...field('고객', item.customer_id), ...field('워크스페이스', item.workspace_id), ...field('담당', item.assigned_to), ...field('접수', when(item.created))),
        options.can_support ? ui.el('button', {class:'adm-btn',type:'button',text:'기존 고객 요청 연결',onclick:()=>management.linkCase(ctx,item)}) : null,
        (data.source_links || []).length ? ui.el('pre',{class:'adm-message',text:JSON.stringify(data.source_links,null,2)}) : null,
        ui.el('h3', {text: '대화'}), messages.length ? thread : ui.empty('메시지가 없습니다.'),
        data.messages_truncated ? ui.el('p', {class: 'adm-muted', text: '최근 200건만 표시합니다.'}) : null,
        form || ui.el('p', {class: 'adm-muted', text: '응대는 관리자 이상 권한이 필요합니다.'}));
    } catch (error) {
      if (error.status === 401) throw error;
      content.replaceChildren(ui.empty(error.status === 403 ? '이 케이스를 열 권한이 없습니다.' : error.message));
    }
  };
  await show();
}

const when = value => typeof value === 'number' && value > 0 ? new Date(value * 1000).toLocaleString('ko-KR', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';

export async function render(main, ctx) {
  if(ctx.rest[0]==='workflow-search') return (await import('./workflow-search.js')).render(main,ctx);
  specialists.reset(); staffWorkspaces.reset();
  const {ui, api, rest} = ctx;
  if(ctx.params.has('q'))memory.q=ctx.params.get('q');
  if (TABS.some(([id]) => id === rest[0])) memory.tab = rest[0];
  if(ctx.bootstrap()?.me?.role==='operator')memory.tab='assignments';
  const body = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(6));
  const tabs = ui.el('div', {class: 'adm-tabs', role: 'tablist', 'aria-label': '고객·워크스페이스 보기'}, TABS.filter(([id])=>ctx.bootstrap()?.me?.role!=='operator'||id==='assignments').map(([id, label]) =>
    ui.el('a', {role: 'tab', href: '#/customers/' + id, 'aria-selected': String(memory.tab === id), class: 'adm-tab'}, ui.pearl(memory.tab === id ? 'ok' : undefined), label)));
  main.replaceChildren(
    ui.el('div', {class: 'adm-head'}, ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'Customers'}), ui.el('h1', {text: '고객·워크스페이스'})),
      ctx.bootstrap()?.me?.role!=='operator'?ui.el('a', {class: 'adm-btn', href: '#/customers/overview'}, '운영 개요'):null),
    tabs, body);
  if(memory.tab==='assignments'){await assignments(body,ctx);return;}
  const read = (path, grade = 'list') => api.read(WAC + path, {grade, tags: ['customers']});
  const fail = error => { if (error.status === 401) throw error; body.replaceChildren(ui.empty(error.status === 403 ? '이 정보는 개인 관리자 권한으로만 볼 수 있습니다.' : error.message)); };
  try {
    // Footer requests do not depend on workspace operations; they open before its migration check.
    if (memory.tab === 'requests') { await requestsView(body, ctx); return; }
    if (memory.tab === 'staff') { await staffWorkspaces.render(body, ctx); return; }
    if (memory.tab === 'specialists') { await specialists.render(body, ctx); return; }
    // Workspace operations must be migrated first; until then show why instead of calling every list.
    const options = await read('/options', 'reference');
    if (options.data && options.data.migration_required) {
      body.replaceChildren(ui.empty('워크스페이스 통합관리 저장소가 아직 준비되지 않았습니다. 운영 마이그레이션 후 표시됩니다.'));
      return;
    }
    await VIEWS[memory.tab](body, ctx, read);
    if (!ctx.isCurrent()) return;
    const customer = ctx.params.get('customer'), workspace = ctx.params.get('workspace'), operation = ctx.params.get('operation');
    if (memory.tab === 'customers' && /^cu_[a-f0-9]{32}$/.test(customer || '')) await openCustomer(ctx, read, {id: customer});
    if (memory.tab === 'organizations' && /^ws_[a-f0-9]{32}$/.test(workspace || '')) await openOrganization(ctx, read, {id: workspace});
    if (memory.tab === 'events' && /^[A-Za-z0-9_.:-]{8,120}$/.test(operation || '')) await openOperation(ctx, read, operation);
  } catch (error) { fail(error); }
}

function kpi(ui, label, value, note) {
  return ui.el('div', {class: 'adm-card adm-kpi'}, ui.el('p', {class: 'adm-eyebrow', text: label}), ui.el('div', {class: 'adm-value adm-num', text: value}), ui.el('p', {text: note}));
}

// Cursor lists share one renderer: "더 보기" appends the next page.
async function pagedTable(body, ctx, read, path, key, columns, {onSelect, empty} = {}) {
  const {ui} = ctx;
  let items = [], cursor = '';
  const holder = ui.el('div');
  const load = async () => {
    const result = await read(path + (path.includes('?') ? '&' : '?') + 'cursor=' + encodeURIComponent(cursor));
    if (!ctx.isCurrent()) return;
    items = items.concat(result.data[key] || []);
    cursor = result.data.next_cursor || '';
    ui.fill(holder, items.length ? ui.table(columns, items, {onSelect, caption: key}) : ui.empty(empty || '기록이 없습니다.'),
      cursor ? ui.el('div', {class: 'adm-more'}, ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load().catch(() => {})}, '더 보기')) : null);
  };
  body.replaceChildren(holder);
  await load();
}

const VIEWS = {
  async overview(body, ctx, read) {
    const {ui, api} = ctx;
    const result = await read('/overview?hours=24', 'live');
    const data = result.data || {}, ingestion = data.ingestion || {};
    const alerts = (data.alerts || []).map(code => ui.el('li', {dataset: {level: 'warning'}}, ui.icon('alert'), ui.el('span', {text: ALERTS[code] || code})));
    body.replaceChildren(
      ui.el('div', {class: 'adm-filters'}, ui.freshness(result.at, api.GRADES.live.stale)),
      ui.el('ul', {class: 'adm-alerts', 'aria-label': '워크스페이스 경보'}, alerts.length ? alerts : [ui.el('li', {dataset: {level: 'ok'}}, ui.icon('check'), ui.el('span', {text: '워크스페이스 경보가 없습니다.'}))]),
      ui.el('section', {class: 'adm-grid adm-kpis'},
        kpi(ui, '고객', ui.number(data.customers), '24시간 신규 ' + ui.number(data.new_customers)),
        kpi(ui, '활동 고객', ui.number(data.active_customers), '최근 24시간'),
        kpi(ui, '활성 조직', data.active_organizations == null ? '확인 불가' : ui.number(data.active_organizations), '조직 워크스페이스'),
        kpi(ui, '열린 지원 케이스', ui.number(data.open_cases), '응대 대기 포함'),
        kpi(ui, '기록 반영', ingestion.complete ? '최신' : '지연', ingestion.last_projection ? '마지막 반영 ' + when(ingestion.last_projection) : '반영 기록 없음')),
      ui.el('p', {class: 'adm-muted', text: '결제·구독은 아직 출시 전입니다. 크레딧은 실제 돈이 아닙니다.'}));
  },
  async customers(body, ctx, read) {
    const {ui} = ctx;
    const search = ui.el('input', {type: 'search', value: memory.q, maxlength: '80', 'aria-label': '고객 ID 검색', placeholder: '고객 ID 일부 (영문·숫자)'});
    const holder = ui.el('div');
    const run = () => {
      memory.q = search.value.trim().replace(/[^A-Za-z0-9_-]/g, '');
      return pagedTable(holder, ctx, read, '/customers?limit=50&q=' + encodeURIComponent(memory.q), 'customers', [
        {label: '고객', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(row.active ? 'ok' : 'off'), ui.el('span', {text: row.id}))},
        {label: '로그인 방식', render: row => row.issuer || '—'}, {label: '가입', render: row => when(row.created)},
        {label: '마지막 로그인', render: row => when(row.last_login)}, {label: '상태', render: row => row.active ? '활성' : '비활성'},
      ], {onSelect: row => openCustomer(ctx, read, row), empty: '조건에 맞는 고객이 없습니다.'});
    };
    let typing = 0;
    search.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => run().catch(() => {}), 350); });
    body.replaceChildren(ui.el('div', {class: 'adm-filters'}, search), holder);
    await run();
  },
  async organizations(body, ctx, read) {
    const {ui} = ctx;
    await pagedTable(body, ctx, read, '/organizations?limit=50', 'organizations', [
      {label: '조직', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(row.active ? 'ok' : 'off'), ui.el('span', {text: row.name || row.id}))},
      {label: 'ID', key: 'id'}, {label: '만든 고객', render: row => row.customer_id || '—'},
      {label: '만든 날', render: row => when(row.created)}, {label: '최근 변경', render: row => when(row.updated)},
    ], {empty: '조직이 없습니다.', onSelect: row => openOrganization(ctx, read, row)});
  },
  async cases(body, ctx, read) {
    const {ui} = ctx;
    const options = (await read('/options', 'reference')).data || {};
    const list = () => pagedTable(body, ctx, read, '/cases?limit=50', 'cases', [
      {label: '케이스', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(caseTone(row)), ui.el('span', {text: row.subject || row.id}))},
      {label: '상태', render: row => CASE_STATUS[row.status] || row.status || '—'}, {label: '우선순위', render: row => PRIORITY[row.priority] || row.priority || '—'},
      {label: '고객', render: row => row.customer_id || '—'}, {label: '최근 변경', render: row => when(row.updated)},
    ], {empty: '지원 케이스가 없습니다.', onSelect: row => openCase(ctx, row, options, list)});
    await list();
  },
  async commands(body, ctx, read) {
    const {ui, api} = ctx;
    const [result, options] = await Promise.all([read('/commands'), read('/options', 'reference')]);
    const items = result.data.commands || [], me = options.data || {};
    const STATE = {pending: ['warn', '승인 대기'], applied: ['ok', '적용됨'], cancelled: ['off', '철회됨'], expired: ['off', '만료']};
    const state = row => STATE[row.status] || [undefined, row.status];
    const left = row => {
      const minutes = Math.ceil((row.expires - Date.now() / 1000) / 60);
      return row.status !== 'pending' ? when(row.expires) : minutes > 0 ? minutes + '분 남음' : '만료';
    };
    const refresh = async () => { if (ctx.isCurrent()) { api.invalidate('customers'); await VIEWS.commands(body, ctx, read); } };
    const open = async row => {
      const content = ui.el('div', {}, ui.skeleton(4));
      ui.drawer(KINDS[row.kind] || row.kind, content, state(row)[0]);
      try {
        const {data} = await api.read(WAC + '/commands/' + encodeURIComponent(row.id), {grade: 'detail', force: true, tags: ['customers']});
        const command = data.command || row, review = data.review || {};
        const field = (label, value) => [ui.el('dt', {text: label}), ui.el('dd', {text: String(value ?? '—')})];
        const self = command.requested_by === me.staff_id, pending = command.status === 'pending';
        const approve = async () => {
          const answer = await ui.confirmChange({title: '검토 후 적용 · ' + (KINDS[review.kind] || review.kind),
            summary: '요청 내용을 확인했고 지금 적용합니다. 적용 후에는 되돌리는 별도 요청이 필요합니다.',
            effect: '요청 후 15분 안에 요청자와 다른 최고관리자가 적용해야 합니다.', confirmLabel: '적용', danger: true, minimum: 5,
            acknowledge: self ? '단독 검토임을 확인합니다. 활성 최고관리자가 1명이고 최근 10분 이내 로그인한 경우에만 허용됩니다.' : null});
          if (!answer) return;
          try {
            await api.write(WAC + '/commands/' + encodeURIComponent(command.id) + '/approve',
              {revision: command.revision, reason: answer.reason, confirm: 'APPLY', ...(self ? {allow_self_review: answer.acknowledged} : {})});
            ui.toast('적용했습니다 · 감사 기록에 남았습니다.');
          } catch (error) {
            ui.toast(error.status === 403 ? (self ? '단독 검토 조건을 충족하지 않습니다. 다른 최고관리자의 승인이 필요합니다.' : '승인 권한이 없습니다.')
              : error.status === 409 ? '이미 처리됐거나 만료된 요청입니다. 목록을 새로 확인하세요.' : error.message, 'bad');
          }
          await refresh();
        };
        const cancel = async () => {
          const answer = await ui.confirmChange({title: '요청 철회', summary: '이 요청을 더 이상 적용할 수 없게 합니다.', confirmLabel: '철회', minimum: 5});
          if (!answer) return;
          try { await api.write(WAC + '/commands/' + encodeURIComponent(command.id) + '/cancel', {revision: command.revision, reason: answer.reason}); ui.toast('요청을 철회했습니다.'); }
          catch (error) { ui.toast(error.status === 409 ? '이미 처리된 요청입니다.' : error.message, 'bad'); }
          await refresh();
        };
        const actions = ui.el('div', {class: 'adm-actions'},
          pending && me.can_approve ? ui.el('button', {class: 'adm-btn danger', type: 'button', onclick: approve}, '검토 후 적용') : null,
          ['pending', 'expired'].includes(command.status) && (me.can_approve || self) ? ui.el('button', {class: 'adm-btn', type: 'button', onclick: cancel}, '요청 철회') : null);
        ui.fill(content, actions,
          pending && !me.can_approve ? ui.el('p', {class: 'adm-muted', text: '적용은 요청자와 다른 최고관리자가 합니다.'}) : null,
          ui.el('dl', {}, ...field('종류', KINDS[review.kind] || review.kind), ...field('고객', review.customer_id),
            ...field('상태', state(command)[1]), ...field('요청 사유', review.reason),
            ...(review.kind === 'credit_adjust' ? [...field('크레딧 증감', review.delta), ...field('크레딧 상태', review.credit_status)] : []),
            ...field('대상 버전', review.target_revision), ...field('요청자', command.requested_by + (self ? ' (나)' : '')),
            ...field('승인자', command.approved_by), ...field('요청 시각', when(command.created)), ...field('검토 기한', when(command.expires))));
      } catch (error) {
        if (error.status === 401) throw error;
        content.replaceChildren(ui.empty(error.message || '요청을 읽지 못했습니다.'));
      }
    };
    body.replaceChildren(
      ui.el('p', {class: 'adm-muted', text: '위험 작업은 요청 후 15분 안에 요청자와 다른 최고관리자가 검토해 적용합니다. 행을 누르면 내용을 확인합니다.'}),
      items.length ? ui.table([
        {label: '명령', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(state(row)[0]), ui.el('span', {text: KINDS[row.kind] || row.kind}))},
        {label: '상태', render: row => state(row)[1]}, {label: '고객', render: row => row.customer_id || '—'},
        {label: '요청', render: row => String(row.requested_by ?? '—') + (row.requested_by === me.staff_id ? ' (나)' : '')},
        {label: '승인', render: row => String(row.approved_by ?? '—')},
        {label: '요청 시각', render: row => when(row.created)}, {label: '검토 기한', render: left},
      ], items, {caption: '승인 명령', onSelect: open}) : ui.empty('승인 명령이 없습니다.'));
  },
  async events(body, ctx, read) {
    const {ui} = ctx;
    let items = [], cursor = null, loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const query = new URLSearchParams({limit: '50', hours: '24'});
        if (cursor) { query.set('before', String(cursor.before)); query.set('cursor', cursor.cursor); }
        const result = await read('/events?' + query);
        if (!ctx.isCurrent()) return;
        items = items.concat(result.data.events || []); cursor = result.data.next_cursor;
        ui.fill(body, ui.el('p', {class: 'adm-muted', text: '최근 24시간의 실제 기록입니다. 입력·출력·토큰은 표시하지 않습니다.'}),
          items.length ? ui.table([
            {label: '시각', render: item => when(item.occurred)}, {label: '이벤트', key: 'event_type'},
            {label: '고객', render: item => item.customer_id || '—'}, {label: '결과', key: 'outcome'},
            {label: '오류', render: item => item.error_code || '—'},
          ], items, {caption: 'AI·실행 이력', onSelect: item => item.operation_id ? openOperation(ctx, read, item.operation_id) : undefined}) : ui.empty('기록된 이력이 없습니다.'),
          cursor ? ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load().catch(error => ui.toast(error.message, 'bad'))}, '더 보기') : null);
      } finally { loading = false; }
    };
    await load();
  },
  async credits(body, ctx, read) {
    const {ui} = ctx;
    await pagedTable(body, ctx, read, '/credits/reconciliation?limit=25', 'accounts', [
      {label: '고객', render: row => row.customer_id || '—'},
      {label: '잔액', class: 'adm-num', render: row => ui.number(row.balance)},
      {label: '검증 기록', class: 'adm-num', render: row => ui.number(row.event_count)},
      {label: '대사 결과', render: row => {
        const states = {matched: ['ok', '일치'], mismatch: ['bad', '불일치'],
          incomplete: ['warn', '검증 범위 초과'], integrity_review_required: ['bad', '무결성 검토 필요']};
        const [tone, label] = states[row.status] || ['warn', '확인 불가'];
        return ui.el('span', {class: 'adm-badge'}, ui.pearl(tone), label);
      }},
    ], {empty: '정산할 크레딧 계정이 없습니다.', onSelect: row => openCustomer(ctx, read, {id:row.customer_id})});
  },
};

async function openCustomer(ctx, read, row) {
  const {ui} = ctx;
  const content = ui.el('div', {}, ui.skeleton(5));
  ui.drawer(row.id, content, row.active ? 'ok' : 'off');
  try {
    const [detail, timeline] = await Promise.all([read('/customers/' + encodeURIComponent(row.id), 'detail'),
      read('/customers/' + encodeURIComponent(row.id) + '/timeline?limit=30', 'detail')]);
    if (!ctx.isCurrent() || !content.isConnected) return;
    const data = detail.data || {}, events = timeline.data.events || [];
    const field = (label, value) => [ui.el('dt', {text: label}), ui.el('dd', {text: String(value ?? '—')})];
    const strand = ui.el('div', {class: 'adm-timeline adm-strand', 'aria-label': '최근 이벤트 ' + events.length + '건'},
      events.slice().reverse().map(item => ui.pearl(item.outcome === 'failed' ? 'bad' : item.outcome === 'unknown' ? 'warn' : 'ok', (item.event_type || '') + ' ' + when(item.occurred))));
    ui.fill(content, 
      ui.el('dl', {}, field('ID', data.customer?.id), field('로그인 방식', data.customer?.issuer), field('가입', when(data.customer?.created)),
        field('마지막 로그인', when(data.customer?.last_login)), field('활성 세션', data.active_sessions), field('소속 조직', (data.links || []).length + '곳'),
        field('크레딧', data.credits ? ui.number(data.credits.balance) : '—'), field('크레딧 계정 상태',data.credits?.status || '미가입')),
      ui.el('p', {class: 'adm-muted', text: '고객 비공개 내용(대화·실행 출력)은 이 화면에 표시하지 않습니다.'}),
      ui.el('h3', {text: '최근 이벤트'}), events.length ? strand : ui.empty('기록된 이벤트가 없습니다.'),
      events.length ? ui.table([{label: '시각', render: item => when(item.occurred)}, {label: '이벤트', key: 'event_type'}, {label: '결과', render: item => item.outcome || '—'},
        {label: '오류', render: item => item.error_code || '—'}], events.slice(0, 15)) : null);
    content.append(ui.el('h3',{text:'소속 작업공간·역할'}),(data.links || []).length ? ui.table([
      {label:'작업공간',key:'workspace_id'},{label:'역할',key:'role'},{label:'활성',render:item=>item.active?'활성':'중지'}
    ],data.links,{caption:'고객 작업공간 접근',onSelect:item=>openOrganization(ctx,read,{id:item.workspace_id})}) : ui.empty('연결된 작업공간이 없습니다.'));
    const older=ui.el('section'),olderStatus=ui.el('p',{role:'status'});let nextCursor=timeline.data.next_cursor,loadingHistory=false;
    const more=ui.el('button',{class:'adm-btn',type:'button',text:'이전 고객 이력',hidden:!nextCursor,onclick:async()=>{
      if(loadingHistory||!nextCursor)return;loadingHistory=true;more.disabled=true;
      try{
        const cursor=nextCursor;const result=await read('/customers/'+encodeURIComponent(row.id)+'/timeline?limit=30&before='+encodeURIComponent(cursor.before)+'&cursor='+encodeURIComponent(cursor.cursor),'sensitive');
        if(!ctx.isCurrent()||!content.isConnected)return;
        older.append(ui.table([{label:'시각',render:item=>when(item.occurred)},{label:'이벤트',key:'event_type'},{label:'결과',key:'outcome'},{label:'오류',key:'error_code'}],result.data.events || [],{caption:'이전 고객 이력'}));
        nextCursor=result.data.next_cursor;more.hidden=!nextCursor;
      }catch(error){if(content.isConnected)olderStatus.textContent=error.message;}
      finally{loadingHistory=false;more.disabled=false;}
    }});content.append(older,more,olderStatus);
    if (events.length) requestAnimationFrame(() => ui.stringPearls(strand, '.adm-pearl'));
    const options = (await read('/options', 'reference')).data || {};
    if (options.can_support && content.isConnected) content.append(ui.el('button',{class:'adm-btn',type:'button',text:'고객 대응 생성',onclick:()=>management.createCase(ctx,row.id)}),commandForm(ctx, data));
    if (content.isConnected) content.append(await management.creditHistory(ctx, row.id));
    if (content.isConnected) content.append(await disclosureSection(ctx, read, row.id, options));
  } catch (error) {
    if (error.status === 401) throw error;
    content.replaceChildren(ui.empty(error.message));
  }
}

// Materials the customer chose to share with support. Reading one is a scoped, audited superadmin action.
async function disclosureSection(ctx, read, customer, options) {
  const {ui, api} = ctx;
  const section = ui.el('details', {class: 'adm-card'}, ui.el('summary', {text: '고객 공유 자료'}));
  const items = ((await read('/customers/' + encodeURIComponent(customer) + '/disclosures', 'sensitive')).data || {}).disclosures || [];
  const now = Date.now() / 1000;
  const state = item => item.revoked ? ['off', '고객이 철회'] : item.expires <= now ? ['off', '만료'] : ['ok', '열람 가능 · ' + when(item.expires) + '까지'];
  if (!items.length) { section.append(ui.el('p', {class: 'adm-muted', text: '고객이 공유한 자료가 없습니다.'})); return section; }
  const viewer = ui.el('div', {'aria-live': 'polite'});
  section.append(ui.el('p', {class: 'adm-muted', text: '고객이 지원 케이스에서 허용한 초안 버전만 열 수 있습니다. 열람은 감사 기록에 남습니다.'}),
    ui.el('ul', {class: 'adm-reviews'}, items.map(item => {
      const [tone, label] = state(item), open = !item.revoked && item.expires > now;
      let armed = false;
      const button = open && options.can_approve ? ui.el('button', {class: 'adm-btn', type: 'button', onclick: async () => {
        // Two-step: the first press states what will be opened; the second opens it.
        if (!armed) { armed = true; button.textContent = '열람 확인(감사 기록)'; return; }
        button.disabled = true;
        try {
          const result = await api.write(WAC + '/disclosures/' + encodeURIComponent(item.id) + '/read', {confirm: 'READ'});
          const draft = result.draft || {};
          viewer.replaceChildren(ui.el('h3', {text: '공유 초안 · ' + (draft.name || item.object_id)}),
            ui.el('pre', {class: 'adm-message', text: JSON.stringify(draft.definition ?? draft, null, 2)}));
        } catch (error) { ui.toast(error.status === 403 ? '열람 권한이 없거나 공유가 끝났습니다.' : error.message, 'bad'); }
        finally { button.disabled = false; armed = false; button.textContent = '승인된 자료 열람'; }
      }}, '승인된 자료 열람') : null;
      return ui.el('li', {class: 'adm-switch'},
        ui.el('div', {}, ui.el('strong', {}, ui.pearl(tone), ' ', item.object_id), ui.el('small', {text: label + ' · 케이스 ' + item.case_id})),
        button || ui.el('small', {class: 'adm-muted', text: open ? '최고관리자만 열람' : ''}));
    })), viewer);
  return section;
}

// Management action request: a reviewed command another superadmin applies within 15 minutes.
function commandForm(ctx, data) {
  const {ui, api} = ctx;
  const credits = data.credits || null, customer = data.customer || {};
  const kind = ui.el('select', {'aria-label': '조치 종류'}, Object.entries(KINDS)
    .filter(([key]) => key !== 'credit_adjust' || credits).map(([key, text]) => ui.el('option', {value: key, text})));
  const delta = ui.el('input', {type: 'number', step: '1', min: '-1000000', max: '1000000', value: '0', 'aria-label': '크레딧 증감'});
  const status = ui.el('select', {'aria-label': '크레딧 상태'}, [['active', '사용 가능'], ['suspended', '일시 중지'], ['closed', '종료']].map(([value, text]) => ui.el('option', {value, text})));
  status.value = credits?.status || 'active';
  const reason = ui.el('textarea', {rows: '3', maxlength: '300', 'aria-label': '근거와 사유'});
  const confirm = ui.el('input', {type: 'checkbox', id: 'adm-command-confirm'});
  const note = ui.el('p', {class: 'adm-status', role: 'status', 'aria-live': 'polite'});
  const creditFields = ui.el('div', {class: 'adm-filters'}, delta, status);
  const sync = () => { creditFields.hidden = kind.value !== 'credit_adjust'; };
  kind.addEventListener('change', sync); sync();
  const submit = ui.el('button', {class: 'adm-btn primary', type: 'submit', text: '승인 대기 조치 등록'});
  const form = ui.el('form', {class: 'adm-case-form', novalidate: true},
    ui.el('p', {class: 'adm-muted', text: '등록한 조치는 바로 적용되지 않습니다. 15분 안에 다른 최고관리자가 승인 명령 탭에서 검토해 적용합니다.'}),
    ui.el('div', {class: 'adm-filters'}, kind), creditFields, reason,
    ui.el('p', {class: 'adm-check'}, confirm, ui.el('label', {for: 'adm-command-confirm', text: '이 고객·현재 상태·요청 내용을 확인했습니다.'})), note,
    ui.el('div', {class: 'adm-actions'}, submit));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const amount = Number(delta.value), text = reason.value.trim();
    if (text.length < 5) { note.textContent = '근거와 사유를 5자 이상 입력하세요.'; reason.focus(); return; }
    if (kind.value === 'credit_adjust' && (!Number.isInteger(amount) || amount === 0 && status.value === credits.status)) { note.textContent = '바꿀 크레딧 증감이나 상태를 입력하세요.'; delta.focus(); return; }
    if (!confirm.checked) { note.textContent = '확인 항목을 선택하세요.'; confirm.focus(); return; }
    submit.disabled = true;
    const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
    const credit = kind.value === 'credit_adjust';
    try {
      await api.write(WAC + '/commands', {customer_id: customer.id, kind: kind.value,
        target_revision: credit ? credits.revision : customer.revision, delta: credit ? amount : 0,
        credit_status: credit ? status.value : (credits?.status || 'active'), reason: text, request_id: id});
      ui.toast('승인 대기 조치를 등록했습니다. 승인 명령 탭에서 적용합니다.');
      form.replaceChildren(ui.el('p', {}, ui.el('a', {href: '#/customers/commands', text: '승인 명령 탭 열기'})));
    } catch (error) { note.textContent = error.message; submit.disabled = false; }
  });
  return ui.el('details', {class: 'adm-card'}, ui.el('summary', {text: '관리 조치 요청'}), form);
}

async function openOrganization(ctx, read, row) {
  const {ui} = ctx;
  const content = ui.el('div', {}, ui.skeleton(4));
  ui.drawer(row.name || row.id, content, row.active ? 'ok' : 'off');
  const result = await read('/organizations/' + encodeURIComponent(row.id) + '/operations', 'sensitive');
  if (!ctx.isCurrent() || !content.isConnected) return;
  const sections = [['drafts', '초안'], ['typed_flows', '워크플로'], ['executions', '개별 실행'],
    ['typed_executions', '워크플로 실행'], ['releases', '릴리스'], ['deployments', '배포']];
  content.replaceChildren(ui.el('p', {class: 'adm-muted', text: '비공개 입력과 출력은 숨기고 최근 메타데이터만 표시합니다.'}),
    ...sections.map(([key, title]) => ui.el('section', {class: 'adm-card'}, ui.el('h3', {text: title}),
      result.data[key]?.length ? ui.table([
        {label: '항목', render: item => item.name || item.id}, {label: '상태', render: item => item.status || (item.active === 0 ? '비활성' : '—')},
        {label:'버전',render:item=>item.revision ?? '—'}, {label:'배포 ID',render:item=>item.app_id || '—'}, {label: '시각', render: item => when(item.finished || item.created)},
      ], result.data[key], {caption: title}) : ui.empty('기록이 없습니다.'))),
    ui.el('a', {class: 'adm-btn', href: '#/customers/specialists'}, ui.icon('external'), '직원 멤버십으로 전문 관리 열기'));
}

async function openOperation(ctx, read, identity) {
  const {ui} = ctx;
  const content = ui.el('div', {}, ui.skeleton(4));
  ui.drawer(identity, content);
  const result = await read('/operations/' + encodeURIComponent(identity), 'sensitive');
  if (!ctx.isCurrent() || !content.isConnected) return;
  const data = result.data || {}, state = data.authoritative_state || {};
  content.replaceChildren(ui.el('h3', {text: '기록된 실행 상태'}),
    ui.el('p', {text: state.status || '현재 원본 실행 상태를 확인할 수 없습니다.'}),
    ui.el('p',{text:state.stale?'관측 상태가 오래되었습니다. 원본 상태를 다시 확인하세요.':'조회한 원본 업무 상태'}),
    (data.attempts || []).length ? ui.table([{label:'노드',key:'node_id'},{label:'시도 상태',key:'status'}],data.attempts,{caption:'개별 실행 시도'}) : null,
    data.events?.length ? ui.table([
      {label: '시각', render: item => when(item.occurred)}, {label: '이벤트', key: 'event_type'},
      {label: '결과', key: 'outcome'}, {label: '오류', render: item => item.error_code || '—'},
    ], data.events, {caption: '실행 이력'}) : ui.empty('이 ID로 연결된 이벤트가 없습니다.'),
    ui.el('p', {class: 'adm-muted', text: '결과 불명은 성공으로 간주하지 않습니다. 비공개 입력과 출력은 표시하지 않습니다.'}));
}

// Filters belong to the current individual staff session.
export function reset() {
  specialists.reset(); staffWorkspaces.reset();
  Object.assign(requestMemory, {kind: 'inquiries', status: '', q: ''}); Object.assign(memory, {tab: 'overview', q: ''}); }
