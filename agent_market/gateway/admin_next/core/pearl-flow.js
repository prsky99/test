// Schema-preserving Pearl flow view. Saving still uses the caller's original authority.
const NS='http://www.w3.org/2000/svg';
export function pearlFlow(ui,definition,{editable=false,onChange=()=>{},states={},health={}}={}){
  const root=ui.el('section',{class:'adm-card','aria-label':'워크플로 단계 흐름'});
  const canvas=document.createElementNS(NS,'svg');canvas.setAttribute('viewBox','0 0 760 260');canvas.setAttribute('role','img');canvas.setAttribute('aria-label','에이전트 연결 흐름');canvas.classList.add('adm-flow-svg');
  const list=ui.el('div',{class:'adm-filters'}),editor=ui.el('div'),status=ui.el('p',{role:'status','aria-live':'polite'});
  root.append(canvas,list,editor,status);
  let selected=null;const gradientId='adm-pearl-'+crypto.randomUUID().slice(0,8);
  const stateLabel=value=>({unrecorded:'실행 기록 없음',healthy:'정상',reachable:'도달 가능',succeeded:'성공',failed:'실패',running:'실행 중',disabled:'비활성',skipped:'건너뜀',blocked:'진행 불가',unknown:'미확인'}[value]||value);
  const draw=()=>{
    canvas.replaceChildren();list.replaceChildren();editor.replaceChildren();
    const defs=document.createElementNS(NS,'defs'),gradient=document.createElementNS(NS,'radialGradient');gradient.id=gradientId;gradient.setAttribute('cx','35%');gradient.setAttribute('cy','29%');gradient.setAttribute('r','72%');
    for(const [offset,color]of [['0%','#ffffff'],['32%','#fffdf5'],['62%','#e1d6c6'],['83%','#baa58c'],['100%','#f9f5ed']]){const stop=document.createElementNS(NS,'stop');stop.setAttribute('offset',offset);stop.setAttribute('stop-color',color);gradient.append(stop);}defs.append(gradient);canvas.append(defs);
    const nodes=definition.nodes || [],edges=definition.edges || [];
    if(!Array.isArray(nodes)||!Array.isArray(edges)||nodes.length>50||edges.length>100){status.textContent='최대 50단계·100연결의 미리보기만 표시합니다. 저장 검증 한도는 별도입니다.';return;}
    const ids=new Map(nodes.map((n,i)=>[n.id,i]));
    const point=i=>({x:65+(i%6)*126,y:55+Math.floor(i/6)*110});
    const height=Math.max(160,Math.ceil(nodes.length/6)*110);canvas.setAttribute('viewBox',`0 0 760 ${height}`);
    const svg=(tag,attrs={})=>{const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));canvas.append(node);return node;};
    for(const edge of edges){if(!ids.has(edge.source)||!ids.has(edge.target))continue;const a=point(ids.get(edge.source)),b=point(ids.get(edge.target));svg('path',{d:`M${a.x} ${a.y} C${a.x+45} ${a.y},${b.x-45} ${b.y},${b.x} ${b.y}`,class:'adm-flow-edge'});}
    nodes.forEach((node,i)=>{
      const p=point(i),agent=health[node.resource_id],value=(node.disabled||node.is_active===false||node.is_active===0)?'disabled':(states[node.id] || agent?.health_status || 'unrecorded');
      const tone=['succeeded','healthy','reachable'].includes(value)?'ok':['failed','down'].includes(value)?'bad':['running','queued','unknown'].includes(value)?'warn':'off';
      svg('circle',{cx:p.x,cy:p.y,r:23,fill:'url(#'+gradientId+')',class:'adm-flow-node','data-tone':tone});
      const label=svg('text',{x:p.x,y:p.y+40,'text-anchor':'middle',class:'adm-flow-label'});label.textContent=String(node.name || node.id).slice(0,18);
      const title=document.createElementNS(NS,'title');title.textContent=String(node.id)+' · 최근 실행 '+(states[node.id] || 'unrecorded')+' · 현재 '+(agent?.health_status || 'unrecorded');label.append(title);
      list.append(ui.el('button',{class:'adm-btn',type:'button','aria-pressed':String(selected===node.id),text:`${i+1}. ${node.name || node.id} · ${stateLabel(value)}${agent?' · 현재 '+agent.health_status:''}`,onclick:()=>{selected=node.id;draw();}}));
    });
    status.textContent=nodes.length?`${nodes.length}단계 · ${edges.length}연결. 테두리는 최근 실행 결과, 없으면 현재 상태입니다. 기록 없음은 미확인입니다.`:'단계를 추가하거나 노드 JSON을 입력하세요.';
    if(selected){const node=nodes.find(n=>n.id===selected);if(!node)return;editor.append(ui.el('h3',{text:'선택 단계: '+String(node.name || node.id)}));
      if(!editable){editor.append(ui.el('p',{text:node.kind || node.type || '단계'}));return;}
      const name=ui.el('input',{'aria-label':'선택 단계 영어 이름',value:String(node.name || ''),maxlength:'120'}),args=ui.el('textarea',{'aria-label':'선택 단계 입력 JSON',rows:'5',maxlength:'32000'});args.value=JSON.stringify(node.data?.input || {},null,2);
      editor.append(ui.el('label',{text:'영어 이름'},name),ui.el('label',{text:'입력 JSON'},args),ui.el('button',{class:'adm-btn',type:'button',text:'선택 단계 변경안 반영',onclick:()=>{try{const input=JSON.parse(args.value);if(!input||typeof input!=='object'||Array.isArray(input)||!name.value.trim())throw Error('이름과 JSON 객체가 필요합니다.');node.name=name.value.trim();node.data={...(node.data || {}),input};onChange(definition);draw();}catch(e){status.textContent=e.message;}}}));
    }
    if(editable){
      const control=ui.el('div',{class:'adm-filters'}),rid=ui.el('input',{type:'number',min:'1','aria-label':'새 단계 에이전트 ID',placeholder:'에이전트 ID'}),kind=ui.el('select',{'aria-label':'새 단계 프로토콜'},['a2a','mcp','x402'].map(v=>ui.el('option',{value:v,text:v.toUpperCase()}))),tool=ui.el('input',{'aria-label':'새 단계 도구',placeholder:'도구 이름 (MCP)'});
      control.append(rid,kind,tool,ui.el('button',{class:'adm-btn',type:'button',text:'에이전트 단계 추가',onclick:()=>{const id=Number(rid.value);if(!Number.isSafeInteger(id)||id<1){status.textContent='등록된 에이전트 ID를 입력하세요.';return;}if(nodes.length>=50){status.textContent='미리보기 단계 한도입니다.';return;}nodes.push({id:'node_'+crypto.randomUUID().slice(0,8),name:'Agent Step',type:'agent',kind:kind.value,resource_id:id,data:{tool:tool.value.trim(),input:{}}});definition.nodes=nodes;onChange(definition);draw();}}));
      const options=()=>nodes.map(n=>ui.el('option',{value:String(n.id),text:String(n.name || n.id)}));
      const source=ui.el('select',{'aria-label':'연결 시작 단계'},options()),target=ui.el('select',{'aria-label':'연결 대상 단계'},options());
      control.append(source,target,ui.el('button',{class:'adm-btn',type:'button',text:'단계 연결',onclick:()=>{if(!source.value||source.value===target.value||edges.some(e=>e.source===source.value&&e.target===target.value)){status.textContent='서로 다른 단계를 선택하세요. 중복 연결은 허용하지 않습니다.';return;}const reaches=(id,seen=new Set())=>{if(id===source.value)return true;if(seen.has(id))return false;seen.add(id);return edges.filter(e=>e.source===id).some(e=>reaches(e.target,seen));};if(reaches(target.value)){status.textContent='순환 연결은 허용하지 않습니다.';return;}edges.push({source:source.value,target:target.value});definition.edges=edges;onChange(definition);draw();}}));
      if(selected)control.append(ui.el('button',{class:'adm-btn danger',type:'button',text:'선택 단계 제거',onclick:()=>{definition.nodes=nodes.filter(n=>n.id!==selected);definition.edges=edges.filter(e=>e.source!==selected&&e.target!==selected);selected=null;onChange(definition);draw();}}));
      for(const [index,edge] of edges.entries())control.append(ui.el('button',{class:'adm-btn',type:'button',text:String(edge.source)+' → '+String(edge.target)+' 연결 제거',onclick:()=>{definition.edges=edges.filter((_,i)=>i!==index);onChange(definition);draw();}}));
      editor.append(control,ui.el('p',{text:'단계 변경은 아직 저장되지 않았습니다. 원래 저장·검증·게시 승인 절차를 완료해야 반영됩니다.'}));
    }
  };
  draw();return root;
}
