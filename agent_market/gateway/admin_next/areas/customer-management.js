// Remaining operational actions reuse current audited domain endpoints.
const WAC = '/admin/api/v2/customers/operations';
const id = () => crypto.randomUUID().replaceAll('-', '');
function input(ui, form, label, type = 'text') {
  const node = ui.el(type === 'textarea' ? 'textarea' : 'input', {'aria-label':label, ...(type === 'textarea' ? {rows:'4',maxlength:'4000'} : {type})});
  form.append(ui.el('label', {text:label}, node)); return node;
}
function choice(ui, form, label, values, current) {
  const node = ui.el('select', {'aria-label':label}, values.map(value => ui.el('option', {value,text:value})));
  if (current) node.value = current;
  form.append(ui.el('label', {text:label}, node)); return node;
}
function actionForm(ctx, title, description, configure) {
  const {ui} = ctx, form = ui.el('form', {class:'adm-case-form'}), content = ui.el('div', {}, ui.el('p', {text:description}), form);
  const close = ui.drawer(title, content);
  const send = configure(form);
  const consent = input(ui, form, '대상 고객·내용·공개 범위를 확인했습니다', 'checkbox'); consent.required = true;
  const note = ui.el('p', {role:'status'}), submit = ui.el('button', {class:'adm-btn primary',type:'submit',text:'확인한 내용 저장'});
  form.append(note, submit);
  for (const event of ['input','change']) form.addEventListener(event, e => { if (e.target !== consent) consent.checked = false; });
  let busy = false, uncertain = false;
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || uncertain || !consent.checked) return;
    busy = true; submit.disabled = true; consent.checked = false;
    try { await send(); if (ctx.isCurrent() && content.isConnected) { close(); ui.toast('검토한 내용을 저장했습니다.'); } }
    catch (error) { if (ctx.isCurrent() && content.isConnected) { uncertain = true; note.textContent = error.message + ' 자동 재시도하지 않았습니다. 창을 닫고 현재 기록을 확인하세요.'; } }
    finally { busy = false; if (!uncertain) submit.disabled = false; }
  });
}
export function createCase(ctx, customer) {
  const {ui, api} = ctx;
  actionForm(ctx, '고객 대응 생성', '고객에게 보이는 첫 안내를 이 고객의 새 케이스에 기록합니다.', form => {
    const subject = input(ui,form,'케이스 제목'), message = input(ui,form,'고객에게 보이는 첫 안내','textarea'), request = id(); subject.required = message.required = true;
    return () => api.write(WAC+'/customers/'+customer+'/cases', {subject:subject.value.trim(),message:message.value.trim(),workspace_id:null,source_ref:null,request_id:request});
  });
}
export function linkCase(ctx, item) {
  const {ui,api} = ctx;
  actionForm(ctx,'기존 고객 요청 연결','이메일 일치만으로 연결하지 않습니다. 실제 고객 관계를 확인해야 하며 알림·광고 동의를 변경하지 않습니다.',form => {
    const kind = choice(ui,form,'원본 요청 종류',['inquiry','privacy','cancellation'],'inquiry'), reference = input(ui,form,'원본 요청 참조 ID'), reason = input(ui,form,'고객 관계 확인 근거','textarea'); reference.required = reason.required = true;
    return () => api.write(WAC+'/cases/'+item.id+'/links',{revision:item.revision,source_kind:kind.value,source_ref:reference.value.trim(),reason:reason.value.trim(),confirmed_customer_relation:true});
  });
}
export async function creditHistory(ctx, customer) {
  const {ui,api} = ctx, content = ui.el('section', {class:'adm-card'}, ui.el('h3', {text:'가입 동의·크레딧 원장'}), ui.skeleton(3));
  try {
    const result = await api.read('/admin/api/customer-credits/'+encodeURIComponent(customer)+'/history',{grade:'sensitive',force:true});
    if (!ctx.isCurrent()) return content;
    content.replaceChildren(ui.el('h3',{text:'가입 동의·크레딧 원장'}),ui.el('p',{text:'유료 플랜·자동결제·충전은 준비 중입니다. 정정은 별도의 승인 명령으로 처리합니다.'}));
    for (const [key,label] of [['agreements','가입 동의'],['events','크레딧 이력']]) {
      const rows=result.data[key] || [];
      content.append(ui.el('details',{},ui.el('summary',{text:label+' '+rows.length+'건'}),ui.el('pre',{class:'adm-message',text:JSON.stringify(rows,null,2)})));
    }
  } catch (error) { content.replaceChildren(ui.empty(error.message)); }
  return content;
}
export function incident(ctx, item = null) {
  const {ui,api} = ctx;
  actionForm(ctx,item?'장애 조치':'장애 등록','운영 현상과 확인 근거를 기록합니다. 실행·알림·결제를 자동 재시도하지 않습니다.',form => {
    const category=choice(ui,form,'장애 분류',['auth','ai','execution','credit','storage','ingestion','support'],item?.category || 'execution');
    const status=item?choice(ui,form,'장애 상태',['mitigated','resolved'],'mitigated'):null;
    const reason=input(ui,form,'현상·조치 근거','textarea'); reason.required=true;
    return () => api.write(WAC+'/incidents'+(item?'/'+item.id+'/actions':''),{revision:item?.revision || 0,status:status?.value || 'open',category:category.value,reason:reason.value.trim(),assigned_to:item?.assigned_to ?? null});
  });
}
