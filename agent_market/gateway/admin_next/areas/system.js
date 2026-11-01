import {storageEvidence} from './completion-view.js';
// ⑦ 시스템: 저장소 크기·행 수, DB 활동(전역 쓰기 잠금·느린 쿼리), 보존, 관리자 메뉴 연결.
export async function render(main, ctx) {
  if (ctx.rest[0] === 'accounts') return (await import('./admin-accounts.js')).render(main, ctx);
  const {ui, api} = ctx;
  const section=ctx.params.get('section')||'all',initial=[];
  const body = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(6));
  const fresh = ui.el('span');
  const paint = result => {
    const data = result.data || {};
    fresh.replaceChildren(ui.freshness(result.at, api.GRADES.reference.stale));
    if (!data.available) { body.replaceChildren(ui.empty('이 저장소에서는 테이블 통계를 제공하지 않습니다.')); return; }
    const activity = data.activity || {};
    const kpi = (label, value, note, tone) => ui.el('div', {class: 'adm-card adm-kpi'}, ui.el('p', {class: 'adm-eyebrow', text: label}),
      ui.el('div', {class: 'adm-value adm-num'}, tone ? ui.pearl(tone) : null, ' ', value), ui.el('p', {text: note}));
    const largest = (data.tables || [])[0]?.bytes || 1;
    body.replaceChildren(
      ui.el('section', {class: 'adm-grid adm-kpis'},
        kpi('데이터베이스', ui.bytes(data.database_bytes), '테이블 ' + ui.number(data.table_count) + '개'),
        kpi('잠금 대기', ui.number(activity.lock_waits), '지금 잠금을 기다리는 쿼리', activity.lock_waits ? 'warn' : 'ok'),
        kpi('느린 쿼리', ui.number(activity.slow_queries), '3초 넘게 실행 중', activity.slow_queries ? 'warn' : 'ok'),
        kpi('실행 중 세션', ui.number(activity.busy), 'idle 제외')),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '큰 테이블 (상위 40)'}),
        ui.el('p', {class: 'adm-muted', text: '보존 정책(설계서 6.1)의 대상입니다. 행 수는 PostgreSQL 통계 추정값입니다.'}),
        ui.table([
          {label: '테이블', key: 'name'},
          {label: '행 수(추정)', class: 'adm-num', render: row => ui.number(row.rows)},
          {label: '크기', class: 'adm-num', render: row => ui.bytes(row.bytes)},
          {label: '비중', render: row => ui.el('span', {class: 'adm-bar', 'aria-hidden': 'true'}, ui.el('i', {style: {width: (row.bytes / largest * 100).toFixed(1) + '%'}}))},
        ], data.tables || [], {caption: '테이블별 크기'})));
  };
  async function load(force = false) {
    const result = await api.read('/admin/api/v2/system/storage', {grade: 'reference', force, tags: ['system:storage'],
      onFresh: fresh => { if (ctx.isCurrent()) paint(fresh); }});
    if (ctx.isCurrent()) paint(result);
  }
  const refresh = ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load(true).catch(error => body.replaceChildren(ui.empty(error.message)))}, ui.icon('refresh'), '다시 측정');
  // Retention: how far back each growing table goes and how much it grew in 24 hours (design 6.1).
  const retention = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '보존 현황'}), ui.skeleton(4));
  const day = value => value ? new Date(value * 1000).toLocaleString('ko-KR', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
  const span = row => row.oldest && row.newest ? Math.max(0, (row.newest - row.oldest) / 86400).toFixed(1) + '일' : '—';
  // Daily summaries keep agent history once raw checks are shortened (design 6.1).
  const summaryNote = ui.el('p', {class: 'adm-muted'});
  if(section!=='storage')initial.push(api.read('/admin/api/v2/system/summaries', {grade: 'reference', tags: ['system:retention']}).then(({data}) => {
    const span = (data && data.health_daily) || {};
    summaryNote.textContent = data && data.available ? '상태 확인 일별 요약: ' + (span.oldest ? span.oldest + ' ~ ' + span.newest + ' · ' + ui.number(span.n) + '행' : '집계 중')
      : '상태 확인 일별 요약이 아직 준비되지 않았습니다(승인 저장소 마이그레이션 후 자동 집계).';
  }).catch(() => {summaryNote.textContent='일별 요약을 확인하지 못했습니다.';}));
  if(section!=='storage')initial.push(api.read('/admin/api/v2/system/retention', {grade: 'reference', tags: ['system:retention']}).then(result => {
    if (!ctx.isCurrent()) return;
    const data = result.data || {};
    retention.replaceChildren(ui.el('h2', {text: '보존 현황'}),
      ui.el('p', {class: 'adm-muted', text: '가장 오래된 기록과 최근 24시간 증가량입니다. 보존 기간을 정하는 근거로 씁니다(설계서 10장 3번).'}),
      summaryNote,
      data.available ? ui.table([
        {label: '테이블', key: 'table'}, {label: '가장 오래된 기록', render: row => day(row.oldest)},
        {label: '보관 기간', class: 'adm-num', render: span}, {label: '24시간 증가', class: 'adm-num', render: row => ui.number(row.last_24h)},
      ], data.tables || [], {caption: '보존 현황'}) : ui.empty('이 저장소에서는 보존 현황을 제공하지 않습니다.'));
  }).catch(error => { if (ctx.isCurrent()) retention.replaceChildren(ui.el('h2', {text: '보존 현황'}), ui.empty(error.message)); }));
  // Retention preview: what candidate periods would remove. Read only; deletion waits for the owner's decision.
  const preview = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '보존 기간 미리보기'}), ui.skeleton(3));
  if(section!=='storage')initial.push(api.read('/admin/api/v2/system/retention/preview', {grade: 'reference', tags: ['system:retention']}).then(result => {
    if (!ctx.isCurrent()) return;
    const data = result.data || {}, days = data.days || [];
    preview.replaceChildren(ui.el('h2', {text: '보존 기간 미리보기'}),
      ui.el('p', {class: 'adm-muted', text: '각 기간보다 오래된 행 수와 줄어드는 크기(추정)입니다. 아무것도 지우지 않습니다. 보존 기간이 정해지면 그 값으로 정리 작업을 켭니다.'}),
      data.available ? ui.table([{label: '대상', render: row => row.label + ' (' + row.table + ')'}, {label: '전체 행', class: 'adm-num', render: row => ui.number(row.rows)},
        ...days.map(d => ({label: d + '일 보존 시 삭제', class: 'adm-num', render: row => ui.number(row.remove[String(d)].rows) + ' · ' + ui.bytes(row.remove[String(d)].bytes)}))],
        data.tables || [], {caption: '보존 기간 미리보기'}) : ui.empty('이 저장소에서는 미리보기를 제공하지 않습니다.'));
  }).catch(error => { if (ctx.isCurrent()) preview.replaceChildren(ui.el('h2', {text: '보존 기간 미리보기'}), ui.empty(error.message)); }));
  // Live activity (superadmin): who holds the global writer lock and which statements run longest.
  const activity = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '데이터베이스 활동'}), ui.skeleton(3));
  const seconds = value => value == null ? '—' : value < 1 ? Math.round(value * 1000) + 'ms' : value.toFixed(1) + '초';
  async function loadActivity(force = false) {
    const head = ui.el('h2', {text: '데이터베이스 활동'});
    if (((ctx.bootstrap() || {}).me || {}).role !== 'superadmin') { activity.replaceChildren(head, ui.el('p', {class: 'adm-muted', text: '실행 중인 쿼리는 최고관리자만 볼 수 있습니다.'})); return; }
    try {
      const result = await api.read('/admin/api/v2/system/activity', {grade: 'live', force, tags: ['system:activity']});
      if (!ctx.isCurrent()) return;
      const data = result.data || {}, writer = data.writer || {};
      if (!data.available) { activity.replaceChildren(head, ui.empty('이 저장소에서는 활동 정보를 제공하지 않습니다.')); return; }
      const tone = writer.waiting ? 'warn' : 'ok';
      activity.replaceChildren(head,
        ui.el('div', {class: 'adm-filters'}, ui.freshness(result.at, api.GRADES.live.stale),
          ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => loadActivity(true)}, ui.icon('refresh'), '지금 다시 보기')),
        ui.el('p', {}, ui.pearl(tone), ' ', writer.held ? '전역 쓰기 잠금 사용 중 · ' + (writer.app || '앱 미상') + ' · ' + seconds(writer.held_seconds) : '전역 쓰기 잠금이 비어 있습니다.',
          writer.waiting ? ' · 대기 ' + writer.waiting + '건(최장 ' + seconds(writer.longest_wait_seconds) + ')' : ''),
        ui.el('p', {class: 'adm-muted', text: '잠금은 1초 안에 풀려야 합니다(Chat 503 교훈). 아래는 오래 실행 중인 쿼리 5개이며 값은 ?로 가렸습니다.'}),
        (data.slow || []).length ? ui.table([
          {label: '실행 시간', class: 'adm-num', render: row => seconds(row.seconds)},
          {label: '상태', render: row => row.state + (row.wait ? ' · ' + row.wait : '') + (row.blocked_by ? ' · 막힘 ' + row.blocked_by : '')},
          {label: '앱', render: row => row.app || '—'},
          {label: '쿼리 형태', render: row => ui.el('code', {text: row.statement || '—'})},
        ], data.slow, {caption: '오래 실행 중인 쿼리'}) : ui.el('p', {class: 'adm-muted', text: '실행 중인 쿼리가 없습니다.'}));
    } catch (error) { if (error.status === 401) throw error; if (ctx.isCurrent()) activity.replaceChildren(head, ui.empty(error.message)); }
  }
  if(section!=='retention')initial.push(loadActivity());
  // Retention policy: periods change only through a reviewed command; nothing is deleted by default.
  const policy = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '보존 기간 설정'}), ui.skeleton(3));
  async function loadPolicy() {
    const head = ui.el('h2', {text: '보존 기간 설정'});
    if (!['superadmin', 'admin'].includes(((ctx.bootstrap() || {}).me || {}).role)) { policy.replaceChildren(head, ui.el('p', {class: 'adm-muted', text: '보존 기간은 관리자 이상만 볼 수 있습니다.'})); return; }
    try {
      const {data} = await api.read('/admin/api/v2/system/retention/policy', {grade: 'detail', force: true, tags: ['reviews', 'system:retention']});
      if (!ctx.isCurrent()) return;
      if (!data.available) { policy.replaceChildren(head, ui.el('p', {class: 'adm-muted', text: '승인 저장소 마이그레이션 후 사용할 수 있습니다. 지금은 아무것도 자동으로 지우지 않습니다.'})); return; }
      const me = ((ctx.bootstrap() || {}).me || {}).role;
      const removed = (data.last || {}).removed || {};
      const rowsOf = Object.entries(data.tables || {}).map(([table, info]) => {
        const days = data.policy[table];
        const select = ui.el('select', {'aria-label': info.label + ' 보존 기간'},
          [ui.el('option', {value: '', text: '자동 정리 안 함'}), ...[3, 7, 14, 30, 90, 180, 365].filter(d => d >= info.minimum_days).map(d => ui.el('option', {value: String(d), text: d + '일'}))]);
        select.value = days == null ? '' : String(days);
        const request = ui.el('button', {class: 'adm-btn', type: 'button', disabled: me !== 'superadmin' || (!info.indexed && days == null), onclick: async () => {
          const next = select.value === '' ? null : Number(select.value);
          if (next === (days ?? null)) { ui.toast('현재 설정과 같습니다.'); return; }
          const answer = await ui.confirmChange({title: '보존 기간 변경 요청 · ' + info.label,
            summary: next == null ? '자동 정리를 멈춥니다.' : next + '일보다 오래된 ' + info.label + '을(를) 승인 후 계속 지웁니다.',
            effect: '승인 명령으로 등록되며, 15분 안에 다른 최고관리자가 적용해야 합니다. 지운 행은 되돌릴 수 없습니다.',
            confirmLabel: '승인 요청', danger: next != null, acknowledge: '검증된 최신 백업이 있음을 확인했습니다.'});
          if (!answer) return;
          try {
            await api.write('/admin/api/v2/system/retention/policy', {table, days: next, backup_confirmed: answer.acknowledged, reason: answer.reason});
            ui.toast('보존 기간 변경 요청을 만들었습니다. 게이트웨이 > 승인 대기에서 적용합니다.');
          } catch (error) { ui.toast(error.message, 'bad'); }
          await loadPolicy();
        }}, '변경 요청');
        return ui.el('div', {class: 'adm-switch'},
          ui.el('div', {}, ui.el('strong', {}, ui.pearl(days == null ? undefined : 'warn'), ' ', info.label + ' (' + table + ') · ' + (days == null ? '자동 정리 안 함' : days + '일 보존')),
            ui.el('small', {text: '최소 ' + info.minimum_days + '일' + (info.indexed ? '' : ' · 시간 인덱스 필요(운영자 명령 후 사용)')
              + (typeof removed[table] === 'number' ? ' · 마지막 정리 ' + ui.number(removed[table]) + '행' : '')})),
          ui.el('div', {class: 'adm-actions'}, select, request));
      });
      policy.replaceChildren(head, ui.el('p', {class: 'adm-muted', text: '변경은 승인 명령(2인 원칙)으로만 적용됩니다. 상태 확인 원본은 일별 요약이 끝난 날만 지웁니다.'}),
        ui.el('div', {class: 'adm-switches'}, rowsOf),
        ui.el('p', {class: 'adm-muted'}, ui.el('a', {href: '#/security/s01', text: '승인 대기 목록 열기'})));
    } catch (error) { if (error.status === 401) throw error; if (ctx.isCurrent()) policy.replaceChildren(head, ui.empty(error.message)); }
  }
  if(section!=='storage')initial.push(loadPolicy());
  const links = [ ['크레딧 정산', '#/customers/credits'], ['관리자 감사', '#/security/audit']];
  const sections=[['저장소',body],['DB 활동',activity],['보존 현황',retention],['정리 예상',preview],['보존 정책',policy]];
  for(const [,section] of sections){section.classList.add('adm-system-section');section.tabIndex=-1;}
  const navigation=ui.el('nav',{class:'adm-tabs adm-section-nav','aria-label':'시스템 화면 내 이동'},sections.map(([name,section])=>ui.el('button',{class:'adm-tab',type:'button',text:name,onclick:()=>{section.scrollIntoView({block:'start',behavior:'instant'});section.focus({preventScroll:true});}})));
  main.replaceChildren(
    ui.el('div', {class: 'adm-head'}, ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'System'}), ui.el('h1', {text: '시스템 · 저장소'})),
      ui.el('div', {class: 'adm-filters'}, fresh, refresh)),
    navigation, body, activity, retention, preview, policy,
    ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '시스템 관리'}), ui.el('a',{class:'adm-btn',href:'#/system/accounts',text:'관리자 계정·역할'}), ui.el('a',{class:'adm-btn',href:'#/catalog/tools?view=credentials',text:'자격증명 관리'}),
      ui.el('div', {class: 'adm-filters'}, links.map(([label, href]) => ui.el('a', {class: 'adm-btn', href, text: label})))));
  if(section==='storage'){
    for(const node of [navigation,retention,preview,policy])node.hidden=true;
  }else if(section==='retention'){
    for(const node of [navigation,body,activity])node.hidden=true;
  }
  if(section!=='retention')storageEvidence(main,ctx);
  if(section==='retention'&&ctx.bootstrap()?.me?.role==='superadmin'){
    const logs=ui.el('section',{class:'adm-card'}),level=ui.el('select',{'aria-label':'로그 수준'},['WARNING','ERROR','CRITICAL','ALL'].map(value=>ui.el('option',{value,text:({WARNING:'경고',ERROR:'오류',CRITICAL:'치명적 오류',ALL:'전체'}[value])}))),entries=ui.el('div');
    const readLogs=async()=>{entries.setAttribute('aria-busy','true');try{const {data}=await api.read('/admin/api/v2/console/logs?'+new URLSearchParams({level:level.value,limit:'50'}),{grade:'sensitive',force:true});if(!ctx.isCurrent())return;entries.replaceChildren(ui.el('p',{class:'adm-muted',text:data.scope}),ui.table([{label:'시각',render:r=>new Date(r.at*1000).toLocaleString('ko-KR')},{label:'수준',key:'level'},{label:'구분',key:'logger'},{label:'내용',key:'message'}],data.items||[],{caption:'최근 운영 로그 · 최대 50개'}));}catch(error){if(ctx.isCurrent())entries.replaceChildren(ui.empty(error.message));}finally{entries.removeAttribute('aria-busy');}};
    level.onchange=readLogs;logs.append(ui.el('h2',{text:'최근 운영 로그'}),level,entries);main.append(logs);await readLogs();
  }
  if(section!=='retention')initial.push(load().catch(error => { if (error.status === 401) throw error; body.replaceChildren(ui.empty(error.message)); }));
  await Promise.all(initial);
}
