// Account changes remain pending until the existing independent review is applied.
export async function render(main, ctx) {
  const {ui,api}=ctx;
  if (ctx.bootstrap()?.me?.role !== 'superadmin') { main.replaceChildren(ui.empty('최고관리자만 계정을 관리할 수 있습니다.')); return; }
  const rows=ui.el('div'),status=ui.el('p',{role:'status'});
  const open = user => {
    const content=ui.el('div'),form=ui.el('form',{class:'adm-case-form'}),inputs={};
    const field=(label,key,type='text',value='')=>{const node=ui.el('input',{type,value,'aria-label':label,maxlength:type==='password'?'512':'100',autocomplete:type==='password'?'new-password':'off'});inputs[key]=node;form.append(ui.field(label,node,{wide:type==='checkbox'}));return node;};
    if (!user) field('관리자 아이디','username').required=true;
    field('표시 이름','name','text',user?.name || '').required=true;
    const role=ui.el('select',{'aria-label':'계정 역할'},['superadmin','admin','operator','viewer'].map(value=>ui.el('option',{value,text:ui.label(value)})));role.value=user?.role || 'admin';form.append(ui.field('계정 역할',role));
    const active=user?field('계정 활성화','active','checkbox'):null;if(active)active.checked=!!user.active;
    const password=field(user?'새 비밀번호 (변경 시에만)':'초기 비밀번호','password','password');password.required=!user;
    const reason=field('계정 변경 사유','reason');reason.minLength=4;reason.required=true;
    const confirm=field('대상 계정·역할·변경 내용을 검토했습니다','confirm','checkbox');confirm.required=true;
    const note=ui.el('p',{role:'status'}),save=ui.el('button',{class:'adm-btn primary',type:'submit',text:'승인 요청 등록'});
    let busy=false,unknown=false;
    for(const event of ['input','change'])form.addEventListener(event,e=>{if(e.target!==confirm)confirm.checked=false;});
    form.append(note,save);content.append(ui.el('p',{text:'아직 계정을 변경하지 않습니다. 승인 대기 목록에서 다른 최고관리자가 검토한 뒤 적용합니다. 비밀번호 값은 브라우저 저장소에 보관하지 않습니다.'}),form);
    ui.drawer(user?'관리자 변경 요청':'관리자 생성 요청',content);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy||unknown||!confirm.checked)return;
      busy=true;save.disabled=true;
      const body={name:inputs.name.value.trim(),role:role.value,reason:reason.value.trim()};
      if(user){body.active=active.checked?1:0;if(password.value)body.new_password=password.value;}else{body.username=inputs.username.value.trim();body.password=password.value;}
      try{
        const result=await api.write('/admin/api/users'+(user?'/'+user.id:''),body,{method:user?'PUT':'POST'});
        if(ctx.isCurrent()&&content.isConnected)content.replaceChildren(ui.el('p',{text:'승인 대기 · '+result.item.id}),ui.el('a',{class:'adm-btn',href:'#/security/s01',text:'승인 대기 목록 열기'}));
      }catch(error){unknown=true;note.textContent=error.message+' 자동 재시도하지 않았습니다. 승인 대기 목록을 확인하세요.';}
      finally{password.value='';delete body.password;delete body.new_password;busy=false;}
    });
  };
  async function load(){
    const result=await api.read('/admin/api/users',{grade:'sensitive',force:true});if(!ctx.isCurrent())return;
    rows.replaceChildren(ui.table([{label:'아이디',key:'username'},{label:'이름',key:'name'},{label:'역할',key:'role'},{label:'활성',render:r=>r.active?'활성':'중지'},{label:'변경',render:user=>ui.el('div',{class:'adm-actions'},
      ui.el('button',{class:'adm-btn',type:'button',text:'변경 요청',onclick:()=>open(user)}),
      ui.el('button',{class:'adm-btn danger',type:'button',text:'삭제 요청',onclick:async()=>{
        const answer=await ui.confirmChange({title:'관리자 삭제 요청',summary:user.username+' 계정의 삭제를 승인 대기에 등록합니다.',effect:'승인 전에는 삭제하지 않습니다.',confirmLabel:'삭제 승인 요청',danger:true});if(!answer)return;
        try{const value=await api.write('/admin/api/users/'+user.id,{reason:answer.reason},{method:'DELETE'});status.textContent='승인 대기 · '+value.item.id;}catch(error){status.textContent=error.message;}
      }}))}],result.data.users || [],{caption:'개인 관리자 계정'}));
  }
  main.replaceChildren(ui.el('h1',{text:'관리자 계정·역할'}),ui.el('div',{class:'adm-filters'},ui.el('button',{class:'adm-btn primary',type:'button',text:'관리자 생성 요청',onclick:()=>open(null)}),ui.el('button',{class:'adm-btn',type:'button',text:'현재 계정 목록 조회',onclick:()=>load().catch(error=>{status.textContent=error.message;})}),ui.el('a',{class:'adm-btn',href:'#/system',text:'시스템으로'})),status,rows);
  try{await load();}catch(error){rows.replaceChildren(ui.empty(error.message));}
}
