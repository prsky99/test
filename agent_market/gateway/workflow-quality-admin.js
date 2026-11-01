/* Scoped staff review records do not create expert credentials or holdout proof. */
(() => {
  'use strict';
  const PROFILE='workspace-quality-review-v1';
  let dialog=null,host=null,message=null,ws='',session='',epoch=0,busy=false;
  const identity=()=>typeof token==='string'&&typeof currentUser!=='undefined'&&currentUser?`${token}|${currentUser.user_id}|${currentUser.role}`:'';
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const button=(label,action)=>{const b=el('button',label);b.type='button';b.className='btn';b.addEventListener('click',action);return b;};
  const field=(label,type='text')=>{const wrap=el('label',label),input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.autocomplete='off';wrap.append(input);return {wrap,input};};
  const consent=label=>{const wrap=el('label'),input=el('input');input.type='checkbox';input.checked=false;wrap.append(input,' ',el('span',label));return {wrap,input};};
  const say=text=>{if(message)message.textContent=text;};
  const mark=()=>({epoch,ws,session});
  const valid=m=>dialog?.open&&m.epoch===epoch&&m.ws===ws&&m.session===session&&session===identity();
  function leave(){epoch++;busy=false;session='';ws='';if(dialog){dialog.close();dialog.remove();dialog=null;}host=null;message=null;}
  function onSession(){const selected=document.getElementById('workspaceSelect');if(session&&(identity()!==session||(selected?.value&&selected.value!==ws)))leave();}
  async function request(path,options={}){const r=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/quality${path}`,{...options,silent:true});if(r?.ok!==true||r.profile!==PROFILE)throw new Error('profile');return r.result;}
  async function post(path,body,after){if(busy)return;busy=true;const m=mark();say('Recording one explicitly reviewed request.');try{const r=await request(path,{method:'POST',json:body});if(valid(m))await after(r);}catch(error){if(valid(m))say('The result is not confirmed. Read current assignment state; no request is retried automatically.');}finally{if(valid(m))busy=false;}}
  function line(parent,text){parent.append(el('p',text));}
  async function assignments(){
    epoch++;busy=false;host.replaceChildren();const m=mark();
    try{const [options,rows]=await Promise.all([request('/options'),request('/assignments')]);if(!valid(m))return;
      line(host,'Application pre-run reservation and staff judgments. Expert qualifications, source review, unseen status and actual independence need separate evidence. No model or provider is called here.');
      line(host,`Qualification adapter: ${options.qualification_source_configured?'configured':'not configured'}; source verifier: ${options.source_verifier_configured?'configured':'not configured'}.`);
      if(options.can_manage)host.append(button('Reserve a new case before execution',()=>reserveForm(options)));
      for(const row of rows){const card=el('section');card.className='card';line(card,`${row.id} · ${row.run_id?'retained run bound':'awaiting a new manual private run'}`);line(card,`Review accounts ${row.reviewer_ids.join(', ')}; adjudicator ${row.adjudicator_user_id}.`);card.append(button('Read assignment state',()=>status(row.id,options)));
        if(options.can_manage&&!row.run_id){const run=field('New retained private run ID');card.append(run.wrap,button('Bind retained run created after reservation',()=>post('/assignments/'+row.id+'/bind',{run_id:run.input.value,authorized:true,notice:options.notices.bind},()=>assignments())));}
        if(row.run_id&&[...row.reviewer_ids,row.adjudicator_user_id].includes(currentUser.user_id)){const c=consent('Open assigned private output and record this disclosure.');card.append(c.wrap,button('Inspect assigned output',()=>{if(!c.input.checked)return;c.input.checked=false;post('/assignments/'+row.id+'/inspect',{authorized:true,notice:options.notices.inspect},result=>reviewForm(row,result,options));}));}
        host.append(card);
      }
      if(!rows.length)line(host,'No reserved cases. A historical run cannot be backdated into a new reservation.');
    }catch(error){if(valid(m))say('Current review scope is unavailable. Reopen after checking the session and membership.');}
  }
  async function reserveForm(options){
    epoch++;busy=false;host.replaceChildren();const m=mark();
    const drafts=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/drafts`,{silent:true});if(!valid(m))return;
    const ds=el('select'),vs=el('select');ds.append(new Option('Select private draft',''));vs.append(new Option('Select active saved snapshot',''));for(const d of drafts.drafts)ds.append(new Option(d.name,d.id));
    ds.addEventListener('change',async()=>{const id=ds.value;vs.replaceChildren(new Option('Select active saved snapshot',''));if(!id)return;const r=await api(`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/drafts/${encodeURIComponent(id)}/snapshots`,{silent:true});if(valid(m)&&ds.value===id)for(const v of r.snapshots)if(v.active)vs.append(new Option(`Snapshot ${v.ordinal}`,v.id));});
    const dataset=field('Frozen dataset SHA-256'),task=field('Frozen case SHA-256'),source=field('Separate source bundle SHA-256'),ref=field('Opaque source reference');
    const executor=el('select'),adjudicator=el('select');for(const p of options.participants){executor.append(new Option(`Executor account ${p.id}`,String(p.id)));adjudicator.append(new Option(`Adjudicator account ${p.id}`,String(p.id)));}
    const reviewers=el('fieldset');reviewers.append(el('legend','Select two to four separate review accounts'));const choices=[];for(const p of options.participants){const c=consent(`Review account ${p.id}`);choices.push([p.id,c]);reviewers.append(c.wrap);}
    const c=consent('Reserve these exact hashes and separated account roles before creating the measured run. This is not independent holdout chronology proof.');
    host.append(ds,vs,dataset.wrap,task.wrap,source.wrap,ref.wrap,executor,reviewers,adjudicator,c.wrap,button('Reserve pre-run case',()=>{
      if(!c.input.checked)return;c.input.checked=false;
      post('/assignments',{draft_id:ds.value,snapshot_id:vs.value,dataset_hash:dataset.input.value,case_hash:task.input.value,source_hash:source.input.value,source_ref:ref.input.value,executor_user_id:Number(executor.value),reviewer_ids:choices.filter(([,choice])=>choice.input.checked).map(([id])=>id),adjudicator_user_id:Number(adjudicator.value),authorized:true,notice:options.notices.reserve},()=>assignments());
    }),button('Back to assignments',assignments));
  }
  async function status(id,options){
    const m=mark();try{const r=await request('/assignments/'+id);if(!valid(m))return;line(host,`${id}: ${r.status}; judgments ${r.review_count}; disagreement ${r.disagreement?'yes':'no'}; adjudicated ${r.adjudicated?'yes':'no'}; qualified operating evidence ${r.qualified_operating_evidence?'yes':'not established'}.`);for(const review of r.reviews)line(host,`Account ${review.user_id}: ${Object.entries(review.scores).map(([key,value])=>key+'='+String(value??'unassessed')).join('; ')}`);}catch(error){if(valid(m))say('Retained proof or current access is unavailable.');}
  }
  function reviewForm(assignment,result,options){
    epoch++;busy=false;host.replaceChildren();line(host,`Assigned run ${assignment.run_id}. Source reference ${result.source_ref}; source hash ${result.source_hash}. Separate source material must be reviewed independently.`);
    for(const item of Array.isArray(result.output?.content)?result.output.content:[])if(item?.type==='text'&&typeof item.text==='string')line(host,item.text);
    const fields={};for(const rubric of result.rubric){const label=el('label',rubric.question),select=el('select');select.append(new Option('Not assessed',''));for(const score of [0,1,2])select.append(new Option(String(score),String(score)));label.append(select);host.append(label);fields[rubric.id]=select;}
    const observed=field('Source observation UTC (YYYY-MM-DDTHH:MM:SSZ)'),notes=field('Assessment notes or adjudication reason','textarea');
    const source=consent('I reviewed the separately referenced source material.'),conflict=consent('I declare no conflict with this execution or assessment.'),approve=consent('Record this explicit staff judgment. This does not certify expert qualification or provider truth.');
    host.append(observed.wrap,notes.wrap,source.wrap,conflict.wrap,approve.wrap,button(assignment.adjudicator_user_id===currentUser.user_id?'Record separate adjudication':'Record assigned review',()=>{
      if(!approve.input.checked||!source.input.checked||!conflict.input.checked)return;approve.input.checked=false;const scores={};for(const[key,select]of Object.entries(fields))scores[key]=select.value===''?null:Number(select.value);
      if(assignment.adjudicator_user_id===currentUser.user_id){post('/assignments/'+assignment.id+'/adjudicate',{scores,reason:notes.input.value,authorized:true,notice:options.notices.adjudicate},()=>assignments());return;}
      const time=Date.parse(observed.input.value);if(!Number.isFinite(time)||!observed.input.value.endsWith('Z')){say('Provide an explicit finite UTC source observation time.');return;}
      post('/assignments/'+assignment.id+'/review',{scores,source_observed_at:time/1000,source_reviewed:true,no_conflict_declared:true,notes:notes.input.value,authorized:true,notice:options.notices.review},()=>assignments());
    }),button('Back to assignments',assignments));
  }
  async function open(workspace){leave();const value=typeof workspace==='string'?workspace:workspace?.id;if(!/^ws_[0-9a-f]{32}$/.test(value||'')||!identity())return;ws=value;session=identity();dialog=el('dialog');dialog.id='workflowQualityDialog';dialog.setAttribute('aria-label','Scoped quality review');dialog.style.width='min(94vw,860px)';dialog.style.maxWidth='860px';message=el('p');message.setAttribute('role','status');host=el('div');dialog.append(el('h2','Pre-run reservation and staff review'),button('Refresh assignments',assignments),button('Close',leave),message,host);dialog.addEventListener('cancel',leave);document.body.append(dialog);dialog.showModal();await assignments();}
  window.WorkflowQualityReviewAdmin={open,leave,onSession};window.addEventListener('pagehide',leave);setInterval(onSession,500);
})();
