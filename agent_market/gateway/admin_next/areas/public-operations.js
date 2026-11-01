import {pearlFlow} from '../core/pearl-flow.js';
// Private contact data is never cached or persisted by this workbench.
const BASE='/admin/api/v2/public/operations';
const time=value=>value?new Date(value*1000).toLocaleString('ko-KR'):'—';
const text=(ui,value)=>ui.dataView(value,{title:''});
const field=(ui,form,label,value='',kind='input')=>{const input=ui.el(kind,{'aria-label':label,...(kind==='textarea'?{rows:'6',maxlength:'150000'}:{type:'text',maxlength:'500'})});input.value=value;form.append(ui.field(label,input,{wide:kind==='textarea'}));return input;};
const choose=(ui,form,label,values)=>{const input=ui.el('select',{'aria-label':label},values.map(value=>ui.el('option',{value,text:value?ui.label(value):'전체'})));form.append(ui.field(label,input));return input;};
async function read(ctx,path){return (await ctx.api.read(BASE+path,{grade:'sensitive',force:true})).data;}
const live=(ctx,node)=>ctx.isCurrent()&&node.isConnected;

export async function change(ctx,button,path,payload,summary,preview=null){
  const {ui,api}=ctx;
  if(button.disabled)return null;
  button.disabled=true;
  const safe=preview || Object.fromEntries(Object.entries(payload).filter(([key])=>key!=='preview_token'));
  const answer=await ui.confirmChange({title:summary,summary:JSON.stringify(safe,null,2).slice(0,6000),effect:'허용된 제한·초안 변경은 즉시 적용하고, 게시·보안 완화·단건 알림은 승인 대기에 등록합니다. 결과가 불명확하면 자동 재시도하지 않습니다.',confirmLabel:'검토한 요청 등록'});
  if(!answer||!ctx.isCurrent()){button.disabled=false;return null;}
  button.disabled=true;
  try{
    const result=await api.write(path,{...payload,reason:answer.reason},{reason:answer.reason});
    if(!ctx.isCurrent())return null;
    ui.drawer(result.review?'승인 대기':'변경 결과',ui.el('div',{},
      ui.el('p',{text:result.review?'아직 게시·발송·보안 완화가 적용되지 않았습니다. 승인자는 현재 대상·동의·기한을 다시 확인합니다.':'현재 기록을 다시 조회해 변경 결과를 확인하세요.'}),
      text(ui,result.review?{id:result.review.id,status:result.review.status,expires:time(result.review.expires),preview_expires:time(result.preview_expires_at)}:result.result || result),
      path===BASE+'/template'?ui.el('a',{class:'adm-btn',href:'#/public/templates?fresh='+Date.now(),text:'정의 목록 다시 조회'}):null,
      result.review?ui.el('a',{class:'adm-btn',href:'#/security/s01',text:'승인 대기 목록 열기'}):null));
    return result;
  }catch(error){if(ctx.isCurrent())ui.toast(error.message+' 현재 기록을 확인하세요. 자동 재전송하지 않았습니다.','bad');return null;}
}
function formDrawer(ctx,title,build){const form=ctx.ui.el('form',{class:'adm-case-form'});ctx.ui.drawer(title,form);build(form);}

export async function render(main,ctx,view){
  const {ui}=ctx,body=ui.el('section',{class:'adm-card adm-workbench'});
  const views=[['','집계'],['visitors','방문 에이전트'],['notifications','알림 설정·이력'],['sns','SNS'],['templates','공개 템플릿']];
  main.replaceChildren(ui.el('div',{class:'adm-head'},ui.el('div',{},ui.el('p',{class:'adm-eyebrow',text:'Public service'}),ui.el('h1',{text:'공개 서비스 운영'}))),ui.el('div',{class:'adm-tabs',role:'navigation','aria-label':'공개 서비스 운영'},views.map(([id,label])=>ui.el('a',{class:'adm-tab',href:'#/public'+(id?'/'+id:''),text:label,'aria-current':id===view?'page':undefined,'aria-selected':String(id===view)}))),body);
  body.append(ui.el('h2',{text:views.find(([id])=>id===view)?.[1] || '방문 에이전트'}));
  try{
    const options=await read(ctx,'/options');if(!live(ctx,body))return;
    body.append(ui.el('p',{text:'광고·일괄 발송은 비활성입니다. 관리자는 고객의 동의를 새로 부여하거나 철회된 연락처를 복구할 수 없습니다.'}));
    await ({visitors,notifications,sns,templates}[view] || visitors)(body,ctx,options);
  }catch(error){if(live(ctx,body))body.replaceChildren(ui.empty(error.message));}
}
async function visitors(body,ctx,options){
  const {ui}=ctx,q=ui.el('input',{type:'search','aria-label':'방문 에이전트 검색',placeholder:'이름·관심 작업'}),filter=ui.el('select',{'aria-label':'연락처 상태'},['all','registered','authorized','pending','marketing','legacy','none'].map(value=>ui.el('option',{value,text:ui.label(value)}))),list=ui.el('div');
  const filters=ui.el('div',{class:'adm-filters'}),protocol=choose(ui,filters,'희망 프로토콜',['','any','a2a','mcp','x402']),state=choose(ui,filters,'대응 상태',['','new','reviewing','waiting','resolved','archived']),source=choose(ui,filters,'방문 출처',['all','live','simulation']),tier=choose(ui,filters,'기록된 방문 빈도',['','new','returning','regular']);
  let offset=0,version=0;
  const load=async()=>{const seq=++version;const data=await read(ctx,'/source/visitors?'+new URLSearchParams({q:q.value,contact:filter.value,protocol:protocol.value,case_state:state.value,source:source.value,...(tier.value?{tier:tier.value}:{}),offset:String(offset),limit:'50'}));if(seq!==version||!live(ctx,list))return;
    list.replaceChildren(text(ui,data.filtered_stats || data.stats || {}),ui.table([{label:'방문자',render:r=>r.name || r.id},{label:'최근 작업',key:'last_task'},{label:'프로토콜',key:'requested_protocol'},{label:'활성 작업 알림',key:'active_watches'},{label:'개별 대응',key:'case_status'}],data.items || data.visitors || [],{caption:'기록된 방문 에이전트',onSelect:row=>visitorDetail(ctx,row.id,options)}),ui.el('button',{class:'adm-btn',text:'이전 50개',disabled:offset===0,onclick:()=>{offset=Math.max(0,offset-50);load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'다음 50개',disabled:!data.pagination?.has_more,onclick:()=>{offset+=50;load().catch(e=>ui.toast(e.message,'bad'));}}));};
  body.append(filters,ui.el('div',{class:'adm-filters'},q,filter,ui.el('button',{class:'adm-btn',text:'검색',onclick:()=>{offset=0;load().catch(e=>ui.toast(e.message,'bad'));}})),list);await load();
}
async function visitorDetail(ctx,id,options){
  const {ui,api}=ctx,content=ui.el('div',{},ui.skeleton(4));ui.drawer('방문 에이전트 상세',content);
  try{
    const data=await read(ctx,'/source/visitors/'+encodeURIComponent(id));if(!live(ctx,content))return;
    content.replaceChildren(ui.el('h3',{text:'기록된 질문·추천'}),text(ui,data.chat_turns || []),ui.el('h3',{text:'개별 대응·목적별 권한'}),text(ui,data.case),text(ui,data.case_notes || []));
    const c=data.case || {};
    if(['admin','superadmin'].includes(ctx.bootstrap()?.me?.role)){
      const form=ui.el('form',{class:'adm-case-form'}),status=choose(ui,form,'대응 상태',['new','reviewing','waiting','resolved','archived']),owner=field(ui,form,'담당자',c.owner || ''),note=field(ui,form,'내부 대응 메모','','textarea'),followup=field(ui,form,'다음 대응 시각 (ISO, 선택)',c.next_followup?new Date(c.next_followup*1000).toISOString():'');status.value=c.status || 'new';
      const b=ui.el('button',{class:'adm-btn',type:'submit',text:'개별 대응 저장'});form.append(b);form.onsubmit=event=>{event.preventDefault();const at=followup.value?Date.parse(followup.value)/1000:null;if(followup.value&&!Number.isFinite(at)){ui.toast('유효한 시각을 입력하세요.','bad');return;}change(ctx,b,'/admin/api/visitors/'+id+'/case',{status:status.value,owner:owner.value,note:note.value,next_followup:at,version:c.version || 0},'개별 대응 저장');};content.append(form);
    }
    for(const watch of data.contact_relationships || []){
      const section=ui.el('section',{class:'adm-card'},ui.el('h3',{text:watch.task || watch.id}),text(ui,watch));content.append(section);
      if(!options.can_change)continue;
      section.append(ui.el('button',{class:'adm-btn',text:'정확한 단건 미리보기',onclick:async()=>{
        try{const preview=await read(ctx,'/source/visitors/'+id+'/task-updates/'+watch.id+'/preview');if(!live(ctx,content))return;const {preview_token,...safe}=preview;const p=ui.el('div',{},ui.el('p',{text:'이 작업·추천·인증 상태의 5분 미리보기입니다. 승인 시점에도 동일해야 합니다. 광고 메시지 편집은 제공하지 않습니다.'}),text(ui,safe));const b=ui.el('button',{class:'adm-btn',text:'단건 처리 승인 요청',disabled:!preview.can_process,onclick:()=>change(ctx,b,'/admin/api/visitors/'+id+'/task-updates/'+watch.id+'/process',{preview_token},'동의된 단건 작업 알림',{watch_id:watch.id,fingerprint:preview.fingerprint,recommendation:preview.recommendation,expires_at:time(preview.expires_at)})});p.append(b);ui.drawer('작업 알림 미리보기',p);}catch(e){ui.toast(e.message,'bad');}
      }}));
      for(const [action,label] of [['pause','일시정지'],['stop','알림 중지'],['withdraw_marketing','광고 동의 철회'],['delete','등록 삭제']]){const b=ui.el('button',{class:'adm-btn',text:label,onclick:()=>change(ctx,b,'/admin/api/visitors/'+id+'/task-updates/'+watch.id+'/action',{action},label,{watch_id:watch.id,task:watch.task,action})});section.append(b);}
    }
  }catch(error){if(live(ctx,content))content.replaceChildren(ui.empty(error.message));}
}
async function notifications(body,ctx){
  const {ui}=ctx,q=ui.el('input',{type:'search','aria-label':'알림 ID·작업 검색'}),list=ui.el('div'),filters=ui.el('div',{class:'adm-filters'});let offset=0,version=0;const state=choose(ui,filters,'알림 상태',['all','active','paused','pending_verification','revoked','expired','failed']),channel=choose(ui,filters,'알림 채널',['all','poll','browser','webhook','a2a']);
  const load=async()=>{const seq=++version;const data=await read(ctx,'/source/needs/notifications?'+new URLSearchParams({q:q.value,state:state.value,channel:channel.value,limit:'50',offset:String(offset)}));if(seq!==version||!live(ctx,list))return;list.replaceChildren(text(ui,data.summary),ui.table([{label:'작업',key:'task'},{label:'채널',key:'channel'},{label:'상태',key:'state'},{label:'주소',key:'destination'},{label:'현재 동의',render:r=>r.permission_current?'유효':'사용 불가'}],data.items || [],{caption:'알림 설정',onSelect:async row=>{const content=ui.el('div',{},ui.skeleton(3));ui.drawer('알림 상세·이력',content);try{const d=await read(ctx,'/source/needs/notifications/'+row.id);if(live(ctx,content))content.replaceChildren(text(ui,d));}catch(e){if(live(ctx,content))content.replaceChildren(ui.empty(e.message));}}}),ui.el('button',{class:'adm-btn',text:'이전 50개',disabled:offset===0,onclick:()=>{offset=Math.max(0,offset-50);load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'다음 50개',disabled:!data.pagination?.has_more,onclick:()=>{offset+=50;load().catch(e=>ui.toast(e.message,'bad'));}}));};
  body.append(filters,ui.el('div',{class:'adm-filters'},q,ui.el('button',{class:'adm-btn',text:'검색',onclick:()=>{offset=0;load().catch(e=>ui.toast(e.message,'bad'));}})),list);await load();
}
async function sns(body,ctx,options){
  const {ui}=ctx,q=ui.el('input',{type:'search','aria-label':'SNS 검색'}),list=ui.el('div'),filters=ui.el('div',{class:'adm-filters'});let offset=0,version=0;const mode=choose(ui,filters,'피드 정렬',['latest','for_you','popular']),protocol=choose(ui,filters,'SNS 프로토콜',['','a2a','mcp','x402']),role=choose(ui,filters,'작성자 종류',['','agent','community','user','developer']);
  const load=async()=>{const seq=++version;const query=new URLSearchParams({tab:mode.value,limit:'50',offset:String(offset),q:q.value});if(protocol.value)query.set('protocol',protocol.value);if(role.value)query.set('role',role.value);const data=await read(ctx,'/source/sns/feed?'+query);if(seq!==version||!live(ctx,list))return;list.replaceChildren(ui.table([{label:'작성자',render:r=>r.author?.name || '—'},{label:'내용',key:'body'},{label:'프로토콜',key:'protocol'},{label:'시각',render:r=>time(r.created)}],data.items || [],{caption:'실제 SNS 피드',onSelect:row=>thread(row)}),ui.el('button',{class:'adm-btn',text:'이전',disabled:offset===0,onclick:()=>{offset=Math.max(0,offset-50);load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'다음',disabled:!data.has_more,onclick:()=>{offset+=50;load().catch(e=>ui.toast(e.message,'bad'));}}));};
  const thread=async row=>{const content=ui.el('div',{},ui.skeleton(3));ui.drawer('SNS 원문·댓글',content);try{const data=await read(ctx,'/source/sns/thread?key='+encodeURIComponent(row.key));if(!live(ctx,content))return;content.replaceChildren(text(ui,data));const like=ui.el('button',{class:'adm-btn',text:'직원 반응 변경',onclick:()=>change(ctx,like,'/admin/api/sns/like',{key:row.key,client:'staff:'+ctx.bootstrap().me.username},'SNS 직원 반응')});content.append(like);if(options.can_change){content.append(ui.el('button',{class:'adm-btn',text:'댓글 작성 승인 요청',onclick:()=>compose(row.key)}));if(row.key.startsWith('p:')){const b=ui.el('button',{class:'adm-btn danger',text:'글 보관 승인 요청',onclick:()=>change(ctx,b,BASE+'/sns',{action:'delete',target:row.key,fields:{}},'SNS 글 보관')});content.append(b);}}}catch(e){if(live(ctx,content))content.replaceChildren(ui.empty(e.message));}};
  const compose=parent=>formDrawer(ctx,'공식 SNS 글 승인 요청',form=>{form.append(ui.el('p',{text:'Agent Concierge 명의의 직원 작성 글로 표시합니다. 검증된 고객/에이전트 글로 가장하지 않습니다. 공개 본문에는 개인정보·비밀값을 넣지 마세요.'}));const content=field(ui,form,'공개 영어 본문','','textarea'),protocol=choose(ui,form,'프로토콜',['','a2a','mcp','x402']),role=choose(ui,form,'공식 글 종류',['developer','user']),rating=choose(ui,form,'평점 (선택)',['','1','2','3','4','5']),resource=field(ui,form,'관련 에이전트 ID (선택)');content.maxLength=500;const b=ui.el('button',{type:'submit',class:'adm-btn',text:'게시 승인 요청'});form.append(b);form.onsubmit=e=>{e.preventDefault();change(ctx,b,BASE+'/sns',{action:'create',fields:{body:content.value,protocol:protocol.value,parent_key:parent || null,role:role.value,rating:rating.value?Number(rating.value):null,resource_id:resource.value?Number(resource.value):null}},'SNS 게시 승인 요청');};});
  body.append(filters,ui.el('div',{class:'adm-filters'},q,ui.el('button',{class:'adm-btn',text:'검색',onclick:()=>{offset=0;load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'주제·출처 정보',onclick:async()=>{try{const data=await read(ctx,'/source/sns/sidebar');if(ctx.isCurrent())ui.drawer('SNS 주제·출처',text(ui,data));}catch(e){ui.toast(e.message,'bad');}}}),options.can_change?ui.el('button',{class:'adm-btn',text:'공식 글 작성',onclick:()=>compose(null)}):null),list);await load();
}
async function templates(body,ctx,options){
  const {ui}=ctx,list=ui.el('div');let offset=0,version=0;const search=ui.el('input',{type:'search','aria-label':'템플릿 이름·설명 검색'}),filters=ui.el('div',{class:'adm-filters'}),kind=choose(ui,filters,'템플릿 종류',['all','templates','drafts']);
  const edit=async row=>{let data={name:'',description:'',category:'automation',tags:'',trigger_type:'manual',nodes:[],edges:[]};if(row)data=await read(ctx,'/templates/'+row.id);if(!ctx.isCurrent())return;
    formDrawer(ctx,'공개 템플릿 정의 편집',form=>{form.append(ui.el('p',{text:'저장만으로 에이전트를 실행하지 않습니다. 공개 게시·게시 중 수정은 별도 승인입니다. 비공개 자격증명·수신처·예약은 상속하지 않습니다.'}));const name=field(ui,form,'영어 이름',data.name),description=field(ui,form,'영어 설명',data.description || ''),category=field(ui,form,'카테고리',data.category || 'automation'),graph=field(ui,form,'노드·연결 JSON',JSON.stringify({nodes:data.nodes,edges:data.edges},null,2),'textarea');
      if(data.nodes?.length)form.append(ui.el('ol',{},data.nodes.map(n=>ui.el('li',{text:(n.name || n.id)+' · '+(n.type || n.kind || 'step')}))));
      const preview=ui.el('div',{class:'adm-flow-preview'});form.append(preview);let states={},health={},shownGraph=null;const initialGraph=graph.value;
      const showGraph=()=>{const marker=graph.value+'|'+JSON.stringify(states)+'|'+JSON.stringify(health);if(shownGraph===marker)return;shownGraph=marker;try{preview.replaceChildren(pearlFlow(ui,JSON.parse(graph.value),{editable:options.can_change,states,health,onChange:value=>{graph.value=JSON.stringify(value,null,2);for(const key of Object.keys(states))delete states[key];shownGraph=graph.value+'|'+JSON.stringify(states)+'|'+JSON.stringify(health);}}));}catch(e){preview.replaceChildren(ui.empty('유효한 노드·연결 JSON을 입력하세요.'));}};graph.addEventListener('input',showGraph);graph.addEventListener('change',showGraph);showGraph();
      if(row)ctx.api.read('/admin/api/v2/insights/workflows/'+row.id+'/state',{grade:'sensitive',force:true}).then(r=>{if(!live(ctx,preview)||graph.value!==initialGraph||preview.contains(document.activeElement))return;health=Object.fromEntries((r.data.agents || []).map(a=>[a.id,a]));states=Object.fromEntries((r.data.steps || []).map(step=>[step.node_id,step.status]));showGraph();preview.prepend(ui.el('p',{text:r.data.run?'최근 저장 실행 상태: '+r.data.run.status+' · 정의 변경안의 성공을 보증하지 않습니다.':'최근 실행 기록 없음'}));}).catch(e=>{if(live(ctx,preview))preview.append(ui.empty(e.message));});
      const values=()=>{const g=JSON.parse(graph.value);if(!g||!Array.isArray(g.nodes)||!Array.isArray(g.edges)||Object.keys(g).some(k=>!['nodes','edges'].includes(k)))throw Error('nodes/edges 배열만 입력하세요.');return {name:name.value,description:description.value,category:category.value,tags:data.tags || '',trigger_type:'manual',...g};};
      const save=ui.el('button',{class:'adm-btn',type:'submit',text:row?'정의 저장 요청':'비공개 초안 저장'});save.disabled=!options.can_change;form.append(save);form.onsubmit=e=>{e.preventDefault();try{change(ctx,save,BASE+'/template',{action:row?'update':'create',target:row?.id,revision:data.revision,fields:values()},'정의 저장');}catch(error){ui.toast(error.message,'bad');}};
      if(row&&options.can_change){for(const [action,label] of [['publish','공개 게시 승인 요청'],['unpublish','게시 중지 승인 요청']]){const b=ui.el('button',{class:'adm-btn',type:'button',text:label,onclick:()=>{try{change(ctx,b,BASE+'/template',{action,target:row.id,revision:data.revision,fields:action==='publish'?values():{}},label);}catch(e){ui.toast(e.message,'bad');}}});form.append(b);}}
    });};
  body.append(ui.el('p',{text:'실제 저장된 정의 목록입니다. 새 초안은 즉시 저장하지만 공개 게시와 게시 중 정의 변경은 검토 전 적용하지 않습니다.'}),ui.el('div',{class:'adm-filters'},options.can_change?ui.el('button',{class:'adm-btn',text:'새 공개용 초안',onclick:()=>edit(null)}):null,ui.el('a',{class:'adm-btn',href:'#/customers/specialists',text:'직원 워크플로 실행·배포'})),list);
  const load=async()=>{const seq=++version;const query=new URLSearchParams({q:search.value,offset:String(offset)});if(kind.value!=='all')query.set('is_template',kind.value==='templates'?'1':'0');const data=await read(ctx,'/templates?'+query);if(seq!==version||!live(ctx,list))return;list.replaceChildren(ui.el('p',{text:'전체 '+ui.number(data.total)+'개 중 '+ui.number(offset+1)+'번부터 최대 100개'}),ui.table([{label:'정의',key:'name'},{label:'게시 상태',render:r=>r.is_template&&r.is_active?'게시 중':'초안/비활성'},{label:'최근 변경',render:r=>time(r.updated_at)}],data.items || [],{caption:'관리자 워크플로 정의',onSelect:row=>edit(row).catch(e=>ui.toast(e.message,'bad'))}),ui.el('button',{class:'adm-btn',text:'이전 정의',disabled:offset===0,onclick:()=>{offset=Math.max(0,offset-100);load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'다음 정의',disabled:!data.has_more,onclick:()=>{offset+=100;load().catch(e=>ui.toast(e.message,'bad'));}}));};body.append(filters,ui.el('div',{class:'adm-filters'},search,ui.el('button',{class:'adm-btn',text:'정의 검색',onclick:()=>{offset=0;load().catch(e=>ui.toast(e.message,'bad'));}})));await load();
}

export async function securityRules(body,ctx){
  const {ui}=ctx;const data=await read(ctx,'/source/security/rules?limit=100');if(!live(ctx,body))return;
  body.replaceChildren(ui.el('p',{text:'보안 완화·차단 해제는 승인 대기입니다. 제한 강화는 사유 기록 후 즉시 적용하며 전체 해제는 자동 수행하지 않습니다.'}),ui.table([{label:'IP',key:'ip'},{label:'규칙',key:'action'},{label:'사유',key:'reason'},{label:'만료',render:r=>time(r.expires_at)}],data.rules || [],{caption:'현재 저장된 보안 규칙'}));
  const form=ui.el('form',{class:'adm-case-form'}),action=choose(ui,form,'보안 변경',['block','allow','remove','remove_blocks','under_attack','rate']),target=field(ui,form,'대상 IP / 일괄 해제할 IP JSON 배열',''),fields=field(ui,form,'설정 JSON','{"duration":3600}','textarea');
  form.append(ui.el('p',{text:'긴급 방어: {"enabled":true/false}, 요청 배율: {"multiplier":0.5}, 규칙 해제: {}. 일괄 해제는 명시한 차단 IP 최대 100개만 검토합니다.'}));action.addEventListener('change',()=>{fields.value=JSON.stringify({block:{duration:3600},allow:{},remove:{},remove_blocks:{},under_attack:{enabled:true},rate:{multiplier:.5}}[action.value]);});const b=ui.el('button',{class:'adm-btn',type:'submit',text:'보안 변경 검토'});form.append(b);form.onsubmit=e=>{e.preventDefault();try{const value=JSON.parse(fields.value);change(ctx,b,BASE+'/security',{action:action.value,target:action.value==='remove_blocks'?JSON.parse(target.value):target.value,fields:value},'보안 변경');}catch(error){ui.toast(error.message,'bad');}};body.append(form);const clean=ui.el('button',{class:'adm-btn',text:'만료된 규칙만 정리',onclick:()=>change(ctx,clean,'/admin/api/security/clear-expired',{},'만료 규칙 정리')});body.append(clean);
}
