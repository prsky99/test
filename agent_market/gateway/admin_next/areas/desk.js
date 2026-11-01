import {page,button,load,metrics,table,date,details,errorView} from '../core/task-ui.js';
import {screenHref} from '../core/screens.js';
export async function render(main,ctx){
 const {ui,api}=ctx,{body,actions,note}=page(main,ctx),view=ctx.rest[0]||'tasks';
 const read=async path=>(await api.read(path,{grade:'sensitive',force:true})).data;
 if(view==='approvals'||view==='reviews'){
  const global=ui.el('section',{class:'adm-card'},ui.el('h2',{text:'서비스 변경 승인'})),customer=ui.el('section',{class:'adm-card'},ui.el('h2',{text:'고객 변경 승인'}));body.append(global,customer);
  const m=await import('./gateway.js');await m.paintReviews(global,ctx,()=>render(main,ctx));
  if(ctx.bootstrap()?.me?.role!=='viewer'){const m=await import('./customers.js');await m.render(customer,{...ctx,rest:['commands']});for(const h of customer.querySelectorAll('h1'))h.replaceWith(ui.el('h2',{text:'고객 변경 승인'}));}
  return;
 }
 if(view==='services'||view==='settings'||view==='content'){
  const path=view==='settings'?'/admin/api/v2/console/settings':'/admin/api/v2/console/services';
  const refresh=()=>load(ctx,body,()=>read(path),d=>{
   if(view==='content'){
    let base;try{base=new URL(d.public_origin||'https://agentconcierge.biz');if(!['http:','https:'].includes(base.protocol))throw Error();}catch{base=new URL('https://agentconcierge.biz');}
    const entries=[['홈','#overview'],['배우기','#learn'],['탐색','#explore'],['테스트','#test'],['워크플로','#workflow'],['채팅','#chat'],['에이전트 등록','#register'],['워크스페이스','/customer/organizations'],['개인정보 안내','#privacy'],['이용약관','#tos']];
    body.replaceChildren(table(ctx,[{label:'페이지',render:r=>r[0]},{label:'확인',render:r=>ui.el('a',{class:'adm-btn',href:new URL(r[1],base).href,target:'_blank',rel:'noopener',text:'공개 화면 열기'})}],entries,{caption:'서비스 화면 미리보기'}),ui.el('a',{class:'adm-btn',href:screenHref('P05'),text:'공개 템플릿 편집'}));return;
   }
   if(view==='settings'){body.replaceChildren(table(ctx,[{label:'설정',key:'name'},{label:'현재 값',render:r=>r.value??'설정 확인 필요'},{label:'적용 범위',key:'scope'},{label:'반영 방식',key:'change'}],d.items||[],{caption:'현재 서비스 설정'}),ui.el('h2',{text:'현재 변경 가능한 실행 제어'}));const control=ui.el('section',{class:'adm-card'});body.append(control);import('./gateway.js').then(m=>{if(ctx.isCurrent())m.paintControls(control,ctx);});return;}
   body.replaceChildren(metrics(ctx,[['어드민 연결','응답 중','지금 처리된 관리자 요청 기준'],['데이터베이스',d.database,'현재 연결된 저장소']]),table(ctx,[{label:'독립 작업자',key:'name'},{label:'상태',render:r=>r.available===true?(r.paused?'일시 정지':'연결됨'):r.available===false?'최근 응답 없음':'확인 불가'},{label:'최근 신호',render:r=>date(r.updated)}],d.items||[],{caption:'독립 작업자 연결 상태'}),ui.el('p',{class:'adm-muted',text:d.scope}),ui.el('a',{class:'adm-btn',href:screenHref('T02'),text:'저장소·백업 확인'}));
  });actions.append(button(ctx,'상태 다시 확인',refresh));await refresh();return;
 }
 if(view==='search'){
  const form=ui.el('form',{class:'adm-filters'}),q=ui.el('input',{type:'search','aria-label':'이름·업무 검색',value:ctx.params.get('q')||'',maxlength:'100'}),kind=ui.el('select',{'aria-label':'검색할 업무'},[['agent','에이전트'],['workflow','직원 워크플로'],...(ctx.bootstrap()?.me?.role==='operator'?[]:[['customer','고객']])].map(([value,text])=>ui.el('option',{value,text}))),holder=ui.el('div');form.append(q,kind,ui.el('button',{class:'adm-btn primary',type:'submit',text:'검색'}));body.append(form,holder);
  form.onsubmit=async e=>{e.preventDefault();if(!q.value.trim()){note.textContent='검색할 이름을 입력하세요.';return;}if(kind.value==='agent'){ctx.navigate(screenHref('A01',{q:q.value.trim()}));return;}if(kind.value==='workflow'){ctx.navigate(screenHref('W01',{q:q.value.trim()}));return;}ctx.navigate(screenHref('U01',{q:q.value.trim()}));};note.textContent='이름으로 찾을 업무를 선택하세요. 권한 없는 비공개 내용은 검색하지 않습니다.';return;
 }
 if(view==='identity'){
  const data=await read('/admin/api/v2/auth/me');body.append(ui.el('section',{class:'adm-card'},ui.el('h2',{text:'현재 로그인한 관리자'}),ui.dataView({이름:data.user?.name,아이디:data.user?.username,역할:ui.label(data.user?.role)}),ui.el('p',{text:'로그인 만료 시 비공개 내용은 숨기고 다시 로그인한 뒤 허용된 이전 화면으로 돌아갑니다.'})));return;
 }
 if(view==='access'){body.append(ui.empty('현재 업무 메뉴와 관리자 권한을 확인하세요.',ui.el('a',{class:'adm-btn',href:screenHref('H01'),text:'운영 요약'})));return;}
 await load(ctx,body,()=>read('/admin/api/v2/home/work'),d=>{
  const rows=[['승인 대기',d.reviews,'S01','변경 요청을 검토하세요.'],['지원 케이스',d.cases,'U04','담당 업무와 고객 답변 대기를 확인하세요.'],['진행 중 사고',d.incidents,'S05','영향 범위와 대응 상태를 확인하세요.']];
  body.replaceChildren(table(ctx,[{label:'처리할 일',render:r=>ui.el('a',{href:screenHref(r[2]),text:r[0]})},{label:'대기 건수',render:r=>ui.number(r[1])},{label:'다음 행동',render:r=>r[3]}],rows,{caption:'현재 처리 대기 업무'}),ui.el('p',{class:'adm-muted',text:'조회할 수 없는 건수는 확인 불가로 표시합니다. 업무를 열어 담당자·대상·승인 범위를 확인하세요.'}),ui.el('h2',{text:'최근 관리자 변경'}),table(ctx,[{label:'시각',render:r=>date(r.at)},{label:'작업',key:'action_name'},{label:'결과',render:r=>ui.label(r.status)}],d.audit||[],{caption:'최근 변경',empty:d.audit_allowed?'최근 변경 기록이 없습니다.':'감사 기록을 확인할 권한이 없습니다.'}));
 });
}
