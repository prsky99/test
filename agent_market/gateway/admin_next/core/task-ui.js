// Shared task states never replace failed data with an empty success result.
export const date=value=>value?new Date(value*1000).toLocaleString('ko-KR'):'기록 없음';
export function page(main,ctx,{title=ctx.screen?.title,help=ctx.screen?.purpose}={}){
 const {ui}=ctx,actions=ui.el('div',{class:'adm-actions'}),body=ui.el('div',{class:'adm-task-body','aria-live':'polite'}),note=ui.el('p',{role:'status',class:'adm-status'});
 main.replaceChildren(ui.el('div',{class:'adm-head'},ui.el('h1',{text:title}),actions),ui.el('p',{class:'adm-task-help',text:help}),note,body);return {body,actions,note};
}
export function button(ctx,label,handler,{primary=false}={}){
 const b=ctx.ui.el('button',{class:'adm-btn'+(primary?' primary':''),type:'button',text:label});
 b.onclick=async()=>{if(b.disabled)return;b.disabled=true;b.setAttribute('aria-busy','true');b.textContent=label+' · 처리 중';try{await handler(b);}catch(e){if(ctx.isCurrent())ctx.ui.toast(e.message,'bad');}finally{b.removeAttribute('aria-busy');b.textContent=label+(b.dataset.uncertain?' · 결과 확인 필요':'');if(b.isConnected&&!b.dataset.uncertain)b.disabled=b.dataset.locked==='true';}};return b;
}
export function errorView(ctx,host,error,retry){
 if(!ctx.isCurrent())return;const {ui}=ctx;const denied=error.status===403;
 host.replaceChildren(ui.el('section',{class:'adm-read-error'},ui.el('h2',{text:denied?'이 정보를 볼 권한이 없습니다':'현재 정보를 불러오지 못했습니다'}),ui.el('p',{text:denied?'관리자 역할과 선택한 작업공간의 멤버십을 확인하세요.':error.message}),!denied&&retry?button(ctx,'다시 조회',retry):null));
}
export async function load(ctx,host,read,paint){
 const progress=ctx.ui.el('p',{role:'status',class:'adm-inline-status',text:'현재 정보를 불러오고 있습니다.'});host.prepend(progress);host.setAttribute('aria-busy','true');try{const value=await read();if(ctx.isCurrent()&&host.isConnected)await paint(value);return value;}
 catch(e){if(e.status===401)throw e;errorView(ctx,host,e,()=>load(ctx,host,read,paint));}
 finally{progress.remove();if(ctx.isCurrent())host.removeAttribute('aria-busy');}
}
export function metrics(ctx,items){const {ui}=ctx;return ui.el('section',{class:'adm-grid adm-kpis'},items.map(([label,value,note])=>ui.el('div',{class:'adm-card adm-kpi'},ui.el('p',{class:'adm-eyebrow',text:label}),ui.el('div',{class:'adm-value adm-num',text:value}),ui.el('p',{class:'adm-muted',text:note||''}))));}
export function table(ctx,columns,items,{empty='조건에 맞는 기록이 없습니다.',action=null,...options}={}){return items.length?ctx.ui.table(columns,items,options):ctx.ui.empty(empty,action);}
export function details(ctx,title,value){const {ui}=ctx;ui.drawer(title,ui.dataView(value,{title:'상세 내용'}));}
