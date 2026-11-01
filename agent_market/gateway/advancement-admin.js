/* Private simulation and reviewed draft support. No money or provider execution. */
(() => {
  'use strict';
  const PROFILE='workspace-advancement-tools-v1';
  const LEDGER='workspace-shadow-accounting-v1', PROPOSE='workspace-support-proposal-v1', APPLY='workspace-support-apply-v1';
  const DECLARE='workspace-readiness-declaration-v1';
  let dialog=null, body=null, status=null, ws='', session='', epoch=0, busy=false, locked=false;
  const identity=()=>typeof token==='string'&&typeof currentUser!=='undefined'&&currentUser?`${token}|${currentUser.user_id}|${currentUser.role}`:'';
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  const button=(text,fn)=>{const el=node('button',text);el.type='button';el.className='btn';el.addEventListener('click',fn);return el;};
  const field=(label,type='text')=>{const host=node('label',label);host.className='form-group';const input=node(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.autocomplete='off';host.style.display='flex';host.style.flexDirection='column';host.style.gap='6px';input.style.cssText='box-sizing:border-box;width:100%;max-width:100%;min-width:0;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg,Canvas);color:var(--text,CanvasText)';host.append(input);return {host,input};};
  const checkbox=label=>{const host=node('label');const input=node('input');input.type='checkbox';input.checked=false;host.append(input,' ',node('span',label));return {host,input};};
  function stamp(){return {epoch,ws,session};}
  function valid(mark){return dialog?.open&&mark.epoch===epoch&&mark.ws===ws&&mark.session===session&&session===identity();}
  function tell(text){if(status)status.textContent=text;}
  function leave(){epoch++;busy=false;locked=false;ws='';session='';if(dialog){dialog.close();dialog.remove();dialog=null;}body=null;status=null;}
  function onSession(){const selected=document.getElementById('workspaceSelect');if(session&&(identity()!==session||(selected?.value&&selected.value!==ws)))leave();}
  function id(prefix){return prefix+'_'+Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');}
  async function request(path,options={}){
    const result=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/advancement${path}`,{...options,silent:true});
    if(result?.ok!==true||result.profile!==PROFILE)throw new Error('unsupported_profile');return result.result;
  }
  function failure(error){tell(error?.status===404||error?.status===401||error?.status===403?'Current session or workspace access changed. Close and reopen this view.':'The result could not be confirmed. Read current history before making a new request. No request is retried automatically.');}
  async function change(path,value,after){
    if(busy||locked)return;const mark=stamp();busy=true;locked=true;tell('Submitting one reviewed request.');
    try{const result=await request(path,{method:'POST',json:value});if(!valid(mark))return;locked=false;await after(result,mark);}
    catch(error){if(valid(mark))failure(error);}
    finally{if(valid(mark))busy=false;}
  }
  function area(){body.replaceChildren();tell('');locked=false;busy=false;}
  function listLine(parent,value){const line=node('p',value);parent.append(line);return line;}
  async function ledger(){
    epoch++;area();const mark=stamp();
    try{
      const [options,summary]=await Promise.all([request('/ledger/options'),request('/ledger')]);if(!valid(mark))return;
      listLine(body,'Simulated accounting only. No customer charge, provider payout or 70/30 allocation is performed.');
      listLine(body,`Verified entries: ${summary.entries}; events: ${summary.events}; balanced: ${summary.balanced?'yes':'no'}.`);
      const units=field('Approved integer units','number');units.input.min='1';units.input.max=String(options.max_units);units.input.value='1';
      const asset=node('select');for(const value of options.assets)asset.append(new Option(value,value));const assetLabel=node('label','Declared simulation asset ');assetLabel.append(asset);
      const consent=checkbox('Approve this exact simulated logical operation. This is not payment consent.');
      body.append(assetLabel,units.host,consent.host,button('Approve simulation',()=>{
        const amount=Number(units.input.value);if(!options.can_write||!consent.input.checked||!Number.isSafeInteger(amount)||amount<1)return;
        consent.input.checked=false;change('/ledger/approve',{operation_id:id('slop'),asset:asset.value,units:amount,authorized:true,notice:LEDGER},()=>ledger());
      }));
      for(const operation of summary.operations){
        const card=node('section');card.className='card';listLine(card,`${operation.id} · ${operation.asset} · approved ${operation.approved_units} · settled ${operation.settled_units} · ${operation.status} · revision ${operation.revision}`);
        const outcome=node('select');for(const value of operation.status==='unknown'?['not_received','completed','partial']:['completed','partial','unknown'])outcome.append(new Option(value,value));
        const amount=field('Settled integer units','number');amount.input.min='0';amount.input.max=String(operation.approved_units);amount.input.value=String(operation.approved_units);
        const approve=checkbox('Review and authorize this simulation event once.');card.append(outcome,amount.host,approve.host);
        const action=operation.status==='approved'?'post':operation.status==='unknown'?'reconcile':null;
        if(action)card.append(button(action==='post'?'Record simulated outcome':'Reconcile recorded unknown',()=>{
          const settled=Number(amount.input.value);if(!options.can_write||!approve.input.checked||!Number.isSafeInteger(settled))return;approve.input.checked=false;
          change('/ledger/'+action,{operation_id:operation.id,event_id:id('slev'),revision:operation.revision,outcome:outcome.value,settled_units:settled,authorized:true,notice:LEDGER},()=>ledger());
        }));
        if(['completed','partial'].includes(operation.status))card.append(button('Reverse the settled simulation once',()=>{
          if(!options.can_write||!approve.input.checked)return;approve.input.checked=false;
          change('/ledger/reverse',{operation_id:operation.id,event_id:id('slev'),revision:operation.revision,authorized:true,notice:LEDGER},()=>ledger());
        }));body.append(card);
      }
    }catch(error){if(valid(mark))failure(error);}
  }
  async function support(){
    epoch++;area();const mark=stamp();
    try{
      const [options,assistant]=await Promise.all([request('/support'),request('/support/assistant')]);if(!valid(mark))return;
      listLine(body,'Approved local guidance and deterministic JSON patch proposals. Optional generated guidance needs separate sharing consent; proposals require a separate review before application.');
      for(const doc of options.documents){const section=node('section');section.className='card';section.append(node('h3',doc.title),node('p',doc.text));body.append(section);}
      const drafts=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/drafts`,{silent:true});if(!valid(mark))return;
      const draftSelect=node('select');draftSelect.append(new Option('Select a private draft',''));for(const d of drafts.drafts)draftSelect.append(new Option(`${d.name} · revision ${d.revision}`,d.id));
      const versions=node('select');versions.append(new Option('Select a saved snapshot',''));
      const name=field('Proposed draft name'), description=field('Proposed description','textarea'), query=field('Optional replacement query');
      const consent=checkbox('Review these private draft changes before preparing a patch.');
      const preview=node('div');let selectedDraft=null, selectedSnapshot=null, proposal=null, selection=0;
      const goal=field('Public objective for optional generated guidance','textarea');goal.input.maxLength=500;
      const modelConsent=checkbox('Share only this public objective and the listed help documents with the configured assistant. Private draft content is excluded.');
      goal.input.addEventListener('input',()=>{modelConsent.input.checked=false;});
      if(assistant.available){body.append(goal.host,modelConsent.host,button('Generate guidance for review',()=>{
        if(!selectedDraft||!selectedSnapshot||!modelConsent.input.checked||!goal.input.value)return;
        modelConsent.input.checked=false;const turn=selection;
        change('/support/assistant',{draft_id:selectedDraft.id,snapshot_id:selectedSnapshot.id,objective:goal.input.value,authorized:true,notice:assistant.notice},value=>{
          if(turn!==selection)return;preview.replaceChildren();listLine(preview,value.model_generated?'Generated guidance is unverified. Review the source documents; no draft change was applied.':'Documentation guidance. Review the source documents; no draft change was applied.');listLine(preview,value.answer);
          for(const doc of value.source_documents||[])listLine(preview,doc.title+': '+doc.text);
          if(value.proposal){proposal=value.proposal;for(const patch of proposal.patch)listLine(preview,patch.path+': '+JSON.stringify(patch.value));const consent=checkbox('Apply this exact generated proposal to a new private draft revision.');preview.append(consent.host,button('Apply generated proposal',()=>{if(!proposal||!consent.input.checked)return;consent.input.checked=false;const p=proposal;proposal=null;change('/support/proposals/'+encodeURIComponent(p.id)+'/apply',{authorized:true,notice:APPLY},value=>{preview.replaceChildren();listLine(preview,'Reviewed private draft revision '+value.revision+' saved. No execution or publication occurred.');});}));}
        });
      }));}
      draftSelect.addEventListener('change',async()=>{
        const turn=++selection;proposal=null;modelConsent.input.checked=false;consent.input.checked=false;preview.replaceChildren();versions.replaceChildren(new Option('Select a saved snapshot',''));selectedDraft=null;selectedSnapshot=null;
        if(!draftSelect.value)return;
        try{const base=`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/drafts/${encodeURIComponent(draftSelect.value)}`;
          const [d,v]=await Promise.all([api(base,{silent:true}),api(base+'/snapshots',{silent:true})]);if(!valid(mark)||turn!==selection)return;
          selectedDraft=d.draft;name.input.value=d.draft.name;description.input.value=d.draft.description;
          for(const item of v.snapshots)if(item.active)versions.append(new Option(`Snapshot ${item.ordinal} · draft revision ${item.draft_revision}`,item.id));
        }catch(error){if(valid(mark))failure(error);}
      });
      versions.addEventListener('change',async()=>{
        const turn=++selection;proposal=null;modelConsent.input.checked=false;consent.input.checked=false;selectedSnapshot=null;preview.replaceChildren();query.input.value='';
        if(!versions.value||!selectedDraft)return;
        try{const v=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/drafts/${encodeURIComponent(selectedDraft.id)}/snapshots/${encodeURIComponent(versions.value)}`,{silent:true});if(valid(mark)&&turn===selection)selectedSnapshot=v.snapshot;}
        catch(error){if(valid(mark))failure(error);}
      });
      body.append(draftSelect,versions,name.host,description.host,query.host,consent.host,button('Prepare exact JSON patch',()=>{
        if(!options.can_edit||!selectedDraft||!selectedSnapshot||!consent.input.checked)return;
        const changes={name:name.input.value,description:description.input.value};
        if(query.input.value){const agents=selectedSnapshot.snapshot.definition.nodes.filter(n=>n.kind==='mcp'&&typeof n.data?.input?.query==='string');if(agents.length!==1){tell('A replacement query requires exactly one saved MCP query node.');return;}changes.literal_input={node_id:agents[0].id,input:{...agents[0].data.input,query:query.input.value}};}
        consent.input.checked=false;const turn=selection;
        change('/support/proposals',{draft_id:selectedDraft.id,snapshot_id:selectedSnapshot.id,snapshot_revision:selectedSnapshot.revision,draft_revision:selectedDraft.revision,changes,documents:['safe-change-review'],authorized:true,notice:PROPOSE},result=>{
          if(turn!==selection)return;proposal=result;preview.replaceChildren();listLine(preview,'Review the exact server-generated patch. Applying it changes one private draft revision only.');
          for(const patch of result.patch)listLine(preview,`${patch.op} ${patch.path}: ${JSON.stringify(patch.value)}`);
          const applyConsent=checkbox('Apply this exact patch to a new private draft revision.');preview.append(applyConsent.host,button('Apply reviewed patch',()=>{
            if(!proposal||!applyConsent.input.checked)return;applyConsent.input.checked=false;const p=proposal;proposal=null;
            change('/support/proposals/'+encodeURIComponent(p.id)+'/apply',{authorized:true,notice:APPLY},value=>{preview.replaceChildren();listLine(preview,`Private draft revision ${value.revision} saved. No execution or publication occurred.`);});
          }));
        });
      }),preview);
    }catch(error){if(valid(mark))failure(error);}
  }
  async function readiness(){
    epoch++;area();const mark=stamp();
    try{
      const report=await request('/readiness');if(!valid(mark))return;
      listLine(body,report.required_current_evidence_complete?'Current source checks are complete; independent review is still required.':'Not ready: required current operating evidence is missing.');
      listLine(body,'Declarations are unverified references. This view never enables commercial execution, payment or provider payouts.');
      const category=node('select');for(const check of report.checks){listLine(body,`${check.category}: ${check.state}${check.source_configured?'':' · source adapter not configured'}`);category.append(new Option(check.category,check.category));}
      const reference=field('Opaque review reference'), digest=field('Claimed SHA-256'), consent=checkbox('Record this declaration as unverified. It does not prove a contract or approval.');
      body.append(category,reference.host,digest.host,consent.host,button('Record declaration only',()=>{
        if(!report.can_declare||!consent.input.checked)return;consent.input.checked=false;
        change('/readiness/declarations',{category:category.value,reference:reference.input.value,sha256:digest.input.value,expires:Date.now()/1000+86400,authorized:true,notice:DECLARE},()=>readiness());
      }));
    }catch(error){if(valid(mark))failure(error);}
  }
  async function runtimeMeter(){
    epoch++;area();const mark=stamp();
    try{const value=await request('/runtime-meter');if(!valid(mark))return;
      listLine(body,'Runtime simulation only. No charge, payment, provider payout or ranking priority.');
      listLine(body,`Logical runs: ${value.operations}; dispatch attempts: ${value.attempts}; simulated units: ${value.simulated_units}; balanced: ${value.balanced?'yes':'no'}.`);
      body.append(button('Reconcile expired simulation records without retrying',()=>change('/runtime-meter/recover',{},runtimeMeter)));
      const enabled=checkbox('Enable simulation for newly authorized private runs in this workspace.');enabled.input.checked=false;
      const units=field('TEST_UNIT per successful logical run','number');units.input.min='1';units.input.max='1000';units.input.value='1';
      const max=field('Maximum new runs in this authorization','number');max.input.min='1';max.input.max='10000';max.input.value='100';
      const consent=checkbox('Authorize this bounded simulation policy for one hour.');
      for(const input of [enabled.input,units.input,max.input])input.addEventListener('input',()=>{consent.input.checked=false;});
      body.append(enabled.host,units.host,max.host,consent.host,button('Save runtime simulation policy',()=>{if(!consent.input.checked)return;const n=Number(units.input.value),m=Number(max.input.value);if(!Number.isSafeInteger(n)||!Number.isSafeInteger(m))return;consent.input.checked=false;change('/runtime-meter',{revision:value.policy?.revision||0,enabled:enabled.input.checked,units_per_success:n,max_runs:m,ttl_seconds:3600,authorized:true,notice:value.notice},runtimeMeter);}));
    }catch(error){if(valid(mark))failure(error);}
  }
  async function operatingPreparation(){
    epoch++;area();const mark=stamp();
    try{const value=await request('/operating-preparation');if(!valid(mark))return;
      listLine(body,'Integration preparation is separate from operating acceptance. This view does not open customer Workspace access or activate payments, providers or notifications.');
      for(const provider of value.identity_providers)listLine(body,`${provider.id}: ${provider.configured?'configured; operating verification pending':'configuration required'}`);
      for(const item of value.configuration)listLine(body,`${item.purpose}: ${item.state}${item.environment?' · '+item.environment:''}`);
      listLine(body,'Current operating evidence');for(const item of value.operating_evidence)listLine(body,`${item.category}: ${item.state}`);
      listLine(body,value.sandbox_payment_adapter_available?'Signed TEST_UNIT transport is available for isolated review.':'The sandbox transport is not configured in this application.');
      if(value.sandbox_payment_adapter_available)body.append(button('Open signed event sandbox',sandboxPayments));
    }catch(error){if(valid(mark))failure(error);}
  }
  async function sandboxPayments(){
    epoch++;area();const mark=stamp();
    try{const value=await request('/sandbox-payments');if(!valid(mark))return;
      listLine(body,'Signed event sandbox. TEST_UNIT only; no actual charge, payout, external provider or public payment webhook. Preparing and dispatching require separate approvals.');
      body.append(button('Read current sandbox history',sandboxPayments));
      for(const item of value.intents){
        const section=node('section');section.className='card';listLine(section,`${item.action} · ${item.units} TEST_UNIT · ${item.state} · ${item.event_reference}`);
        if(item.can_dispatch&&value.can_write){const consent=checkbox('Dispatch this exact signed sandbox event once.');section.append(consent.host,button('Dispatch sandbox event',()=>{if(!consent.input.checked)return;consent.input.checked=false;change('/sandbox-payments/dispatch',{intent_id:item.id,authorized:true,notice:value.execute_notice},sandboxPayments);}));}
        if(item.state==='prepared'&&value.can_write){const consent=checkbox('Withdraw this prepared sandbox event.');section.append(consent.host,button('Withdraw sandbox event',()=>{if(!consent.input.checked)return;consent.input.checked=false;change('/sandbox-payments/withdraw',{intent_id:item.id,authorized:true,notice:value.withdraw_notice},sandboxPayments);}));}
        body.append(section);
      }
      if(!value.can_write)return;
      const [agreements,summary]=await Promise.all([request('/agreements'),request('/agreements/summary')]);if(!valid(mark))return;
      const action=node('select');action.setAttribute('aria-label','Sandbox event action');action.append(new Option('Capture TEST_UNIT','capture'),new Option('Refund TEST_UNIT','refund'));
      const targets=node('select');targets.setAttribute('aria-label','Sandbox agreement or settlement');
      const amount=field('Sandbox integer TEST_UNIT','number');amount.input.min='1';amount.input.max='1000000000000';amount.input.value='1';
      const consent=checkbox('Prepare this exact TEST_UNIT event without dispatching it.');let choices=[],reference=id('sim');
      function selectTargets(){consent.input.checked=false;reference=id('sim');choices=action.value==='capture'?agreements.versions.filter(a=>a.status==='active'&&a.current_control_verified):summary.settlements.filter(a=>a.remaining.gross_units>0);targets.replaceChildren(new Option('Select a current target',''));for(const item of choices)targets.append(new Option(`${item.id} · revision ${item.revision}`,item.id));}
      action.addEventListener('change',selectTargets);for(const input of [targets,amount.input])input.addEventListener('input',()=>{consent.input.checked=false;reference=id('sim');});selectTargets();
      body.append(action,targets,amount.host,consent.host,button('Prepare sandbox event',()=>{const target=choices.find(a=>a.id===targets.value),n=Number(amount.input.value);if(!consent.input.checked||!target||!Number.isSafeInteger(n)||n<1)return;consent.input.checked=false;change('/sandbox-payments/prepare',{action:action.value,target_id:target.id,units:n,revision:target.revision,event_reference:reference,authorized:true,notice:value.prepare_notice},sandboxPayments);}));
    }catch(error){if(valid(mark))failure(error);}
  }
  async function open(workspace){
    leave();const value=typeof workspace==='string'?workspace:workspace?.id;if(!/^ws_[0-9a-f]{32}$/.test(value||'')||!identity())return;
    ws=value;session=identity();dialog=node('dialog');dialog.id='advancementAdminDialog';dialog.setAttribute('aria-labelledby','advancementAdminTitle');dialog.style.cssText='box-sizing:border-box;max-width:860px;width:min(94vw,860px);max-height:88vh;overflow:auto;padding:24px;border:1px solid var(--line);border-radius:18px;background:var(--panel,Canvas);color:var(--text,CanvasText)';
    const title=node('h2','Workspace simulation and support');title.id='advancementAdminTitle';const nav=node('div');nav.className='row';nav.style.cssText='display:flex;flex-wrap:wrap;gap:8px';
    nav.append(button('Shadow accounting',ledger),button('Runtime simulation',runtimeMeter),button('Draft support',support),button('Provider agreements',()=>{const selected=ws;leave();window.WorkspaceAgreementAdmin?.open(selected);}),button('Readiness',readiness),button('Integration preparation',operatingPreparation),button('Signed event sandbox',sandboxPayments),button('Close',leave));
    const header=node('div');header.style.cssText='position:sticky;top:0;z-index:2;background:var(--panel,Canvas);padding-bottom:12px';header.append(title,nav);status=node('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');body=node('div');body.style.overflowWrap='anywhere';dialog.append(header,status,body);dialog.addEventListener('cancel',leave);document.body.append(dialog);dialog.showModal();await ledger();
  }
  window.AdvancementAdmin={open,leave,onSession};
  window.addEventListener('pagehide',leave);
  setInterval(onSession,500);
})();
