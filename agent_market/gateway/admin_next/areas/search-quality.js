import {page,button,metrics,table,date,load} from '../core/task-ui.js';
const LABELS={explore:'탐색',recommendation:'Agent 추천',workflow_generation:'Workflow 생성'};
export async function render(main,ctx){
 const {ui,api}=ctx,{body,actions}=page(main,ctx);
 const refresh=()=>load(ctx,body,()=>api.read('/admin/api/v2/public/search-quality',{grade:'sensitive',force:true,tags:['public:quality']}).then(value=>value.data),paint);
 actions.append(button(ctx,'현재 지표 조회',refresh));
 function paint(data){
  if(!data.available){body.replaceChildren(ui.empty('품질 관측이 아직 없습니다. 검색·생성 요청 후 다시 조회하세요.'));return;}
  const rows=data.rows,requests=rows.reduce((n,r)=>n+r.requests,0),errors=rows.reduce((n,r)=>n+r.statuses.error+r.statuses.denied,0),repairs=rows.reduce((n,r)=>n+(r.counters.local_query_repairs||0),0);
  body.replaceChildren(metrics(ctx,[['관측 요청',ui.number(requests),'현재 프로세스 세대의 누적 요청'],['오류·권한 거부',ui.number(errors),'정상 0건 검색과 별도 집계'],['목적 보정',ui.number(repairs),'원래 목적의 검색문만 제한적으로 보정']]),
   ui.el('p',{class:'adm-inline-status',text:'API 내부 처리시간은 경로별 최근 최대 2,048건 표본입니다. 네트워크를 포함한 전체 응답 SLA와 구분합니다. 프로세스 재시작 시 새 세대로 집계하며, 다른 서비스의 저장 지표는 최대 30초 간격의 관측입니다.'}),
   table(ctx,[{label:'서비스',render:r=>r.role},{label:'화면',render:r=>LABELS[r.surface]},{label:'요청',render:r=>ui.number(r.requests)},
    {label:'p50',render:r=>r.p50_ms==null?'기록 없음':r.p50_ms.toFixed(1)+' ms'},
    {label:'p95',render:r=>r.p95_ms==null?'기록 없음':r.p95_ms.toFixed(1)+' ms'},
    {label:'표본',render:r=>ui.number(r.sample_count)},{label:'검색 0건',render:r=>ui.number(r.statuses.no_match)},
    {label:'추가 정보 필요',render:r=>ui.number(r.statuses.needs_details)},{label:'관측 시각',render:r=>date(r.captured_at)}],rows),
   ui.el('h2',{text:'검색 처리 경로'}),table(ctx,[{label:'서비스·화면',render:r=>r.role+' · '+LABELS[r.surface]},
    {label:'정확한 이름 빠른 조회',render:r=>ui.number(r.counters.exact_shortcuts||0)},
    {label:'Projection 캐시 적중',render:r=>ui.number(r.counters.projection_cache_hits||0)},
    {label:'재정렬 후보',render:r=>ui.number(r.counters.reranked_candidates||0)},
    {label:'순서 차이 관측',render:r=>ui.number(r.counters.rerank_order_changed||0)},
    {label:'예산 초과 시 원래 순서 유지',render:r=>ui.number(r.counters.rerank_budget_exhausted||0)}],rows));
 }
 await refresh();
}
