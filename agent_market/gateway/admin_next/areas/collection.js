// Index progress must describe the worker's result, not merely a live thread.
export function indexMessage(data,index){
 const worker=data.worker,state=worker?.vector_index;
 if(worker?.available!==true)return '색인 작업자의 현재 응답을 확인하지 못했습니다. 저장된 대기 건수를 표시합니다.';
 if(worker.paused)return '자동 색인이 일시 정지되어 있습니다. 대기 데이터는 아직 처리되지 않았습니다.';
 if(state?.enabled===false||state?.state==='disabled')return '임베딩 생성이 꺼져 있어 자동 색인이 중지되었습니다. 작업자 연결 상태와는 별개입니다.';
 if(state?.state==='error'||state?.last_failed>0)return '최근 색인 처리에 오류가 있습니다. 대기 건수와 마지막 처리 결과를 확인하세요.';
 if(state?.state==='running')return '색인 작업자가 데이터를 처리 중입니다. 완료 건수는 처리 결과를 확인한 뒤 반영됩니다.';
 if(index.outbox_count===0)return '기록된 반영 대기가 없습니다.';
 if(['outbox','backfill'].includes(state?.state)&&state.last_count>0)return '최근 '+state.last_count+'건의 색인을 완료했습니다. 남은 변경 데이터가 대기 중입니다.';
 return '대기 데이터가 있지만 실제 색인 진행은 아직 확인되지 않았습니다. 대기 건수가 줄어드는지 확인하세요.';
}
import {page,button,load,metrics,table,date,details} from '../core/task-ui.js';
import {screenHref} from '../core/screens.js';
// Read-only status loads on entry; collecting or rechecking requires its own reviewed command.
export async function render(main,ctx){
 const {ui,api}=ctx,view=ctx.rest[0]||'overview',shell=page(main,ctx),{body,actions,note}=shell;
 const path='/admin/api/v2/console/'+({overview:'collection',actions:'collection',health:'health',evaluations:'evaluations','search-index':'search-index'}[view]||'collection');
 let uncertain=false;
 const read=async()=>{const r=await api.read(path,{grade:'sensitive',force:true});return r.data;};
 const refresh=()=>load(ctx,body,read,paint);
 actions.append(button(ctx,'상태 새로 확인',refresh));
 async function command(kind,b,payload={}){
  if(uncertain)return;const answer=await ui.confirmChange({title:kind==='crawl'?'에이전트 수집 시작':'고객 추천 요청 재평가',summary:kind==='crawl'?(payload.force_full?'모든 등록 정보를 다시 가져옵니다.':'마지막 수집 이후 변경된 정보를 가져옵니다.'):'활성 고객 추천 요청을 다시 평가해 제안을 갱신합니다. 수집 대상 에이전트를 재검색하는 작업이 아닙니다.',effect:kind==='crawl'?'수집 요청을 접수한 뒤 작업자가 처리합니다. 이미 관리 중인 에이전트는 제공자의 누락만으로 삭제하지 않습니다.':'추천 결과에 따라 새 제안·갱신이 생길 수 있으며, 기존 알림 동의와 전달 조건을 만족하면 알림이 전송될 수 있습니다.',confirmLabel:kind==='crawl'?'수집 요청':'재평가 요청'});if(!answer||!ctx.isCurrent())return;
  try{const value=await api.write('/admin/api/v2/catalog-tools/actions/'+kind+(kind==='crawl'?'?force_full='+Boolean(payload.force_full):''),{},{reason:answer.reason});if(!ctx.isCurrent())return;note.textContent=value.started===false?(value.reason||'이미 실행 중인 작업을 확인하세요.'):'요청을 접수했습니다. 아래 작업 상태에서 실제 진행과 완료를 확인하세요.';await refresh();}
  catch(e){uncertain=true;b.dataset.uncertain='true';note.textContent='접수 여부를 확인하지 못했습니다. 다시 전송하지 않고 작업 상태부터 확인하세요. '+e.message;}
 }
 function paint(d){
  body.replaceChildren();
  if(view==='health'){
   const sums=d.totals||[],active=sums.reduce((n,r)=>n+r.n,0),healthy=sums.filter(r=>['healthy','reachable'].includes(r.status)).reduce((n,r)=>n+r.n,0);
   body.append(metrics(ctx,[['활성 에이전트',ui.number(active),'현재 관리 대상'],['정상·도달 가능',ui.number(healthy),'기록된 최근 상태'],['기본 점검 주기',ui.number(d.interval_seconds/3600)+'시간','설정된 주기'],['수집 작업자',workerName(d.worker),'최근 연결 신호 기준']]),table(ctx,[{label:'에이전트',render:r=>ui.el('a',{href:screenHref('A02',{agent:r.id}),text:r.name})},{label:'프로토콜',key:'kind'},{label:'현재 상태',render:r=>ui.label(r.health_status)},{label:'마지막 점검',render:r=>date(r.last_check_at)},{label:'다음 예정',render:r=>date(r.next_check_at)}],d.items||[],{caption:'다음 점검 대상 · 최대 50개',empty:'점검할 활성 에이전트가 없습니다.',action:ui.el('a',{class:'adm-btn',href:screenHref('A01'),text:'에이전트 관리'})}));return;
  }
  if(view==='evaluations'){
   const totals=d.totals||[];body.append(metrics(ctx,[['평가 완료',ui.number(totals.filter(r=>r.grade!=='unrated').reduce((n,r)=>n+r.n,0)),'등급이 기록된 활성 에이전트'],['평가 등급 없음',ui.number(totals.filter(r=>r.grade==='unrated').reduce((n,r)=>n+r.n,0)),'미평가 또는 등급 미확정'],['작업자 연결',workerName(d.worker),'마지막 응답 기준']]),table(ctx,[{label:'에이전트',render:r=>ui.el('a',{href:screenHref('A02',{agent:r.id}),text:r.name})},{label:'프로토콜',key:'kind'},{label:'등급',render:r=>r.eval_grade||'평가 전'},{label:'점수',render:r=>r.eval_score==null?'확인 불가':ui.number(r.eval_score)},{label:'평가 시각',render:r=>date(r.eval_at)},{label:'테스트',render:r=>ui.el('a',{class:'adm-btn',href:screenHref('A03',{agent:r.id}),text:'테스트 검토'})}],d.items||[],{caption:'최근 평가 · 최대 50개',empty:'평가 대상 에이전트가 없습니다.'}));return;
  }
  if(view==='search-index'){
   const index=d.index||{};if(index.available===false){body.append(ui.empty('검색 데이터 준비 상태를 확인하지 못했습니다. 다른 업무는 계속 사용할 수 있습니다.',button(ctx,'다시 확인',refresh)));return;}
   body.append(metrics(ctx,[['검색 반영',ui.number(index.vector_count??index.indexed_count),'현재 사용 중인 검색 모델 기준'],['반영 대기',ui.number(index.outbox_count),'실제 대기 기록'],['대상 에이전트',ui.number(index.active_count),'현재 관리 대상'],['반영률',index.pct==null?'확인 불가':Number(index.pct).toFixed(1)+'%','관측 가능한 범위에서 계산']]),ui.el('section',{class:'adm-card'},ui.el('h2',{text:'검색 준비 상태'}),ui.el('p',{text:indexMessage(d,index)}),ui.el('p',{class:'adm-muted',text:d.worker?.vector_index?.last_success_at?'최근 실제 색인 완료 '+date(d.worker.vector_index.last_success_at):'최근 실제 색인 완료 시각은 작업자 상태에서 확인되지 않았습니다.'}),ui.el('a',{class:'adm-btn',href:screenHref('C02'),text:'자동 작업 상태 보기'})));return;
  }
  const worker=d.worker,connected=worker?.available===true,progress=d.progress||{},runs=d.runs||[],jobs=d.actions||{};
  const latest=new Map();for(const row of runs)if(!latest.has(row.source))latest.set(row.source,row);
  const providers=[...new Set([...Object.keys(progress),...latest.keys()])].map(source=>{const p=progress[source],r=latest.get(source);return {source,progress:p,last:r,state:p?(connected?(worker.paused?'일시 정지':jobs.crawl?.state==='queued'?'처리 대기':'진행 기록 있음'):'작업자 연결 확인 필요'):r?(r.ok?'최근 수집 완료':'최근 수집 실패'):'수집 전'};});
  body.append(metrics(ctx,[['수집 작업자',workerName(worker),worker?.updated?'마지막 확인 '+date(worker.updated):'현재 상태 확인'],['진행 정보',ui.number(Object.keys(progress).length)+'곳','저장된 제공자별 진행'],['최근 신규 등록',ui.number(runs.reduce((n,r)=>n+(r.new||0),0)),'아래 최근 '+runs.length+'회 수집 기록의 합계'],['최근 실패',ui.number(runs.filter(r=>!r.ok).length)+'회','아래 최근 수집 기록 기준']]));
  if(!connected)body.append(ui.el('p',{class:'adm-inline-status',text:worker?'수집 작업자의 최근 응답을 확인하지 못했습니다. 마지막 수집 결과는 아래에서 확인할 수 있습니다.':'연결된 수집 작업자가 없습니다. 현재 저장된 수집 기록을 표시합니다.'}));
  const launch=button(ctx,'변경된 에이전트 수집',b=>command('crawl',b),{primary:true}),full=button(ctx,'전체 정보 다시 수집',b=>command('crawl',b,{force_full:true}));
  if(ctx.bootstrap()?.me?.role==='superadmin'){
   launch.disabled=!d.crawl_available||uncertain;full.disabled=launch.disabled;actions.replaceChildren(button(ctx,'상태 새로 확인',refresh),launch);
   const rescan=button(ctx,'고객 추천 요청 재평가',b=>command('rescan',b));rescan.disabled=!d.rescan_available||uncertain;
   if(view==='actions')body.append(rescan,ui.el('section',{class:'adm-card'},ui.el('h2',{text:'수집 실행'}),ui.el('p',{text:'기본 수집은 변경분을 가져옵니다. 전체 다시 수집은 기존 정보를 모두 확인할 때 사용하세요.'}),full));
  }
  body.append(table(ctx,[{label:'제공자',key:'source'},{label:'상태',key:'state'},{label:'확인한 항목',render:r=>ui.number(r.progress?.seen??r.last?.seen)},{label:'새로 등록',render:r=>ui.number(r.progress?.new??r.last?.new)},{label:'변경 반영',render:r=>ui.number(r.progress?.changed??r.last?.changed)},{label:'최근 완료',render:r=>date(r.last?.at)}],providers,{caption:'제공자별 수집 상태',empty:'아직 수집 기록이 없습니다. 작업자 연결을 확인한 뒤 변경된 에이전트 수집을 시작하세요.',onSelect:r=>details(ctx,r.source+' 수집 기록',{진행:r.progress,최근결과:r.last})}));
  const requests=Object.entries(jobs).map(([kind,v])=>({kind,...v}));
  body.append(ui.el('h2',{text:'최근 요청한 작업'}),table(ctx,[{label:'작업',render:r=>({crawl:'에이전트 수집',rescan:'고객 추천 요청 재평가',pause:'일시 정지',resume:'재개'}[r.kind]||r.kind)},{label:'상태',render:r=>ui.label(r.state||(r.running?'running':r.error?'failed':'completed'))},{label:'접수',render:r=>date(r.started_at)},{label:'완료',render:r=>date(r.finished_at)},{label:'요청 참조',key:'command_id'}],requests,{caption:'접수·처리 상태',empty:'아직 이 화면에서 확인할 수 있는 수집 요청이 없습니다.'}));
  body.append(ui.el('h2',{text:'최근 수집 결과'}),table(ctx,[{label:'완료 시각',render:r=>date(r.at)},{label:'제공자',key:'source'},{label:'결과',render:r=>r.ok?'완료':'실패'},{label:'신규',key:'new'},{label:'변경',key:'changed'},{label:'소요 시간',render:r=>r.seconds==null?'확인 불가':Number(r.seconds).toFixed(1)+'초'}],runs,{caption:'최근 30회 수집 결과',empty:'완료된 수집 기록이 없습니다.',onSelect:r=>details(ctx,r.source+' 수집 결과',r)}));
  if(view==='actions'){
   body.append(ui.el('section',{class:'adm-card'},ui.el('h2',{text:'현재 자동 수집 설정'}),Object.keys(d.schedule||{}).length?ui.dataView(d.schedule):ui.el('p',{text:'자동 수집은 독립 작업자의 설정을 사용합니다. 웹 화면에서 작업자 설정을 임의로 바꾸지 않습니다.'})));
   if(ctx.bootstrap()?.me?.role==='superadmin')body.append(button(ctx,worker?.paused?'자동 수집 재개':'자동 수집 일시 정지',async()=>{const action=worker?.paused?'resume':'pause',answer=await ui.confirmChange({title:action==='pause'?'자동 수집 일시 정지':'자동 수집 재개',summary:'독립 수집 작업자의 새 작업 처리를 변경합니다.',confirmLabel:'변경 요청'});if(!answer)return;await api.write('/admin/api/v2/catalog/collector/actions',{action,reason:answer.reason});await refresh();}));
  }
 }
 await refresh();
}
function workerName(w){return w?.available===true?(w.paused?'일시 정지':'연결됨'):w?'응답 확인 필요':'연결 안 됨';}
