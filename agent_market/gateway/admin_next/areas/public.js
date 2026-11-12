// Public-service operations use aggregate projections, never cached contact records.
import * as operations from './public-operations.js';
export async function render(main, ctx) {
  if (ctx.rest[0]) return operations.render(main,ctx,ctx.rest[0]);
  const {ui, api} = ctx;
  const body = ui.el('div', {'aria-live': 'polite'}, ui.skeleton(5));
  const paint = result => {
    const data = result.data || {}, v = data.visitors || {}, requests = data.requests || {};
    const card = (title, value, note) => ui.el('section', {class: 'adm-card adm-kpi'},
      ui.el('p', {class: 'adm-eyebrow', text: title}), ui.el('div', {class: 'adm-value adm-num', text: ui.number(value)}),
      ui.el('p', {text: note}));
    body.replaceChildren(
      ui.freshness(data.captured_at * 1000 || result.at, api.GRADES.list.stale),
      ui.el('div', {class: 'adm-grid adm-kpis'},
        card('방문 에이전트', v.total, '24시간 활동 ' + ui.number(v.active_24h) + ' · 내부 측정 ' + ui.number(v.internal?.total) + '명 별도'),
        card('검증 연락처', v.verified_contacts, '등록과 광고 동의는 별개입니다.'),
        card('작업 알림', v.active_task_watches, '인증 대기 ' + ui.number(v.pending_task_watches)),
        card('지원 문의', requests.inquiries?.pending, '처리 중 ' + ui.number(requests.inquiries?.in_progress))),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '공개 워크플로 템플릿'}),
        ui.el('p', {class: 'adm-muted', text: '활성 템플릿 ' + ui.number(data.template_total) + '개 · 최대 50개 미리보기'}),
        data.templates?.length ? ui.table([
          {label: '템플릿', key: 'name'}, {label: '분류', key: 'category'},
          {label: '실행', render: row => ui.number(row.runs_count)},
        ], data.templates, {caption: '공개 템플릿'}) : ui.empty('활성 공개 템플릿이 없습니다.')),
      ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '서비스 운영 연결'}),
        ui.el('p', {text: '목적별 동의·주소 검증을 유지하고 게시·보안 완화·단건 알림은 승인 후 적용합니다. 광고 발송은 비활성 상태입니다.'}),
        ui.el('div', {class: 'adm-filters'}, [
          ['방문 에이전트·연락 동의', '#/public/visitors'], ['알림 설정·이력', '#/public/notifications'],
          ['SNS 운영', '#/public/sns'], ['템플릿 편집·게시', '#/public/templates'],
          ['공개 화면 미리보기', '#/public/p06'],
        ].filter(([,href]) => href==='#/public/p06' || ['admin','superadmin'].includes(ctx.bootstrap()?.me?.role)).map(([text, href]) => ui.el('a', {class: 'adm-btn', href}, ui.icon('external'), text)))));
  };
  async function load(force = false) {
    try {
      const result = await api.read('/admin/api/v2/public/summary', {grade: 'list', tags: ['public'], force,
        onFresh: value => { if (ctx.isCurrent()) paint(value); }});
      if (ctx.isCurrent()) paint(result);
    } catch (error) {
      if (error.status === 401) throw error;
      if (ctx.isCurrent()) body.replaceChildren(ui.empty(error.message));
    }
  }
  main.replaceChildren(ui.el('div', {class: 'adm-head'}, ui.el('h1', {text: '공개 서비스'}),
    ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => load(true)}, ui.icon('refresh'), '새로 읽기')), body);
  await load();
}
