import {agentEvidence} from './insights.js';
// ② 카탈로그: v2 커서 목록(진주 상태), 상세, 사유가 남는 변경 작업. 필터는 영역을 옮겨도 기억한다.
const STATUS = {healthy: ['ok', '정상'], reachable: ['ok', '도달 가능'], failing: ['warn', '실패 반복'], down: ['bad', '중단'],
  retired: ['off', '폐기'], unknown: [undefined, '미확인'], quarantined: ['bad', '격리']};
const KINDS = [['', '전체 프로토콜'], ['a2a', 'A2A'], ['mcp', 'MCP'], ['x402', 'x402']];
const HEALTH = [['', '전체 상태'], ...Object.entries(STATUS).map(([key, [, label]]) => [key, label])];
const memory = {q: '', kind: '', status: '', pages: 1};

export async function render(main, ctx) {
  if (ctx.rest[0] === 'tools') return (await import('./catalog-tools.js')).render(main, ctx);
  const {ui, api, params} = ctx;
  const restorePages=params.has('q')&&params.get('q')!==memory.q?1:Math.min(memory.pages,10);
  if (params.has('q')) memory.q = params.get('q');
  const linkedId = /^[1-9][0-9]{0,17}$/.test(params.get('agent') || '') ? params.get('agent') : ctx.rest[0] === 'agents' && /^[1-9][0-9]{0,17}$/.test(ctx.rest[1] || '') ? ctx.rest[1] : null;
  const me = (ctx.bootstrap() || {}).me || {};
  const canChange = ['superadmin', 'admin'].includes(me.role),canOperate=['superadmin','admin','operator'].includes(me.role);
  const status = value => STATUS[value] || [undefined, value || '미확인'];
  const path = cursor => {
    const search = new URLSearchParams({limit: '50'});
    for (const key of ['q', 'kind', 'status']) if (memory[key]) search.set(key, memory[key]);
    if (cursor) search.set('cursor', String(cursor));
    return '/admin/api/v2/catalog/agents?' + search;
  };
  const results = ui.el('div', {'aria-live': 'polite'});
  const fresh = ui.el('span');
  let loaded = [], total = null, next = null, generation = 0;const pendingPages=new Set();

  async function act(agent, action) {
    const labels = {check: ['상태 다시 확인', '지금 이 에이전트의 상태를 한 번 확인합니다.', '외부 주소로 확인 요청 1회를 보냅니다.'],
      deactivate: ['비활성화', '이 에이전트를 추천·검색·실행 대상에서 뺍니다.', '다시 활성화할 수 있습니다.'],
      activate: ['활성화', '이 에이전트를 다시 대상에 넣고 상태 확인을 처음부터 시작합니다.', '확인 전까지 상태는 미확인입니다.']};
    const [label, summary, effect] = labels[action];
    const answer = await ui.confirmChange({title: label + ' · ' + (agent.name || '에이전트 ' + agent.id), summary, effect,
      confirmLabel: label, danger: action === 'deactivate'});
    if (!answer) return false;
    try {
      await api.write('/admin/api/v2/catalog/agents/' + agent.id + '/actions',
        {action, reason: answer.reason, ...(action === 'check' ? {} : {expected_active: Boolean(agent.active)})});
      ui.toast(label + ' 완료 · 감사 기록에 남았습니다.');
      return true;
    } catch (error) {
      ui.toast(error.message || '작업을 완료하지 못했습니다.', 'bad');
      return error.status === 409;
    }
  }

  async function openAgent(row) {
    const content = ui.el('div', {}, ui.skeleton(5));
    ui.drawer(row.name || '에이전트 ' + row.id, content, status(row.health_status)[0],()=>{if(ctx.isCurrent())window.history.replaceState(null,'','#/catalog'+(memory.q?'?q='+encodeURIComponent(memory.q):''));});
    const show = async force => {
      try {
        const {data} = await api.read('/admin/api/v2/catalog/agents/' + encodeURIComponent(row.id), {grade: 'detail', force, tags: ['catalog:agent:' + row.id, 'catalog:agents']});
        if(!ctx.isCurrent()||!content.isConnected)return;
        const agent = data.item || data.agent || {}, history = data.related?.health_checks || data.history || [];
        // Opened from a link (#/catalog?agent=ID), the drawer only knew the ID until now.
        const panel = content.closest('.adm-drawer');
        if (panel && agent.name) { panel.querySelector('h2').textContent = agent.name; panel.setAttribute('aria-label', agent.name); }
        const field = (label, value) => [ui.el('dt', {text: label}), ui.el('dd', {}, value instanceof Node ? value : String(value ?? '—'))];
        const recent = ui.el('div', {class: 'adm-timeline adm-strand', 'aria-label': '최근 상태 확인 ' + history.length + '건'},
          history.slice(0, 24).reverse().map(item => ui.pearl(['healthy', 'reachable'].includes(item.outcome) ? 'ok' : item.outcome === 'failing' ? 'warn' : 'bad',
            new Date(item.at * 1000).toLocaleString('ko-KR') + ' ' + (item.outcome || '') + ' ' + (item.status_code ?? ''))));
        const after = async changed => { if (changed) { await show(true); await load(true); } };
        // Daily summaries outlive raw checks: one pearl per day, toned by that day's success rate.
        const daily = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(1));
        api.read('/admin/api/v2/catalog/agents/' + encodeURIComponent(agent.id) + '/daily?days=30', {grade: 'detail', tags: ['catalog:agent:' + agent.id]}).then(({data}) => {
          if(!ctx.isCurrent()||!daily.isConnected)return;
          const days = (data && data.days) || [];
          if (!data || data.available === false) { daily.replaceChildren(ui.el('p', {class: 'adm-muted', text: '일별 요약이 아직 준비되지 않았습니다.'})); return; }
          if (!days.length) { daily.replaceChildren(ui.el('p', {class: 'adm-muted', text: '요약된 날이 없습니다.'})); return; }
          const tone = row => !row.checks ? undefined : row.ok / row.checks >= .95 ? 'ok' : row.ok / row.checks >= .6 ? 'warn' : 'bad';
          const strand = ui.el('div', {class: 'adm-timeline adm-strand', 'aria-label': '일별 상태 ' + days.length + '일'},
            days.map(row => ui.pearl(tone(row), row.day + ' 성공 ' + row.ok + '/' + row.checks + (row.latency_p95 != null ? ' · p95 ' + row.latency_p95 + 'ms' : ''))));
          const total = days.reduce((sum, row) => sum + row.checks, 0), ok = days.reduce((sum, row) => sum + row.ok, 0);
          daily.replaceChildren(strand, ui.el('p', {class: 'adm-muted adm-num', text: days.length + '일 · 성공률 ' + ui.percent(total ? ok / total : null) + ' · 확인 ' + ui.number(total) + '회'}));
          requestAnimationFrame(() => ui.stringPearls(strand, '.adm-pearl'));
        }).catch(error => { if (error.status !== 401) daily.replaceChildren(ui.el('p', {class: 'adm-muted', text: error.message})); });
        const actions = canOperate ? ui.el('div', {class: 'adm-actions'},
          ui.el('button', {class: 'adm-btn', type: 'button', onclick: async () => after(await act(agent, 'check'))}, ui.icon('refresh'), '상태 다시 확인'),
          canChange ? (agent.active ? ui.el('button', {class: 'adm-btn danger', type: 'button', onclick: async () => after(await act(agent, 'deactivate'))}, '비활성화')
                       : ui.el('button', {class: 'adm-btn primary', type: 'button', onclick: async () => after(await act(agent, 'activate'))}, '활성화')) : null)
          : ui.el('p', {class: 'adm-muted', text: '변경 작업은 관리자 이상 권한이 필요합니다.'});
        const metadata = ui.el('section',{class:'adm-card'}), facts=ui.el('div'),evidence=ui.el('div');
        const redact=(value,depth=0)=>{
          if(depth>6)return '[Depth limit]';
          if(Array.isArray(value))return value.slice(0,50).map(item=>redact(item,depth+1));
          if(value && typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,/secret|password|authorization|credential|access_token|refresh_token|private_key/i.test(key)?'[REDACTED]':redact(item,depth+1)]));
          return value;
        };
        const sections=[['연결 정보',agent.details],['검증 기록',agent.eval_info],['도구 안내',agent.usage_guide],['수집 출처',{source:agent.source,created_at:agent.created_at,updated_at:agent.updated_at}],['운영 메모',agent.notes || '이 원본에 기록된 메모가 없습니다.']];
        const tabs=ui.el('div',{class:'adm-tabs',role:'tablist','aria-label':'에이전트 상세 정보'});
        const showMeta=(index,update=true)=>{
          if(update)window.history.replaceState(null,'','#/catalog/agents/'+agent.id+'?tab='+['overview','evidence','tools','source','notes'][index]);
          evidence?.replaceChildren();
          facts.replaceChildren(ui.el('pre',{class:'adm-message',text:JSON.stringify(redact(sections[index][1] ?? {}),null,2)}));
          [...tabs.children].forEach((button,i)=>button.setAttribute('aria-selected',String(index===i)));
        };
        sections.forEach(([label],index)=>tabs.append(ui.el('button',{class:'adm-tab',type:'button',role:'tab',text:label,onclick:()=>showMeta(index)})));
        metadata.append(tabs,facts);showMeta(0,false);
        metadata.append(evidence);
        const requestedTab=['overview','evidence','tools','source','notes'].indexOf(params.get('tab'));if(requestedTab>=0)showMeta(requestedTab,false);
        if(!force)window.history.replaceState(null,'','#/catalog/agents/'+agent.id+'?tab='+encodeURIComponent(params.get('tab') || 'overview'));
        const callsTab=ui.el('button',{class:'adm-tab',type:'button',role:'tab',text:'호출·버전·증거·감사'});
        const showCalls=()=>{window.history.replaceState(null,'','#/catalog/agents/'+agent.id+'?tab=calls');facts.replaceChildren();[...tabs.children].forEach(b=>b.setAttribute('aria-selected',String(b===callsTab)));agentEvidence(evidence,ctx,agent.id);};
        callsTab.addEventListener('click',showCalls);tabs.append(callsTab);
        if(params.get('tab')==='calls')showCalls();
        if(me.role==='superadmin')metadata.append(ui.el('a',{class:'adm-btn',href:'#/catalog/tools?view=contract&agent='+encodeURIComponent(agent.id),text:'현재 연결 버전·계약·실행 증거 관리'}));
        content.replaceChildren(actions, metadata,
          ui.el('dl', {},
            field('ID', agent.id), field('프로토콜', (agent.kind || '').toUpperCase()), field('상태', status(agent.health_status)[1] + (agent.active ? '' : ' · 비활성')),
            field('등급', (agent.eval_grade || '평가 전') + (agent.eval_score != null ? ' · ' + agent.eval_score : '')),
            field('보안 판정', agent.eval_security || '—'), field('출처', agent.source), field('분류', agent.category),
            field('주소', agent.url), field('마지막 성공', agent.last_ok_at ? new Date(agent.last_ok_at * 1000).toLocaleString('ko-KR') : '—'),
            field('연속 실패', agent.consecutive_failures)),
          ui.el('h3', {text: '최근 상태 확인'}), history.length ? recent : ui.empty('상태 확인 기록이 없습니다.'),
          ui.el('h3', {text: '최근 30일 (일별 요약)'}), daily,
          ui.el('p', {}, ui.el('a', {class: 'adm-btn', href: '#/catalog/tools?agent=' + encodeURIComponent(agent.id)}, ui.icon('external'), '입력을 검토하고 테스트')));
        requestAnimationFrame(() => ui.stringPearls(recent, '.adm-pearl'));
      } catch (error) {
        if (error.status === 401) throw error;
        content.replaceChildren(ui.empty(error.message || '상세 정보를 읽지 못했습니다.'));
      }
    };
    await show(false);
  }

  const columns = [
    {label: '에이전트', render: row => ui.el('span', {class: 'adm-name'}, ui.pearl(status(row.health_status)[0], status(row.health_status)[1]), ui.el('span', {text: row.name || row.url || '이름 없음'}))},
    {label: '프로토콜', render: row => (row.kind || '').toUpperCase()},
    {label: '상태', render: row => ui.el('span', {class: 'adm-badge'}, ui.pearl(status(row.health_status)[0]), status(row.health_status)[1])},
    {label: '등급', render: row => row.eval_grade || '—'},
    {label: '24시간 확인', class: 'adm-num', render: row => row.health_n_24h ? row.health_ok_24h + '/' + row.health_n_24h : '—'},
    {label: '응답', class: 'adm-num', render: row => ui.ms(row.probe_latency_ms)},
    {label: '출처', render: row => row.source || '—'},
  ];
  const paint = at => {
    fresh.replaceChildren(ui.freshness(at, api.GRADES.list.stale));
    if (!loaded.length) { results.replaceChildren(ui.empty('조건에 맞는 에이전트가 없습니다.')); return; }
    const more = next ? ui.el('div', {class: 'adm-more'}, ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load(false, next)}, '50개 더 보기')) : null;
    ui.fill(results, 
      ui.el('p', {class: 'adm-muted adm-num', text: (total == null ? '' : ui.number(total) + '개 중 ') + ui.number(loaded.length) + '개 표시'}),
      ui.table(columns, loaded, {onSelect: openAgent, onPrefetch: row => api.prefetch('/admin/api/v2/catalog/agents/'+row.id+'/daily?days=30',{grade:'detail',tags:['catalog:agent:'+row.id]}), caption: '에이전트 목록'}), more);
  };

  async function load(force = false, cursor = null) {
    const target = path(cursor);if(pendingPages.has(target))return;
    const mine=++generation;pendingPages.add(target);results.setAttribute('aria-busy','true');
    try {
      const result = await api.read(target, {grade: 'list', force, tags: ['catalog:agents'], onFresh: fresh => {
        if (ctx.isCurrent() && mine === generation && !cursor) { loaded = fresh.data.items || []; total = fresh.data.total; next = fresh.data.next_cursor; paint(fresh.at); }
      }});
      if (!ctx.isCurrent() || mine !== generation) return;
      const data = result.data || {};
      memory.pages=cursor?memory.pages+1:1;
      loaded = cursor ? loaded.concat(data.items || []) : (data.items || []);
      if (!cursor) total = data.total;
      next = data.next_cursor;
      paint(result.at);
    } catch (error) {
      if (error.status === 401) throw error;
      if(ctx.isCurrent()&&mine===generation)ui.toast(error.message || '목록을 읽지 못했습니다.','bad');
    }finally{pendingPages.delete(target);if(ctx.isCurrent()&&mine===generation)results.setAttribute('aria-busy','false');}
  }

  const exportButton = canChange ? ui.el('button',{class:'adm-btn',type:'button',text:'CSV 내보내기 · 최대 200개',onclick:async()=>{exportButton.disabled=true;try{const url=new URL(path(null),location.origin);url.searchParams.set('limit',String(Math.min(loaded.length || 50,200)));url.searchParams.set('format','csv');await api.download(url.pathname+url.search,'agent-catalog-page.csv');}catch(error){ui.toast(error.message,'bad');}finally{exportButton.disabled=false;}}}) : null;
  const search = ui.el('input', {type: 'search', value: memory.q, maxlength: '120', 'aria-label': '이름·주소 검색', placeholder: '이름·주소 검색'});
  const select = (options, key, label) => {
    const node = ui.el('select', {'aria-label': label}, options.map(([value, text]) => ui.el('option', {value, text})));
    node.value = memory[key];
    node.addEventListener('change', () => { memory[key] = node.value;memory.pages=1; load(); });
    return node;
  };
  let typing = 0;
  search.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { memory.q = search.value.trim();memory.pages=1; load(); }, 350); });

  const overview = ((ctx.bootstrap() || {}).overview || {}).collector;
  const collector = canOperate && overview ? ui.el('button', {class: 'adm-btn' + (overview.paused ? ' primary' : ''), type: 'button', onclick: async () => {
    const action = overview.paused ? 'resume' : 'pause';
    const answer = await ui.confirmChange({title: action === 'pause' ? '수집기 일시정지' : '수집기 재개',
      summary: action === 'pause' ? '새 에이전트 수집과 상태 확인을 멈춥니다.' : '수집과 상태 확인을 다시 시작합니다.',
      effect: '언제든 반대로 되돌릴 수 있습니다.', confirmLabel: action === 'pause' ? '일시정지' : '재개', danger: action === 'pause'});
    if (!answer) return;
    try {
      await api.write('/admin/api/v2/catalog/collector/actions', {action, reason: answer.reason});
      ui.toast('수집기 '+(action==='pause'?'일시정지':'재개')+' 요청을 접수했습니다. 현재 상태를 다시 확인하세요.');
      await ctx.reloadBootstrap(true); await render(main, ctx);
    } catch (error) { ui.toast(error.message, 'bad'); }
  }}, overview.paused ? '수집기 재개' : '수집기 일시정지') : null;

  main.replaceChildren(
    ui.el('div', {class: 'adm-head'}, ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'Catalog'}), ui.el('h1', {text: '카탈로그 · 에이전트'})),
      ui.el('div', {class: 'adm-filters'}, fresh, collector)),
    ui.el('p', {class: 'adm-muted', text: '활성 에이전트를 최근 등록 순으로 보여 줍니다. 진주 테두리는 최근 상태입니다. 행을 누르면 상세와 변경 작업을 엽니다.'}),
    ui.el('div', {class: 'adm-filters'}, search, exportButton, select(KINDS, 'kind', '프로토콜'), select(HEALTH, 'status', '상태'),
      ui.el('a', {class: 'adm-btn', href: '#/catalog/tools?view=collector'}, ui.icon('external'), '수집 진행'),
      ui.el('a', {class: 'adm-btn', href: '#/catalog/tools?view=register'}, ui.icon('external'), '등록 심사'),
      ui.el('a', {class: 'adm-btn', href: '#/catalog/tools?view=reports'}, ui.icon('external'), '테스트 보고서')),
    results);
  results.replaceChildren(ui.skeleton(8));
  await load();
  for(let i=1;i<restorePages&&next&&ctx.isCurrent();i++)await load(false,next);
  if (ctx.isCurrent() && linkedId) await openAgent({id: linkedId});
}

// Filters belong to the current individual staff session.
export function reset() { Object.assign(memory, {q: '', kind: '', status: '', pages:1}); }
