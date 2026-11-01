/* Explicit customer links and HTTPS control proofs never grant staff roles. */
(() => {
  'use strict';
  let epoch=0, workspace=null, session='', dialog=null, plan=null, selected=null, busy=false, uncertain=false;
  const controllers=new Set();
  const current=()=>typeof token==='string'&&currentUser?`${token}|${currentUser.user_id}|${currentUser.role}`:'';
  const el=(tag,text='')=>{const node=document.createElement(tag);node.textContent=text;if(tag==='pre')node.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:12px';return node;};
  function leave(){epoch++;for(const c of controllers)c.abort();controllers.clear();if(dialog){dialog.close();dialog.remove();}dialog=null;workspace=null;session='';plan=null;selected=null;busy=false;uncertain=false;}
  function valid(mark){return !!dialog&&dialog.open&&mark===epoch&&session===current()&&state.tab==='workspaces'&&document.getElementById('workspaceSelect')?.value===workspace;}
  function field(label,type='text'){const wrap=el('label',label),input=el('input');wrap.style.cssText='display:block;margin:12px 0';input.type=type;input.maxLength=100;if(type!=='checkbox')input.style.cssText='display:block;box-sizing:border-box;width:100%;margin-top:6px';wrap.append(input);return[wrap,input];}
  function button(label,action){const node=el('button',label);node.type='button';node.className='btn';node.style.margin='4px 6px 4px 0';node.addEventListener('click',action);return node;}
  async function request(suffix,options={}){const c=new AbortController();controllers.add(c);try{return await api('/admin/api/workflow-workspaces/'+workspace+suffix,{...options,silent:true,signal:c.signal});}finally{controllers.delete(c);}}
  async function open(id){
    leave();if(!/^ws_[0-9a-f]{32}$/.test(id)||!current()||currentUser.role==='operator')return;
    workspace=id;session=current();dialog=el('dialog');dialog.className='workspace-dialog';dialog.style.cssText='box-sizing:border-box;max-width:760px;width:calc(100vw - 32px);max-height:86vh;overflow:auto;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:16px;padding:24px';
    const title=el('h2','Customer access and provider control'),close=button('Close',leave),status=el('p','Loading current workspace authority.');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    title.id='workspaceIdentityTitle';dialog.setAttribute('aria-labelledby',title.id);dialog.append(title,close,status);
    dialog.addEventListener('cancel',event=>{event.preventDefault();leave();});document.body.append(dialog);dialog.showModal();
    const [customerLabel,customer]=field('Customer ID'),role=el('select');role.add(new Option('Read workspace','viewer'));role.add(new Option('Run reviewed private tools','runner'));
    const [activeLabel,active]=field('Access active','checkbox');active.checked=true;
    const customerList=el('div'),claimList=el('div'),preview=el('pre'),authorityLabel=el('label'),authority=el('input');authority.type='checkbox';authority.checked=false;
    authorityLabel.append(authority,document.createTextNode('I authorize one HTTPS request to the exact challenge address to verify endpoint control.'));
    const [resourceLabel,resource]=field('Registered resource ID','number');resource.min='1';resource.step='1';
    const [targetLabel,target]=field('Transfer target workspace ID'),[offerLabel,offer]=field('Received transfer ID');
    let inputRevision=0;
    const showChallenge=value=>{if(value.profile!=='provider-https-control-v1'||!value.claim||!value.challenge)throw Error();plan=value;authority.checked=false;preview.textContent='Place this exact JSON at '+value.claim.challenge_url+' before verifying:\n'+JSON.stringify(value.challenge,null,2);status.textContent='A fresh challenge is required. No endpoint request was made.';};
    const mark=epoch;
    const controls=()=>{save.disabled=busy||uncertain||!/^cu_[0-9a-f]{32}$/.test(customer.value);prepare.disabled=busy||uncertain||!Number.isSafeInteger(Number(resource.value))||Number(resource.value)<1;verify.disabled=busy||uncertain||!plan||!authority.checked||plan.claim.expires*1000<=Date.now();};
    const failure=()=>{uncertain=true;controls();status.textContent='The change could not be confirmed. Refresh recorded state before making another decision. No request is automatically retried.';};
    async function refresh(){
      const currentMark=epoch;plan=null;authority.checked=false;preview.textContent='';busy=true;controls();try{
        const customers=await request('/customers');if(!valid(currentMark))return;
        if(customers.profile!=='customer-oidc-bff-v1')throw Error();customerList.replaceChildren();
        for(const row of customers.customers){const item=el('p',`${row.customer_id} · ${row.role} · ${row.active?'active':'inactive'} · revision ${row.revision}`);item.append(button('Review change',()=>{if(!valid(currentMark))return;selected=row;customer.value=row.customer_id;role.value=row.role;active.checked=!!row.active;controls();}));customerList.append(item);}
        const claims=await request('/provider-claims');if(!valid(currentMark))return;claimList.replaceChildren();
        for(const row of claims.claims){
          const expired=row.valid_until&&row.valid_until*1000<=Date.now(),item=el('p',`Resource ${row.resource_id} · ${expired?'expired':row.status} · revision ${row.revision}`);
          const mutate=async(suffix,body,challenge=false)=>{if(busy||uncertain||!valid(currentMark))return;busy=true;plan=null;authority.checked=false;preview.textContent='';controls();try{const result=await request('/provider-claims/'+suffix,{method:'POST',json:body});if(!valid(currentMark))return;await refresh();if(valid(currentMark)&&challenge)showChallenge(result);if(valid(currentMark)&&result.transfer_id){preview.textContent='Transfer ID: '+result.transfer_id+'\nThe receiving owner must accept this offer and publish a fresh challenge. Previous proof is retired.';}}catch{if(valid(currentMark))failure();}finally{if(valid(currentMark)){busy=false;controls();}}};
          item.append(button('Prepare fresh challenge',()=>mutate(row.id+'/rechallenge',{revision:row.revision},true)));
          if(!row.revoked)item.append(button('Revoke control proof',()=>mutate(row.id+'/revoke',{revision:row.revision})));
          if(!row.revoked&&row.status==='verified'&&!expired)item.append(button('Offer endpoint transfer',()=>{if(!/^ws_[0-9a-f]{32}$/.test(target.value)||target.value===workspace){status.textContent='Enter a different active target workspace ID before offering a transfer.';return;}return mutate(row.id+'/transfer',{revision:row.revision,target_workspace_id:target.value});}));claimList.append(item);
        }
        uncertain=false;status.textContent='Customer access is explicit. Endpoint control does not certify quality or grant execution authority.';
      }catch{if(valid(currentMark))failure();}finally{if(valid(currentMark)){busy=false;controls();}}
    }
    const save=button('Save customer access',async()=>{if(save.disabled||!valid(mark))return;const body={customer_id:customer.value,role:role.value,active:active.checked,revision:selected?.customer_id===customer.value?selected.revision:0};busy=true;controls();try{await request('/customers',{method:'POST',json:body});if(valid(mark)){selected=null;customer.value='';await refresh();}}catch{if(valid(mark))failure();}finally{if(valid(mark)){busy=false;controls();}}});
    const prepare=button('Prepare HTTPS challenge',async()=>{if(prepare.disabled||!valid(mark))return;const reviewedRevision=inputRevision;plan=null;authority.checked=false;preview.textContent='';busy=true;controls();try{const value=await request('/provider-claims/prepare',{method:'POST',json:{resource_id:Number(resource.value)}});if(!valid(mark)||reviewedRevision!==inputRevision)return;if(value.profile!=='provider-https-control-v1')throw Error();plan=value;preview.textContent='Place this exact JSON at '+value.claim.challenge_url+' before verifying:\n'+JSON.stringify(value.challenge,null,2);status.textContent='Preparation did not contact the provider. Review the address and authorization before verifying.';}catch{if(valid(mark))failure();}finally{if(valid(mark)){busy=false;controls();}}});
    const expire=button('Record expired proofs',async()=>{if(busy||uncertain||!valid(mark))return;busy=true;controls();try{await request('/provider-claims/expire',{method:'POST',json:{limit:50}});if(valid(mark))await refresh();}catch{if(valid(mark))failure();}finally{if(valid(mark)){busy=false;controls();}}});
    const accept=button('Accept transfer and prepare challenge',async()=>{if(busy||uncertain||!valid(mark)||!/^pt_[0-9a-f]{32}$/.test(offer.value))return;busy=true;plan=null;authority.checked=false;preview.textContent='';controls();try{const result=await request('/provider-claims/transfers/'+offer.value+'/accept',{method:'POST',json:{revision:1}});if(!valid(mark))return;await refresh();if(valid(mark))showChallenge(result);}catch{if(valid(mark))failure();}finally{if(valid(mark)){busy=false;controls();}}});
    const verify=button('Verify endpoint control',async()=>{if(verify.disabled||!valid(mark))return;const reviewed=plan;plan=null;authority.checked=false;preview.textContent='';busy=true;controls();try{await request('/provider-claims/verify',{method:'POST',json:{claim_id:reviewed.claim.id,revision:reviewed.claim.revision,authorized:true,notice:'provider-https-control-v1'}});if(valid(mark))await refresh();}catch{if(valid(mark))failure();}finally{if(valid(mark)){busy=false;controls();}}});
    customer.addEventListener('input',()=>{selected=null;controls();});resource.addEventListener('input',()=>{inputRevision++;plan=null;authority.checked=false;preview.textContent='';controls();});authority.addEventListener('change',controls);
    dialog.append(el('h3','Customer access'),el('p','The customer signs in with Google or GitHub and shares their customer ID with the owner. Email and provider roles are never matched to staff accounts.'),customerLabel,role,activeLabel,save,customerList,
      el('h3','Provider HTTPS control'),el('p','Only the registered public HTTPS origin and fixed well-known path are checked. A successful challenge is not a quality report.'),resourceLabel,prepare,preview,authorityLabel,verify,targetLabel,el('p','Offering a transfer retires the previous proof immediately. A current owner of the target workspace must accept within ten minutes and verify a new domain nonce.'),offerLabel,accept,expire,claimList,button('Refresh recorded state',refresh));
    controls();await refresh();
  }
  window.addEventListener('pagehide',leave);window.WorkspaceIdentityAdmin={open,leave,onSession:()=>{if(session&&session!==current())leave();}};
})();
