import {homeWork} from './completion-view.js';
// ① 운영 홈: 서비스 흐름 목걸이, 경보, 핵심 지표.
export async function render(main, ctx) {
  const {ui, api} = ctx;
  let result;
  try{result = await api.read('/admin/api/v2/home/bootstrap', {grade:'live',tags:['home'],onFresh:()=>{if(ctx.isCurrent())render(main,ctx);}});}
  catch(error){if(error.status===401)throw error;if(!ctx.isCurrent())return;main.replaceChildren(ui.el('div',{class:'adm-head'},ui.el('h1',{text:ctx.screen?.title||'운영 요약'})),ui.el('section',{class:'adm-card'},ui.el('h2',{text:'운영 집계를 확인하지 못했습니다'}),ui.el('p',{text:error.message}),ui.el('button',{class:'adm-btn',type:'button',text:'집계 다시 확인',onclick:()=>render(main,ctx)}),ui.el('a',{class:'adm-btn',href:'#/home/h02',text:'처리할 일 확인'})));homeWork(main,ctx,{overview:{},gateway:{}});return;}
  if (!ctx.isCurrent()) return;
  const data = result.data || {}, overview = data.overview || {}, gateway = data.gateway || {};
  const catalog = overview.public_catalog || {}, health = overview.health || {};
  const grades = (overview.evaluation && overview.evaluation.grades) || [];
  const graded = grades.filter(row => ['A', 'B'].includes(row.grade)).reduce((sum, row) => sum + (row.n || 0), 0);
  const checkRate = health.checks_6h ? health.ok_6h / health.checks_6h : null;

  const refresh = ui.el('button', {class: 'adm-btn', type: 'button', onclick: async () => {
    refresh.disabled = true;
    try { await ctx.reloadBootstrap(true); await render(main, ctx); } finally { refresh.disabled = false; }
  }}, ui.icon('refresh'), '새로고침');
  const head = ui.el('div', {class: 'adm-head'},
    ui.el('div', {}, ui.el('p', {class: 'adm-eyebrow', text: 'Operations'}), ui.el('h1', {text: ctx.screen?.title||'운영 요약'})),
    ui.el('div', {class: 'adm-filters'}, ui.freshness(result.at, api.GRADES.live.stale), refresh));

  // Service flow necklace: collect, verify, evaluate, connect, deliver (design 12.5).
  const steps = [
    {area: 'catalog', label: '수집', value: ui.number(catalog.cataloged), note: '24시간 신규 ' + ui.number(catalog.new_24h),
     status: (health.overdue_6h || 0) > 1000 ? 'warn' : 'ok'},
    {area: 'catalog', label: '검증', value: ui.percent(checkRate), note: '6시간 상태 확인 ' + ui.number(health.checks_6h),
     status: checkRate === null ? undefined : checkRate < 0.6 ? 'warn' : 'ok'},
    {area: 'catalog', label: '평가', value: ui.number(graded), note: 'A·B 등급 에이전트', status: graded ? 'ok' : undefined},
    {area: 'gateway', label: '연결', value: ui.percent(gateway.success_rate), note: '24시간 실행 성공률',
     status: gateway.success_rate == null ? undefined : gateway.success_rate < 0.9 ? 'bad' : 'ok'},
    {area: 'gateway', label: '결과', value: ui.number(gateway.succeeded), note: '24시간 완료된 실행', status: gateway.succeeded ? 'ok' : undefined},
  ];
  const flow = ui.el('section', {class: 'adm-card adm-flow adm-strand', 'aria-label': '서비스 흐름'},
    steps.map(step => ui.el('button', {type: 'button', onclick: () => { if (data.me?.role !== 'viewer' || step.area === 'gateway') ctx.navigate('#/' + step.area); }, disabled: data.me?.role === 'viewer' && step.area === 'catalog', 'aria-label': step.label + ' ' + step.value + ', ' + step.note},
      ui.pearl(step.status), ui.el('strong', {class: 'adm-num', text: step.value}), ui.el('span', {text: step.label + ' · ' + step.note}))));
  flow.addEventListener('restring', () => ui.stringPearls(flow, '.adm-pearl'));

  const alerts = (data.alerts || []).length
    ? ui.el('ul', {class: 'adm-alerts', 'aria-label': '경보'}, data.alerts.map(alert => ui.el('li', {dataset: {level: alert.level}},
        ui.icon('alert'), ui.el('span', {text: alert.text}), ui.el('a', {href: '#/' + alert.area, text: '열기'}))))
    : ui.el('ul', {class: 'adm-alerts'}, ui.el('li', {dataset: {level: 'ok'}}, ui.icon('check'), ui.el('span', {text: '지금 확인할 경보가 없습니다.'})));

  const kpi = (label, value, note) => ui.el('div', {class: 'adm-card adm-kpi'}, ui.el('p', {class: 'adm-eyebrow', text: label}),
    ui.el('div', {class: 'adm-value adm-num', text: value}), ui.el('p', {text: note}));
  const kpis = ui.el('section', {class: 'adm-grid adm-kpis', 'aria-label': '핵심 지표'},
    kpi('기본 헬스체크 주기', ui.number((Number(health.interval) > 0 ? Number(health.interval) : 21600) / 3600) + '시간', '우선 대상 15분 재확인 · ±10% 분산'),
    kpi('등록 에이전트', ui.number(catalog.cataloged), '도달 가능 ' + ui.number(catalog.reachable) + ' (' + (catalog.reachable_share ?? '—') + '%)'),
    kpi('상태 확인 대기', ui.number(health.due_now), '예정 시각보다 6시간 지연 ' + ui.number(health.overdue_6h)),
    kpi('게이트웨이 p95', ui.ms(gateway.p95_ms), '24시간 실행 ' + ui.number(gateway.operations) + '건'),
    kpi('고객 요청', ui.number(Object.values(overview.needs || {}).reduce((a, b) => a + (b || 0), 0)), '상태별 합계'),
    kpi('수집기', overview.collector ? (overview.collector.paused ? '일시정지' : '동작 중') : '확인 불가', '저장소 ' + ((overview.storage || {}).backend || '확인 불가')));

  const protocols = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '프로토콜별 카탈로그'}),
    ui.el('ul', {class: 'adm-bars'}, (catalog.by_protocol || []).map(row => {
      const share = catalog.cataloged ? row.n / catalog.cataloged : 0;
      return ui.el('li', {}, ui.el('span', {text: row.label || row.kind}), ui.el('span', {class: 'adm-bar', 'aria-hidden': 'true'}, ui.el('i', {style: {width: (share * 100).toFixed(1) + '%'}})),
        ui.el('span', {class: 'adm-num', text: ui.number(row.n)}));
    })));
  const sources = ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '실행 경로 (24시간)'}),
    (gateway.by_source || []).length ? ui.el('ul', {class: 'adm-bars'}, gateway.by_source.slice(0, 6).map(row => {
      const rate = row.total ? row.succeeded / row.total : 0;
      return ui.el('li', {}, ui.el('span', {text: row.source}), ui.el('span', {class: 'adm-bar', dataset: {tone: rate < .9 ? 'bad' : undefined}, 'aria-hidden': 'true'}, ui.el('i', {style: {width: (rate * 100).toFixed(1) + '%'}})),
        ui.el('span', {class: 'adm-num', text: ui.percent(rate)}));
    })) : ui.empty(gateway.available === false ? '실행 관측을 확인할 수 없습니다.' : '최근 24시간 실행 기록이 없습니다.'));

  main.replaceChildren(head, flow, alerts, kpis, ui.el('div', {class: 'adm-grid adm-two'}, protocols, sources));
  homeWork(main,ctx,{overview,gateway});
  requestAnimationFrame(() => ui.stringPearls(flow, '.adm-pearl'));
}
