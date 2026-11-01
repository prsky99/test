// Explicit catalog operations never turn a page read into an automatic live test.
const BASE='/admin/api/v2/catalog-tools';
const VIEWS=[['test','에이전트 테스트','등록된 에이전트와 입력을 확인한 뒤 한 번만 실행합니다.'],['register','직접 등록','주소 조사, 등록 정보 검토, 등록 순서로 진행하세요.'],['reports','테스트 보고서','기존 보고서를 검색하고 개별 결과를 확인합니다.'],['collector','수집 진행·실행','현재 진행 상태를 확인한 뒤 필요한 작업만 요청하세요.'],['credentials','자격증명','키 이름과 제공자를 확인한 뒤 비밀 값을 안전하게 변경합니다.'],['contract','의미 계약 검토','에이전트의 현재 연결·계약·테스트 근거를 확인합니다.'],['github','GitHub 이슈·PR 검색','공개 GitHub 이슈와 PR을 관리자 확인용으로 검색합니다. 공개 탐색·채팅에는 노출하지 않습니다.']];
export async function render(main,ctx) {
  if((ctx.params.get('view')||'test')==='test')return (await import('./agent-workbench.js')).render(main,ctx);
  if(ctx.params.get('view')==='contract')return (await import('./connection-review.js')).render(main,ctx);
  if(ctx.params.get('view')==='credentials')return (await import('./connections.js')).render(main,ctx);
  if(ctx.params.get('view')==='collector')return (await import('./collection.js')).render(main,{...ctx,rest:['overview']});
  const {ui,api}=ctx, role=ctx.bootstrap()?.me?.role;
  if(!['superadmin','admin'].includes(role)){main.replaceChildren(ui.empty('개인 관리자 권한이 필요합니다.'));return;}
  const view=ctx.params.get('view') || 'test',body=ui.el('section',{class:'adm-card adm-workbench'}),note=ui.el('p',{role:'status',class:'adm-status'});
  const spec=VIEWS.find(([key])=>key===view)||VIEWS[0];
  main.replaceChildren(ui.el('div',{class:'adm-head'},ui.el('div',{},ui.el('p',{class:'adm-eyebrow',text:'Catalog'}),ui.el('h1',{text:'카탈로그 운영 도구'})),ui.el('a',{class:'adm-btn',href:'#/catalog',text:'에이전트 목록'})),ui.el('div',{class:'adm-tabs',role:'navigation','aria-label':'카탈로그 운영 도구'},VIEWS.filter(([key])=>key!=='contract'||view==='contract').map(([key,label])=>ui.el('a',{class:'adm-tab',href:'#/catalog/tools?view='+key,'aria-current':view===key?'page':undefined,'aria-selected':String(view===key),text:label}))),body);
  const fields=ui.el('div',{class:'adm-form-grid'}),actions=ui.el('div',{class:'adm-actions'});
  const live=()=>ctx.isCurrent()&&body.isConnected;
  const field=(label,type='text',value='')=>{const node=ui.el(type==='textarea'?'textarea':'input',{'aria-label':label,value,...(type==='textarea'?{rows:'5',maxlength:'65536'}:{type,maxlength:type==='password'?'4096':'1000',autocomplete:'off'})});node.value=value;fields.append(ui.field(label,node,{wide:type==='textarea'||type==='checkbox'}));return node;};
  const select=(label,values)=>{const node=ui.el('select',{'aria-label':label},values.map(value=>ui.el('option',{value,text:ui.label(value)})));fields.append(ui.field(label,node));return node;};
  const output=ui.el('div',{class:'adm-result','aria-live':'polite',hidden:true});
  let initialRead=null;
  const safe=(value,depth=0)=>{
    if(depth>12)return '[Depth limit]';
    if(Array.isArray(value))return value.slice(0,1000).map(item=>safe(item,depth+1));
    if(value && typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,/^(?:authorization|password|secret|key_value|api_key|access_token|refresh_token|private_key|token)$/i.test(key)?'[REDACTED]':safe(item,depth+1)]));
    return value;
  };
  const show=value=>{output.hidden=false;output.replaceChildren(ui.dataView(safe(value)));};
  let busy=false,uncertain=false;
  async function change(button,path,payload,title,effect='변경 결과는 현재 기록을 다시 조회해 확인할 수 있습니다.',method='POST') {
    if(busy||uncertain||!live())return null;
    const answer=await ui.confirmChange({title,summary:effect+'\n'+JSON.stringify(path.startsWith('/credentials')?{key_name:payload.key_name,provider:payload.provider}:payload).slice(0,3000),confirmLabel:'검토한 요청 실행'});if(!answer||!live()||busy||uncertain)return null;
    busy=true;button.disabled=true;note.textContent='요청을 처리하고 있습니다. 자동 재시도하지 않습니다.';
    try{const result=await api.write(BASE+path,payload,{method,reason:answer.reason});if(live()){show(result);note.textContent='요청 결과를 받았습니다. 실제 실행 결과와 별도로 품질·권한을 확인하세요.';}return result;}
    catch(error){uncertain=true;if(live())note.textContent=error.message+' 다시 전송하지 않았습니다. 현재 기록을 조회한 뒤 새 화면에서 검토하세요.';return null;}
    finally{busy=false;if(!uncertain)button.disabled=false;}
  }
  const button=(label,handler)=>{const b=ui.el('button',{class:'adm-btn',type:'button',text:label});b.addEventListener('click',async()=>{if(b.disabled)return;b.disabled=true;b.setAttribute('aria-busy','true');try{await handler(b);}catch(error){if(live())note.textContent=error.message;}finally{b.removeAttribute('aria-busy');if(!uncertain)b.disabled=false;}});actions.append(b);return b;};
  async function read(path){const result=await api.read(BASE+path,{grade:'sensitive',force:true});if(live())show(result.data);return result.data;}
  try {
    if(view==='register'){
      body.append(ui.el('p',{text:'공개 HTTPS 주소를 조사한 뒤 검토한 항목을 등록합니다. 조사·등록에는 외부 확인 요청이 발생합니다. 실행·게시·배포 권한을 부여하지 않습니다.'}));
      const url=field('에이전트 HTTPS 주소','url'),kind=select('프로토콜',['a2a','mcp','x402']),name=field('에이전트 이름'),category=field('카테고리','text','ai_models'),description=field('설명','textarea'),extra=field('고급 등록 정보 JSON (프로토콜 원본 정보)','textarea','{}');
      let inputRevision=0;for(const element of [url,kind,name,description,category,extra]){element.addEventListener('input',()=>inputRevision++);element.addEventListener('change',()=>inputRevision++);}
      button('주소 조사',async b=>{const revision=inputRevision;const result=await change(b,'/register/inspect',{url:url.value.trim()},'등록 주소 조사','입력한 공개 주소에 외부 조사 요청을 보냅니다.');if(!result||revision!==inputRevision||!live())return;kind.value=result.kind;name.value=result.name || '';description.value=result.description || '';category.value=result.category || 'ai_models';extra.value=JSON.stringify({price_usdc:result.price_usdc,pay_to:result.pay_to,networks:result.networks,details:result.details},null,2);});
      button('검토한 에이전트 등록',b=>{let advanced;try{advanced=JSON.parse(extra.value);if(!advanced||Array.isArray(advanced)||typeof advanced!=='object'||Object.keys(advanced).some(key=>!['price_usdc','pay_to','networks','details'].includes(key)))throw Error();}catch{note.textContent='허용된 프로토콜 원본 정보 JSON을 입력하세요.';return;}return change(b,'/register',{...advanced,url:url.value.trim(),kind:kind.value,name:name.value.trim(),description:description.value.trim(),category:category.value.trim()},'에이전트 등록','이 주소의 활성 상태를 외부에서 확인한 뒤 카탈로그에 등록합니다.');});
    }else if(view==='reports'){
      const q=field('보고서 검색','search',ctx.params.get('q') || '');
      const list=ui.el('div',{dataset:{reportList:'1'},'aria-live':'polite'});let offset=0,version=0;
      const openReport=async row=>{
        const content=ui.el('div',{},ui.skeleton(3));ui.drawer(row.title || '테스트 보고서',content);
        try {const result=await api.read(BASE+'/test-reports/'+encodeURIComponent(row.report_id || row.id),{grade:'sensitive',force:true});if(live()&&content.isConnected)content.replaceChildren(ui.dataView(safe(result.data),{title:'테스트 보고서 상세'}));}
        catch(error){if(live()&&content.isConnected)content.replaceChildren(ui.empty(error.message));}
      };
      const load=async()=>{
        const turn=++version;list.setAttribute('aria-busy','true');list.querySelectorAll('.adm-pager button').forEach(button=>{button.disabled=true;});
        try {
          const {data:result}=await api.read(BASE+'/test-reports?'+new URLSearchParams({limit:'50',offset:String(offset),q:q.value.trim()}),{grade:'sensitive',force:true});
          if(!live()||turn!==version)return;
          const rows=result.reports || [],total=result.total || 0;
          list.replaceChildren(ui.el('p',{class:'adm-muted',text:'전체 '+ui.number(total)+'개 · '+(rows.length?ui.number(offset+1)+'–'+ui.number(offset+rows.length):'0')+'개 표시'}),
            ui.table([{label:'보고서',render:row=>row.title || row.agent_name || row.report_id || row.id},{label:'프로토콜',render:row=>(row.kind || '—').toUpperCase()},{label:'등급',render:row=>row.eval_grade || row.grade || '—'}],rows,{caption:'저장된 테스트 보고서',onSelect:row=>{if(ctx.screen)ctx.navigate('#/agents/a05?'+new URLSearchParams({report:String(row.report_id||row.id),q:q.value}));else openReport(row);}}),
            ui.el('div',{class:'adm-pager'},ui.el('button',{class:'adm-btn',type:'button',text:'이전 50개',disabled:offset===0,onclick:()=>{if(list.getAttribute('aria-busy')==='true')return;offset=Math.max(0,offset-50);load().catch(e=>{note.textContent=e.message;});}}),ui.el('button',{class:'adm-btn',type:'button',text:'다음 50개',disabled:offset+rows.length>=total,onclick:()=>{if(list.getAttribute('aria-busy')==='true')return;offset+=50;load().catch(e=>{note.textContent=e.message;});}})));
        } finally {if(turn===version)list.removeAttribute('aria-busy');}
      };
      const search=button('현재 보고서 조회',()=>{offset=0;return load();});
      q.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();search.click();}});
      body.append(list);initialRead=async()=>{await load();if(ctx.params.get('report'))await openReport({report_id:ctx.params.get('report')});};
    }else if(view==='collector'){
      body.append(ui.el('p',{text:'수집 진행은 현재 원본 집계입니다. 실행 버튼은 수집·검색 요청을 등록하며 백그라운드 완료를 의미하지 않습니다.'}));
      button('현재 수집 상태 조회',async()=>{const data=await read('/overview');if(live())show({crawl:data.crawl,actions:data.actions,collector:data.collector,captured_at:data.captured_at});});
      if(role==='superadmin'){
        const full=field('전체 동기화 (기본은 증분)','checkbox');
        button('수집 요청',b=>change(b,'/actions/crawl?force_full='+String(full.checked),{},full.checked?'전체 수집 요청':'증분 수집 요청','승인된 원본 수집을 백그라운드에서 요청합니다. 중복 요청은 자동 재시도하지 않습니다.'));
        button('게이트웨이 재검색 요청',b=>change(b,'/actions/rescan',{},'게이트웨이 재검색 요청','게이트웨이 에이전트의 원본 재검색을 한 번 요청합니다.'));
      }
    }else if(view==='contract'){
      if(role!=='superadmin'){body.replaceChildren(ui.empty('계약 승인은 최고관리자만 가능합니다.'));return;}
      body.append(ui.el('p',{text:'현재 연결 버전과 증거를 검토합니다. 계약 승인은 품질 인증이나 외부 실행 동의가 아니며, 계약 테스트는 입력을 외부 에이전트에 한 번 전송합니다.'}));
      const rid=field('계약 에이전트 ID','number',ctx.params.get('agent') || ''),contract=field('의미 계약 ID','text','docs.search.v1'),tool=field('승인할 정확한 도구 이름'),input=field('계약 테스트 입력 JSON','textarea','{}');
      button('현재 연결 버전·증거 조회',()=>read('/connections/'+Number(rid.value)));
      button('지원 의미 계약 조회',()=>read('/capability-contracts'));
      button('이 도구의 계약 승인',b=>change(b,'/connections/'+Number(rid.value)+'/contracts/'+encodeURIComponent(contract.value.trim()),{tool:tool.value.trim()},'의미 계약 승인','현재 스키마의 이 도구를 해당 계약으로 승인합니다. 추천·실행 적격성에 영향을 줄 수 있습니다.'));
      button('정확한 입력으로 계약 테스트',b=>{let value;try{value=JSON.parse(input.value);if(!value||Array.isArray(value)||typeof value!=='object')throw Error();}catch{note.textContent='유효한 계약 입력 JSON을 입력하세요.';return;}return change(b,'/connections/'+Number(rid.value)+'/contracts/'+encodeURIComponent(contract.value.trim())+'/test',{input:value},'계약 테스트 1회 실행','이 정확한 입력을 승인된 에이전트에 한 번 보냅니다. 구조 통과와 사실·전문가 품질은 별도입니다.');});
    }else if(view==='github'){
      if(role!=='superadmin'){body.replaceChildren(ui.empty('GitHub 검색은 최고관리자만 사용할 수 있습니다.'));return;}
      body.append(ui.el('p',{text:'GitHub 공개 검색 API를 인증 없이 호출합니다. 서버 전체에서 분당 10회까지이며, 같은 검색은 10분간 저장된 결과를 씁니다. 한도를 넘으면 잠시 후 다시 시도하세요.'}));
      const query=field('검색어'),repository=field('저장소 (owner/name, 선택)'),kind=select('종류',['any','issue','pull_request']),state=select('상태',['any','open','closed']),limit=field('개수 (1~5)','number','5');
      button('GitHub 검색',b=>{const payload={query:query.value.trim(),limit:Math.max(1,Math.min(5,Math.trunc(Number(limit.value))||5)),type:kind.value,state:state.value};if(repository.value.trim())payload.repository=repository.value.trim();return change(b,'/owned-data/github-issues/search',payload,'GitHub 이슈·PR 검색','GitHub 공개 검색 API에 최대 1회 요청합니다. 같은 검색은 10분간 저장된 결과를 씁니다.');});
    }else if(view==='credentials'){
      if(role!=='superadmin'){body.replaceChildren(ui.empty('자격증명 변경은 최고관리자만 가능합니다.'));return;}
      body.append(ui.el('p',{text:'저장된 원문을 표시하지 않습니다. 새 값은 비밀번호 입력칸에서만 전달하고 전송 후 지웁니다. 결제·구독·외부 모델을 자동 활성화하지 않습니다.'}));
      const key=field('키 이름'),provider=field('제공자 식별','text','custom'),description=field('키 설명'),secret=field('새 비밀 값','password');
      button('현재 키 목록 조회',()=>read('/credentials'));
      button('키 저장 요청',async b=>{const payload={key_name:key.value.trim(),provider:provider.value.trim(),description:description.value.trim(),key_value:secret.value};try{await change(b,'/credentials',payload,'자격증명 저장','이 키 이름의 서버 저장 값을 변경합니다. 실행·결제 동의를 부여하지 않습니다.');}finally{secret.value='';payload.key_value='';}});
      button('키 삭제 요청',b=>change(b,'/credentials/'+encodeURIComponent(key.value.trim()),{},'자격증명 삭제','이 키를 사용하는 새 연결이 실패할 수 있습니다.','DELETE'));
    }else{
      body.append(ui.el('p',{text:'도구 명세 조회도 원본에 접근할 수 있습니다. 실행 입력과 대상을 검토한 뒤 한 번만 테스트합니다. 결과는 검증되지 않은 에이전트 출력입니다.'}));
      const rid=field('에이전트 ID','number',ctx.params.get('agent') || ''),action=select('프로토콜 동작',['tools/call','message/send','query']),tool=field('도구 이름'),args=field('도구 입력 JSON','textarea','{}'),message=field('A2A 메시지','textarea');rid.min='1';rid.step='1';
      button('현재 명세 조회',async()=>{if(!Number.isSafeInteger(Number(rid.value))||Number(rid.value)<1)return;const answer=await ui.confirmChange({title:'도구 명세 조사',summary:'선택한 등록 주소의 명세를 조회합니다. 원본 도구 목록 요청이 발생할 수 있습니다.',confirmLabel:'명세 조회'});if(answer)await read('/test/agents/'+Number(rid.value)+'/spec');});
      button('검토한 입력 1회 실행',b=>{let input;try{input=JSON.parse(args.value);if(!input||Array.isArray(input)||typeof input!=='object')throw Error();}catch{note.textContent='유효한 도구 입력 JSON을 입력하세요.';return;}return change(b,'/test/execute',{resource_id:Number(rid.value),action:action.value,tool:tool.value.trim(),arguments:input,message:message.value,timeout_seconds:10},'에이전트 단일 테스트','이 정확한 입력을 선택한 에이전트에 한 번 보냅니다. 재전송하지 않습니다.');});
      button('저장된 테스트 보고서',()=>{location.hash='#/catalog/tools?view=reports';});
    }
    const descriptions=[...body.childNodes];if(view==='register'){const advanced=ui.el('details',{class:'adm-raw-details'},ui.el('summary',{text:'고급 등록 정보'}));for(const control of fields.querySelectorAll('textarea[aria-label*=JSON]')){const label=control.closest('label');if(label)advanced.append(label);}if(advanced.querySelector('textarea'))descriptions.push(advanced);}
    ui.fill(body,ui.el('h2',{text:spec[1]}),ui.el('p',{class:'adm-muted',text:spec[2]}),descriptions.filter(node=>!node.hasAttribute?.('data-report-list')),fields,actions,note,descriptions.filter(node=>node.hasAttribute?.('data-report-list')),output);
    if(initialRead)await initialRead();
  }catch(error){if(live())note.textContent=error.message;}
}
