/* A task-oriented presentation over the existing reviewed authoring APIs.
   Selection never saves, spends credits, shares input or executes an agent. */
const humanStudio = {screen:'create', kind:'custom', phase:'plan', ready:false, confirm:null, lastPlan:'',operation:'',stepsExpanded:false};
const humanEl = (tag, copy, className) => {
  const element = document.createElement(tag);
  if (copy !== undefined) element.textContent = copy;
  if (className) element.className = className;
  return element;
};
function humanButton(copy, action, className='') {
  const button = humanEl('button',copy,className); button.type='button'; button.onclick=action; return button;
}
function humanMove(id, parent, label=false) {
  const element=$(id); if(!element) return;
  const wrapper=label ? element.closest('label') : null;
  const directLabel=document.querySelector('label[for="'+id+'"]');
  if(directLabel && !wrapper) parent.append(directLabel);
  parent.append(wrapper||element); return element;
}
function humanDetails(title, parent, ...elements) {
  const details=humanEl('details',undefined,'human-details'); details.append(humanEl('summary',title));
  for(const item of elements) if(item) details.append(item); parent.append(details); return details;
}
function humanHelp(title, copy, parent, id) {
  const details=humanEl('details',undefined,'context-help');if(id)details.id=id;
  details.append(humanEl('summary',title),humanEl('div',copy,'context-help-body'));parent.append(details);return details;
}
function humanIcon(name) {
  const paths={sparkles:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z',arrow:'M5 12h14m-6-6 6 6-6 6',check:'m5 12 4 4L19 6'};
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','aria-hidden':'true',class:'lucide'}))svg.setAttribute(key,value);
  const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[name]||paths.arrow);svg.append(path);return svg;
}
function humanNavigate(screen, focus=true) {
  if(!['create','templates','library','builder'].includes(screen))return;
  humanStudio.screen=screen;
  const hash=screen==='builder'?'workflow':screen;
  if(location.hash!=='#'+hash)location.hash=hash;
  humanStudioSync();
  if(focus){const heading=$('human-'+screen)?.querySelector('h1,h2');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true})}window.scrollTo({top:0,behavior:'instant'})}
}
function humanConfirm(title, copy, fields, consent, action, confirmCopy='Continue') {
  if(busy)return;
  const dialog=$('human-confirm');
  $('human-confirm-title').textContent=title;$('human-confirm-copy').textContent=copy;
  $('human-confirm-fields').replaceChildren();
  for(const [label,value] of fields){$('human-confirm-fields').append(humanEl('dt',label),humanEl('dd',String(value)))}
  $('human-confirm-label').textContent=consent;$('human-confirm-check').checked=false;
  $('human-confirm-yes').textContent=confirmCopy;$('human-confirm-yes').disabled=true;
  dialog.dataset.action=confirmCopy.startsWith('Save')?'save':confirmCopy.startsWith('Run')?'run':'download';
  humanStudio.confirm=()=>{humanStudio.operation=confirmCopy.startsWith('Run')?'run':confirmCopy.startsWith('Save')?'save':'download';action()};dialog.returnValue='cancel';dialog.showModal();
}
function humanFields(definition) {
  return ordered(definition.nodes).map((step,index)=>['Step '+(index+1),
    (candidates.find(c=>c.resource_id===step.resource_id&&c.contract_id===step.contract_id)?.name||taskLabel(step.contract_id))+' — '+
    (step.input?.query||'Uses the result from an earlier step')]);
}
let humanActiveFlows=0;
function humanSaveCustom() {
  const chosen=review;if(!chosen||busy||!canEdit||uncertain)return;
  const charge=chosen.credit_charge??1;
  humanConfirm('Save your workflow',charge?'This saves your workflow and uses '+charge+' credit'+(charge===1?'':'s')+'. Your remaining balance will be '+(creditBalance-charge).toLocaleString('en-US')+'.':'This update uses no additional credits.',
    [['Workflow',chosen.name||$('name').value],...humanFields(chosen.definition)],
    'Save these reviewed steps using the credits shown above.',
    ()=>work(async()=>{
      if(review!==chosen)throw Error();
      const result=await api(typed+'/commits',{review_id:chosen.review_id,authorized:true,notice:chosen.notice});
      await listing();$('saved').value=result.flow.id;
      applyFlow((await api(typed+'/flows/'+result.flow.id)).flow);await history(false);
      // listing() above already refreshed the balance after the commit.
      humanStudio.phase='try';stage='test';humanNavigate('builder');
      try{sessionStorage.removeItem('workspace-objective-draft')}catch{}
      return charge?'Workflow saved. '+charge+' credit'+(charge===1?'':'s')+' used.':'Workflow changes saved.';
    }),charge?'Save · '+charge+' credit'+(charge===1?'':'s'):'Save changes');
}
function humanTryCustom() {
  if(busy||!flow||dirty||!canRun||uncertain)return;
  work(async()=>{
    const current=flow;const prepared=await api(typed+'/flows/'+flow.id+'/prepare',{revision:flow.revision});ticket=prepared;$('test-review').textContent=JSON.stringify(prepared.review,null,2);
    // Defer opening until the shared work lock has released.
    setTimeout(()=>{
      if(busy||flow!==current||ticket!==prepared)return;
      humanConfirm('Try your workflow','This makes one real request through each listed agent. It does not use another workflow credit.',
        // Reviewed capability adapters disclose how inputs are limited before any call.
        [...humanFields({nodes:prepared.review.nodes}),...[...new Set((prepared.review.destinations||[]).map(d=>d.input_notice).filter(Boolean))].map(notice=>['Provider notice',notice])],
        'Send these inputs and the connected results to the listed agents for this test.',()=>{
          if(ticket!==prepared||flow!==current)return;
          $('run-consent').checked=true;humanStudio.phase='results';stage='test';humanNavigate('builder');sync();$('run').click();
        },'Run workflow');
    },0);
  });
}
function humanSaveTemplate() {
  if(busy||!hubProduct||!canEdit||uncertain)return;
  let inputs;try{inputs=hubInputs()}catch{return}const name=$('hub-name').value.trim();if(!name){$('hub-name').reportValidity();$('hub-name').focus();return}
  work(async()=>{
    hubReview=(await api(hubBase+'/prepare',{template_id:hubProduct.id,definition_hash:hubProduct.definition_hash,name,inputs,draft_id:hubDraft?.id||null,revision:hubDraft?.revision||0})).review;
    const chosen=hubReview;const charge=chosen.credit_charge??1;
    setTimeout(()=>{
      if(busy||chosen!==hubReview)return;
      humanConfirm('Save your workflow',charge?'Saving uses '+charge+' credit'+(charge===1?'':'s')+'. Remaining balance: '+(creditBalance-charge)+'.':'These changes use no additional credits.',
        [['Workflow',name],...Object.entries(inputs).map(([k,v])=>[humanInputLabel(k),v])],
        'Save these reviewed template settings using the credits shown above.',()=>work(async()=>{
          if(hubReview!==chosen)throw Error();
          const result=await api(hubBase+'/drafts',{proposal:chosen.proposal,signature:chosen.signature,authorized:true,notice:chosen.notice});
          hubOpen(hubProduct,result.draft);humanStudio.phase='try';
          await Promise.all([loadHub(),creditStatus()]);humanNavigate('builder');
        }),charge?'Save · '+charge+' credit'+(charge===1?'':'s'):'Save changes');
    },0);
  });
}
function humanTryTemplate() {
  if(busy||!hubDraft||hubDirty||hubTesting||uncertain)return;
  humanConfirm('Try your workflow',hubProduct.product?'This sends your saved public research inputs to the template’s agents. A verified alternative may be used when an eligible failure occurs.':'This sends the published default inputs shown in this workflow to its listed agents.',
    [['Agents',hubProduct.nodes.filter(n=>n.type==='agent').map(n=>n.name).join(', ')],...(hubProduct.product?Object.entries(hubDraft.inputs).map(([k,v])=>[humanInputLabel(k),v]):hubProduct.nodes.filter(n=>n.type==='agent').flatMap(n=>Object.entries(n.data?.input||{}).map(([k,v])=>[n.name+' · '+humanInputLabel(k),typeof v==='object'?JSON.stringify(v):String(v)])))],
    hubProduct.product?'Send these public inputs and allow one verified alternative source if needed for this run.':'Send the published default inputs to the listed agents for this run.',()=>{
      $('hub-run-consent').checked=true;humanStudio.phase='results';humanNavigate('builder');sync();$('hub-run').click();
    },'Run workflow');
}
function humanDownloadCustom() {
  if(busy||!flow||dirty||!canManage||lastRun?.status!=='succeeded'||uncertain)return;
  humanStudio.phase='download';humanNavigate('builder');$('origin').focus();
}
function humanPrepareDownload() {
  if(busy||!flow||dirty||lastRun?.status!=='succeeded'||!canManage||uncertain)return;
  const supplied=$('origin').value.trim();let origin;
  try{origin=new URL(supplied)}catch{$('origin').setCustomValidity('Enter the HTTPS address where your app will run.');$('origin').reportValidity();return}
  $('origin').setCustomValidity('');
  if(origin.protocol!=='https:'||origin.origin!==supplied||origin.username||origin.password){$('origin').setCustomValidity('Use an HTTPS origin without a path, such as https://my-app.example.');$('origin').reportValidity();return}
  const current=flow;const tested=lastRun;
  humanConfirm('Prepare your web app','Authorize this tested version for the app address below. Access lasts one hour, with up to 5 tasks per minute and 20 per day. Setup instructions are included in the ZIP.',
    [['App address',supplied],['Workflow',flow.name]],
    'Release this tested version and authorize this app address with the limits above.',()=>work(async()=>{
      if(flow!==current||lastRun!==tested||dirty)throw Error();
      // Every mutation follows this fresh approval; uncertain responses stop here.
      if(!release)release=(await api(scope()+'/releases',{run_id:lastRun.id,ttl_seconds:3600})).release;
      const result=await api(scope()+'/releases/'+release.id+'/deployments',{allowed_origins:[supplied],ttl_seconds:3600,minute_limit:5,day_limit:20,authorized:true,notice:'workspace-sdk-deployment-v2'});
      $('download').replaceChildren();downloadButton(result.deployment);
    }), 'Authorize app');
}
function humanInputLabel(name) {
  return ({query:'What should it search for?',query_a:'First research topic',query_b:'Second research topic',limit:'Number of results'})[name]||name.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
}
function humanStudioBuild() {
  const main=document.querySelector('main');main.classList.add('human-studio');
  const preserved=[...main.children];const parking=humanEl('div');parking.hidden=true;parking.id='human-preserved';
  for(const element of preserved)parking.append(element);
  main.append(parking);
  const header=humanEl('header',undefined,'human-page-header');header.append(humanEl('p','YOUR WORKSPACE','human-eyebrow'));
  const row=humanEl('div',undefined,'human-header-row');row.append(humanEl('h1','Make work flow.'));
  const balance=humanEl('a','Checking credits…','human-credit-link');balance.id='human-credit-balance';balance.href='/customer/plan';row.append(balance);header.append(row,humanEl('p','Describe a task. Review the steps. Put your workflow to work.','human-lede'));
  main.append(header);
  const nav=humanEl('nav',undefined,'human-local-nav');nav.setAttribute('aria-label','Workflow workspace');
  for(const [key,label] of [['create','Create with AI'],['templates','Templates'],['library','My workflows']]){
    const button=humanButton(label,()=>humanNavigate(key));button.id='human-nav-'+key;nav.append(button);
  }main.append(nav);
  const enrollment=humanEl('p',undefined,'human-enrollment');enrollment.id='human-enrollment';enrollment.append(humanEl('span','Before creating a workflow, review the plan and credit terms. '));const planLink=humanEl('a','Review plan and get started');planLink.href='/customer/plan?workspace='+ws;enrollment.append(planLink);main.append(enrollment);
  const notice=humanEl('div',undefined,'human-notice');const busyCopy=humanEl('p');busyCopy.id='human-busy-copy';busyCopy.setAttribute('role','status');notice.append(busyCopy);humanMove('status',notice);humanMove('retry-load',notice);humanMove('signin',notice);main.append(notice);
  const create=humanEl('section',undefined,'human-screen');create.id='human-create';
  const columns=humanEl('div',undefined,'human-create-grid');const form=humanEl('div',undefined,'human-composer');
  form.append(humanEl('div','START WITH AN IDEA','human-eyebrow'),humanEl('h2','What would you like to do?'),humanEl('p','Describe a public research, news or documentation task. We’ll suggest the steps for you. AI suggestions can take a few seconds and can be wrong, so review each step before you save.','human-muted'));
  for(const id of ['name','pearl-flow-preview','flow-count','step-editor'])humanMove(id,parking);
  const editor=$('editor');editor.replaceChildren(...[...editor.children].filter(n=>!['name','pearl-flow-preview','flow-count','step-editor'].includes(n.id)));
  // The named fields were kept in the parking tree below before replacement.
  columns.append(form);create.append(columns);main.append(create);
  const builder=humanEl('section',undefined,'human-screen');builder.id='human-builder';
  const toolbar=humanEl('div',undefined,'human-builder-toolbar');toolbar.append(humanButton('← Back to my workflows',()=>humanNavigate('library'),'human-link-button'));
  const heading=humanEl('h2','Your workflow');heading.id='human-builder-title';toolbar.append(heading);builder.append(toolbar);
  const progress=humanEl('ol',undefined,'human-progress');progress.setAttribute('aria-label','Workflow progress');
  for(const copy of ['Review','Try it','Use it'])progress.append(humanEl('li',copy));progress.id='human-progress';builder.append(progress);
  const custom=humanEl('div');custom.id='human-custom-builder';builder.append(custom);
  const template=humanEl('div');template.id='human-template-builder';builder.append(template);main.append(builder);
  const templates=humanEl('section',undefined,'human-screen');templates.id='human-templates';main.append(templates);
  const library=humanEl('section',undefined,'human-screen');library.id='human-library';main.append(library);
  main.append(parking);
  // Restore reusable controls without cloning identifiers or action listeners.
  humanMove('editor',form);
  for(const heading of editor.querySelectorAll('h2'))heading.remove();
  for(const p of [...editor.children])if(p.tagName==='P'&&p.textContent.startsWith('Suggestions require your review'))p.remove();
  $('objective').rows=4;$('objective').placeholder='Find recent battery recycling research, then find supporting sources.';
  document.querySelector('label[for="objective"]').textContent='Your task';
  $('objective-help').textContent='Currently supports public research, news and documentation. You can edit the proposed steps before saving.';
  const modelConsent=$('model-consent').closest('label');modelConsent.lastChild.textContent=' Share this public description and available agent capabilities with the AI suggestion service.';
  $('model').textContent='Create my workflow';$('model').classList.add('human-primary');$('model').prepend(humanIcon('sparkles'));
  const examples=humanEl('div',undefined,'human-examples');examples.setAttribute('aria-label','Example workflow ideas');
  for(const [label,goal,needs] of [['Research a topic','Find public battery recycling research in two connected steps.','docs.search.v1'],['Find recent news','Find artificial intelligence news, then supporting documentation in two steps.','news.search.v1 docs.search.v1'],['Explore two topics','Find documentation for Docker and Kubernetes independently.','docs.search.v1']]){const example=humanButton(label,()=>{$('objective').value=goal;invalidate();$('objective').focus()});example.dataset.contracts=needs;examples.append(example)}
  try{if(Array.isArray(candidates))humanExampleAvailability(candidates)}catch{}
  editor.insertBefore(examples,$('objective-help'));humanMove('objective-help',parking);
  const manual=humanButton('Build step by step',humanManual,'human-link-button');manual.id='human-manual';editor.append(manual);const availability=humanButton('Refresh availability',()=>{$('refresh').click()},'human-link-button');availability.id='human-check-availability';editor.append(availability);
  const secondaryActions=humanEl('div',undefined,'layout-actions human-secondary-actions');editor.append(secondaryActions);secondaryActions.append(manual,availability);
  humanHelp('How suggestions work','Suggestions use available verified connections for public research, news and documentation. Review the proposed steps before saving or running.',editor,'human-ai-help');
  const aside=humanEl('aside',undefined,'human-start-guide');aside.append(humanEl('h3','From idea to something useful'));
  const guide=humanEl('ol');for(const [title,copy] of [['Tell us the goal','Start with a sentence. No agent setup required to describe your idea.'],['Make it yours','See the steps, change the inputs and approve the exact credit use.'],['Try it, then use it','Check real results before downloading your app.']]){const li=humanEl('li');li.append(humanEl('strong',title),humanEl('p',copy));guide.append(li)}aside.append(guide,humanButton('Prefer a ready-made workflow? Browse templates →',()=>humanNavigate('templates'),'human-link-button'));columns.append(aside);
  const reviewPanel=$('review-panel');custom.append(reviewPanel);
  reviewPanel.querySelector('h2').textContent='Review your workflow';
  humanMove('name',reviewPanel);$('name').required=true;humanMove('pearl-flow-preview',reviewPanel);humanMove('flow-count',reviewPanel);const showSteps=humanButton('Show all steps',()=>{humanStudio.stepsExpanded=!humanStudio.stepsExpanded;humanStudioSync()});showSteps.id='human-show-steps';showSteps.setAttribute('aria-controls','pearl-flow-preview');reviewPanel.append(showSteps);humanMove('step-editor',reviewPanel);
  $('step-editor').querySelector('summary').textContent='Change a step';humanMove('review',parking);
  const expert=humanDetails('Advanced workflow details',reviewPanel,$('proposal-detail'),$('support-panel'));
  expert.classList.add('human-expert');
  const actions=humanEl('div',undefined,'human-action-bar');
  const save=humanButton('Save workflow',humanSaveCustom,'human-primary');save.id='human-save';
  const tryButton=humanButton('Try workflow',humanTryCustom,'human-primary');tryButton.id='human-try';
  const download=humanButton('Download app',humanDownloadCustom,'human-primary');download.id='human-download';
  const refresh=humanButton('Check latest results',()=>work(()=>history()));refresh.id='human-refresh';actions.append(save,tryButton,download,refresh,humanButton('View or edit steps',()=>{humanStudio.phase='plan';humanStudioSync();$('step-editor').open=true;$('step-editor').scrollIntoView({block:'center'})}));custom.append(actions);
  // Legacy action controls remain available to the reviewed controller, not as a second user journey.
  for(const id of ['save-consent','save','review-summary'])humanMove(id,parking,id.endsWith('consent'));
  humanMove('test-panel',parking);humanMove('export-panel',custom);humanMove('results-panel',custom);
  $('results-panel').querySelector('h2').textContent='Your results';
  const downloadPanel=$('export-panel');downloadPanel.querySelector('h2').textContent='Use your workflow in an app';
  for(const child of [...downloadPanel.children])if(!['origin','download'].includes(child.id)&&child.tagName!=='H2'&&!(child.tagName==='LABEL'&&child.htmlFor==='origin'))parking.append(child);
  const info=humanEl('p','Enter the HTTPS address where your app will run. We’ll prepare a one-hour authorization. The ZIP includes the app and its setup guide.');downloadPanel.prepend(info);
  document.querySelector('label[for="origin"]').textContent='Your app address';$('origin').placeholder='https://my-app.example';$('origin').oninput=()=>{$('origin').setCustomValidity('');$('deploy-consent').checked=false;sync()};
  downloadPanel.append(humanButton('Prepare download',humanPrepareDownload,'human-primary'));
  const revoke=humanDetails('Manage app access',downloadPanel,$('revoke'));revoke.querySelector('button').textContent='Revoke app access';
  humanMove('hub-editor',template);$('hub-name').required=true;humanMove('template-hub',templates);
  $('template-hub').querySelector('h2').textContent='Start from a template';
  const templateIntro=$('template-hub').querySelector('.workspace-studio-heading')?.nextElementSibling;if(templateIntro)templateIntro.textContent='Choose a template to use or customize.';
  const templateCount=humanEl('div',undefined,'context-help-row human-count-row');$('hub-state').before(templateCount);templateCount.append($('hub-state'),$('hub-search-help'));
  humanMove('hub-saved',parking,true);humanMove('hub-load',parking);humanMove('hub-review-box',parking);
  $('hub-title').hidden=true;
  const templateSafety=humanEl('details',undefined,'human-details');templateSafety.id='human-template-safety';templateSafety.append(humanEl('summary','How this template works'));
  const fallbackCopy=$('hub-agents').nextElementSibling;if(fallbackCopy)templateSafety.append(fallbackCopy);
  templateSafety.append($('hub-agents'));$('hub-editor').append(templateSafety);
  for(const paragraph of [...$('hub-editor').children].filter(n=>n.tagName==='P'&&n.textContent.startsWith('Use public English')))paragraph.textContent='Use public English search terms. Never include private information.';
  $('hub-review').textContent='Save workflow';$('hub-review').onclick=humanSaveTemplate;$('hub-review').classList.add('human-primary');
  const templateTry=humanButton('Try workflow',humanTryTemplate,'human-primary');templateTry.id='human-template-try';$('hub-test').prepend(templateTry);
  humanMove('hub-run-consent',parking,true);humanMove('hub-run',parking);$('hub-history').textContent='Check latest results';$('hub-download').textContent='Download app';$('hub-download').classList.add('human-primary');
  humanMove('library',library);$('library').querySelector('h2').textContent='My workflows';
  const customHeading=humanEl('h3','Custom workflows');customHeading.id='human-custom-library-heading';$('workflow-cards').before(customHeading);
  humanMove('saved',parking);humanMove('load',parking);humanMove('retire',parking);humanMove('history',parking);
  const templateHeading=humanEl('h3','Saved template workflows');templateHeading.id='human-template-library-heading';$('library').append(templateHeading);
  const stored=humanEl('div');stored.id='human-template-cards';$('library').append(stored);
  const empty=humanEl('div',undefined,'human-empty');empty.id='human-library-empty';empty.append(humanIcon('sparkles'),humanEl('h3','Your first workflow starts with an idea.'),humanEl('p','Create one with AI or choose a template. Saved workflows will appear here.'),humanButton('Create a workflow',()=>humanNavigate('create'),'human-primary'),humanButton('Browse templates',()=>humanNavigate('templates')));$('library').append(empty);
  $('library-empty').textContent='No workflows match that name. Try a different search.';
  $('a2a-panel').querySelector('summary').textContent='Long-running agent tasks';library.append($('a2a-panel'));
  const advanced=humanEl('div');advanced.id='human-more';advanced.append($('feedback-panel'));library.append(advanced);
  const manage=humanDetails('Workflow settings',custom,$('retire'));manage.id='human-workflow-settings';$('retire').textContent='Archive this workflow';
  const dialogs=[...parking.querySelectorAll('dialog')];for(const dialog of dialogs)main.append(dialog);
  const confirm=humanEl('dialog',undefined,'human-confirm');confirm.id='human-confirm';confirm.setAttribute('aria-labelledby','human-confirm-title');confirm.setAttribute('aria-describedby','human-confirm-copy');
  const title=humanEl('h2');title.id='human-confirm-title';const copy=humanEl('p');copy.id='human-confirm-copy';const fields=humanEl('dl');fields.id='human-confirm-fields';
  const label=humanEl('label',undefined,'human-consent');const check=humanEl('input');check.type='checkbox';check.id='human-confirm-check';const labelText=humanEl('span');labelText.id='human-confirm-label';label.append(check,labelText);
  const buttons=humanEl('div',undefined,'human-dialog-actions');buttons.append(humanButton('Cancel',()=>confirm.close('cancel')));
  const yes=humanButton('Continue',()=>{if(!check.checked)return;const action=humanStudio.confirm;humanStudio.confirm=null;confirm.close('confirm');action?.()},'human-primary');yes.id='human-confirm-yes';yes.disabled=true;buttons.append(yes);check.onchange=()=>yes.disabled=!check.checked;
  confirm.append(title,copy,fields,label,buttons);confirm.addEventListener('close',()=>{humanStudio.confirm=null;check.checked=false;if(confirm.returnValue!=='confirm'){$('status').textContent=confirm.dataset.action==='save'?'Save cancelled. No credits were used.':confirm.dataset.action==='run'?'Run cancelled. No agent was called.':'Download setup cancelled.';humanStudioSync()}});main.append(confirm);
  humanStudio.ready=true;
}
function humanManual() {
  if(busy||!canEdit||!creditReady)return;
  discardThen(()=>{
    invalidate();flow=null;review=null;$('name').value='My workflow';$('steps').replaceChildren();
    const candidate=candidates.find(c=>c.executable&&c.contract_id==='docs.search.v1')||candidates.find(c=>c.executable);
    if(candidate){for(let i=0;i<2;i++)addStep({id:'step_'+(i+1),resource_id:candidate.resource_id,contract_id:candidate.contract_id,
      input:{language:'en',limit:1,...(i?{}:{query:''}),...(candidate.contract_id==='news.search.v1'?{from_utc:new Date(Date.now()-86400000).toISOString().replace(/\.\d{3}Z$/,'Z')}:{})},
      bindings:i?{query:{node_id:'step_1',path:['items',0,'title']}}:{},after:i?['step_1']:[],when:null});}
    else{addStep();addStep()}
    dirty=true;humanStudio.dirtyScreen='builder';humanStudio.kind='custom';humanStudio.phase='plan';humanNavigate('builder');$('step-editor').open=true;humanStudioSync();
  });
}
function humanEnhanceSteps() {
  if(!humanStudio.ready)return;
  const rows=[...$('steps').children];
  for(const [index,row] of rows.entries()){
    const id=row.querySelector('[data-field=id]'),query=row.querySelector('[data-role=query]'),advanced=row.querySelector('.step-advanced');
    if(!id||!query||!advanced)continue;
    const idLabel=id.closest('label');if(idLabel&&!advanced.contains(idLabel))advanced.append(idLabel);
    let source=row.querySelector('[data-human-source]');
    if(!source){
      const label=humanEl('label','Search input');source=humanEl('select');source.dataset.humanSource='true';source.setAttribute('aria-label','Input for step '+(index+1));label.append(source);query.closest('label').before(label);
      // A select input event must not redraw its value from the old binding
      // before the following change event commits the new selection.
      source.oninput=event=>event.stopPropagation();
      source.onchange=()=>{
        try{const literal=row.querySelector('[data-field=input]'),bind=row.querySelector('[data-field=bindings]'),after=row.querySelector('[data-field=after]'),when=JSON.parse(row.querySelector('[data-field=when]').value);
          const inputs=JSON.parse(literal.value),bindings=JSON.parse(bind.value),old=bindings.query?.node_id;let dependencies=JSON.parse(after.value);
          if(source.value){bindings.query={node_id:source.value,path:['items',0,'title']};delete inputs.query;dependencies=[...new Set([...dependencies,source.value])];}
          else{delete bindings.query;inputs.query='';}
          if(old&&old!==source.value&&!Object.values(bindings).some(v=>v.node_id===old)&&when?.node_id!==old)dependencies=dependencies.filter(v=>v!==old);
          literal.value=JSON.stringify(inputs,null,2);bind.value=JSON.stringify(bindings,null,2);after.value=JSON.stringify(dependencies);row.refreshStep();invalidate();
        }catch{$('status').textContent='Check this step’s advanced settings before changing its input.'}
      };
    }
    let bindings={};try{bindings=JSON.parse(row.querySelector('[data-field=bindings]').value)}catch{}
    const options=[new Option('Write search text',''),...rows.slice(0,index).map((r,i)=>new Option('Use the result from step '+(i+1),r.querySelector('[data-field=id]').value))];
    const key=options.map(o=>o.value).join('|');if(source.dataset.options!==key){source.replaceChildren(...options);source.dataset.options=key}
    source.value=bindings.query?.node_id||'';source.disabled=busy||!canEdit;query.required=!source.value;source.closest('label').hidden=!['docs.search.v1','news.search.v1'].includes(row.querySelector('[data-field=choice]').value.split('|')[1]);
    const label=row.querySelector('legend');if(label)label.textContent='Step '+(index+1);
  }
}
function humanLibrary() {
  if(!humanStudio.ready)return;
  const query=$('workflow-search').value.trim().toLowerCase();const list=$('human-template-cards');list.replaceChildren();
  for(const draft of hubDrafts.filter(d=>d.name.toLowerCase().includes(query))){
    const card=humanButton('',()=>{
      const current=hubCatalog.find(p=>p.id===draft.template_id);
      if(!current){humanUnavailable(draft);return}
      hubOpen(current,draft);
      if(current.definition_hash!==draft.definition_hash){hubDirty=true;humanStudio.phase='plan';humanStudioSync()}
      else work(hubHistory);
    },'human-workflow-card');
    card.append(humanIcon('check'),humanEl('strong',draft.name),humanEl('span','Saved template · Open workflow','human-muted'));
    list.append(card);
  }
  const total=libraryFlows.length+hubDrafts.length;
  $('human-library-empty').hidden=total>0;$('library-empty').hidden=Boolean($('workflow-cards').children.length||list.children.length)||total===0;
  const matches=libraryFlows.filter(item=>item.name.toLowerCase().includes(query)).length;
  $('library-state').hidden=total===0;
  $('library-state').setAttribute('role','status');
  // Count each group the way its own list counts it, so this line agrees with "Show more · n of N shown".
  const saved=list.children.length,parts=[matches+' custom workflow'+(matches===1?'':'s')];
  // Workspaces have no workflow cap (11-01); the count only separates active from retired.
  humanActiveFlows=libraryFlows.filter(item=>item.active).length;parts.push(humanActiveFlows+' active');
  if(hubDrafts.length)parts.push(saved+' saved template'+(saved===1?'':'s'));
  $('library-state').textContent=parts.join(' · ')+(query?' match “'+query+'”':'');
  if(!$('human-library-help')){const row=humanEl('div',undefined,'context-help-row human-count-row');$('library-state').before(row);row.append($('library-state'));humanHelp('About saved workflows','Custom workflows and saved template workflows are grouped separately. Agent steps can reuse the same agent. Search matches saved workflow names.',row,'human-library-help');}
  $('human-library-help').hidden=total===0;
  $('human-custom-library-heading').hidden=libraryFlows.length===0;
  $('human-template-library-heading').hidden=hubDrafts.length===0;
  for(const button of $('workflow-cards').querySelectorAll('.workflow-card')){
    const caption=button.querySelector('span:last-child');if(caption)caption.textContent=caption.textContent.replace('Saved workflow · Open to inspect tests','Open workflow').replace('Inactive workflow','Archived workflow');
  }
}
function humanUnavailable(draft) {
  humanStudio.kind='unavailable';humanNavigate('builder');
  const panel=$('human-unavailable');panel.replaceChildren(humanEl('h3',draft.name),humanEl('p','Your settings are safe. This template needs a fresh verification before it can run again. Refresh templates or choose another starting point.'));
  const values=humanEl('dl');for(const [key,value] of Object.entries(draft.inputs))values.append(humanEl('dt',humanInputLabel(key)),humanEl('dd',String(value)));
  panel.append(values,humanButton('Browse available templates',()=>humanNavigate('templates'),'human-primary'));humanStudioSync();
}
function humanStudioSync() {
  if(!humanStudio.ready)return;
  for(const screen of ['create','templates','library','builder'])$('human-'+screen).hidden=screen!==humanStudio.screen;
  for(const screen of ['create','templates','library']){
    const active=humanStudio.screen===screen;$('human-nav-'+screen).setAttribute('aria-current',active?'page':'false');$('human-nav-'+screen).disabled=busy||!loaded;
  }
  $('human-credit-balance').textContent=loaded?creditBalance.toLocaleString('en-US')+' credits':'Checking credits…';
  $('editor').hidden=humanStudio.screen!=='create';$('human-enrollment').hidden=!loaded||creditReady||!canEdit;
  if(loaded&&!creditReady)$('model').disabled=true;
  $('human-check-availability').hidden=!loaded;$('human-check-availability').disabled=busy||!loaded;
  const availability=$('model-availability');availability.setAttribute('role','status');
  // An uncertain outcome locks new requests until history is read; offer that step right here.
  let recheck=$('human-check-history');
  if(!recheck){recheck=humanButton('Check history',()=>$('refresh').click(),'human-link-button');recheck.id='human-check-history';availability.after(recheck)}
  recheck.hidden=!uncertain||busy;
  // The disabled button explains itself until both the task and the sharing choice are given.
  availability.hidden=loaded&&!busy&&canEdit&&creditReady&&modelReady&&!uncertain&&Boolean($('objective').value.trim())&&$('model-consent').checked;
  $('model').setAttribute('aria-describedby','model-availability');
  availability.textContent=!loaded?'Checking access…'
    :busy?(humanStudio.operation==='generate'?'Creating your proposal…':'Finishing your current action…')
    :!canEdit?'Editing access is required to create a workflow.'
      :!creditReady?'Review your plan and credit terms to continue.'
        :!modelReady?'AI is unavailable. Try a template or build step by step.'
          :uncertain?'The last request did not confirm its outcome. Select Check history to reload it, then try again.'
            :!$('objective').value.trim()?'Describe a public task to begin.'
              :!$('model-consent').checked?'Allow input sharing to continue.':'Ready to create.';
  const modelCopy=busy&&humanStudio.operation==='generate'?'Creating your workflow…':'Create my workflow';
  if($('model').textContent!==modelCopy){$('model').textContent=modelCopy;if(!busy)$('model').prepend(humanIcon('sparkles'));}
  if(!busy)humanStudio.operation='';
  $('human-custom-builder').hidden=humanStudio.kind!=='custom';$('human-template-builder').hidden=humanStudio.kind!=='template';$('human-unavailable').hidden=humanStudio.kind!=='unavailable';
  document.querySelector('.human-page-header').hidden=humanStudio.screen==='builder';
  const custom=humanStudio.kind==='custom';const saved=custom?flow:hubDraft;const success=custom?lastRun?.status==='succeeded':hubSuccess;
  $('review-panel').hidden=custom&&Boolean(flow)&&!dirty&&['results','download'].includes(humanStudio.phase);
  $('human-try').classList.toggle('human-primary',!success);
  humanEnhanceSteps();
  for(const [index,card] of [...$('pearl-flow-preview').querySelectorAll('.pearl-flow-node')].entries()){
    const row=$('steps').children[index];if(!row)continue;
    const choice=row.querySelector('[data-field="choice"]').value,picked=candidates.find(c=>c.resource_id+'|'+c.contract_id===choice);
    card.querySelector('h3').textContent=picked?.name||taskLabel(choice.split('|')[1]);
    try{const inputs=JSON.parse(row.querySelector('[data-field="input"]').value),bindings=JSON.parse(row.querySelector('[data-field="bindings"]').value);const source=bindings.query?.node_id;
      const sourceIndex=[...$('steps').children].findIndex(r=>r.querySelector('[data-field="id"]').value===source);
      card.querySelector('p').textContent=source?'Uses the result from step '+(sourceIndex+1):inputs.query?'Searches for “'+String(inputs.query).slice(0,90)+'”':'Review the input for this step';
    }catch{}
  }
  const stepCount=$('steps').children.length;
  $('flow-count').textContent=stepCount+' steps · Review each input before running';
  $('human-manual').disabled=busy||!loaded||!canEdit||!creditReady;
  $('human-show-steps').hidden=stepCount<=3;$('human-show-steps').disabled=busy||!loaded;
  $('human-show-steps').textContent=humanStudio.stepsExpanded?'Show fewer steps':'Show all '+stepCount+' steps';
  $('human-show-steps').setAttribute('aria-expanded',String(humanStudio.stepsExpanded));
  for(const [i,card] of [...$('pearl-flow-preview').querySelectorAll('.pearl-flow-node')].entries())card.hidden=stepCount>3&&!humanStudio.stepsExpanded&&i>=3;
  $('human-builder-title').textContent=(custom?$('name').value:hubDraft?.name||hubProduct?.name)||'Your workflow';
  $('human-progress').hidden=humanStudio.kind==='unavailable';
  [...$('human-progress').children].forEach((item,index)=>{
    const current=humanStudio.phase==='plan'?0:humanStudio.phase==='try'?1:2;
    item.dataset.state=index<current?'complete':index===current?'current':'next';
  });
  $('human-save').hidden=!(custom&&review);$('human-save').disabled=busy||!loaded||!canEdit||!creditReady||!review||uncertain||creditBalance<(review?.credit_charge??1);
  if(review)$('human-save').textContent=(review.credit_charge??1)?'Save workflow · '+(review.credit_charge??1)+' credit'+((review.credit_charge??1)===1?'':'s'):'Save changes';
  $('human-review').hidden=!(custom&&!review&&dirty);$('human-review').disabled=busy||!loaded||!canEdit||uncertain||Boolean($('steps').querySelector('[data-provider-blocked=true]'));
  $('human-try').hidden=!(custom&&flow&&!dirty);$('human-try').disabled=busy||!loaded||!canRun||!flow?.active||uncertain||['running','unknown'].includes(lastRun?.status);
  $('human-refresh').hidden=!flow;$('human-refresh').disabled=busy||!loaded;
  $('human-download').hidden=!(custom&&success&&!dirty&&canManage)||humanStudio.phase==='download';$('human-download').disabled=busy||uncertain;
  $('export-panel').hidden=!(custom&&humanStudio.phase==='download'&&success);
  $('results-panel').hidden=!(custom&&lastRun&&humanStudio.screen==='builder');
  $('human-more').hidden=false;$('human-workflow-settings').hidden=!flow||!custom;
  $('review-hint').hidden=true;$('credit-quote').hidden=true;
  const canChange=canEdit&&!busy&&loaded;
  for(const control of document.querySelectorAll('#human-builder input:not([type=checkbox]),#human-builder textarea,#human-builder select'))control.disabled=!canChange;
  if($('origin'))$('origin').disabled=busy||!loaded||!canManage;
  $('hub-review').hidden=Boolean(hubDraft&&!hubDirty);$('hub-review').disabled=!canChange||!creditReady||uncertain;
  $('hub-test').hidden=!hubDraft;
  $('human-template-try').hidden=Boolean(hubDirty);$('human-template-try').disabled=busy||!loaded||!canRun||hubTesting||uncertain||!hubDraft;
  $('hub-download').hidden=!hubSuccess||hubDirty||!canManage;
  $('hub-support').textContent=hubProduct?.product?'Verified fallback · One alternative when needed, with your permission':'Published template · Reviewed default inputs';
  $('hub-agents').hidden=false;
  for(const input of $('hub-inputs').querySelectorAll('input')){
    const label=document.querySelector('label[for="'+input.id+'"]');if(label)label.textContent=humanInputLabel(input.name);
  }
  const quiet=['Review a workflow or inspect retained tests.','Your reviewed action is complete.','AI proposal ready. Review the steps and exact inputs before saving.'];
  document.querySelector('.human-notice').hidden=loaded&&!busy&&quiet.includes($('status').textContent);
  document.querySelector('.human-notice').dataset.busy=String(busy);
  $('human-busy-copy').hidden=!busy;$('status').hidden=busy;
  if(busy)$('human-busy-copy').textContent=humanStudio.operation==='generate'?'Creating your workflow. Nothing will run until you approve it.':humanStudio.operation==='run'?'Running your workflow. Results appear as each step finishes.':humanStudio.operation==='save'?'Saving your reviewed workflow…':'Working on your request…';
  document.querySelector('#human-library .human-empty')?.querySelectorAll('button').forEach(b=>b.disabled=busy||!loaded);
  document.querySelectorAll('#human-create .human-examples button').forEach(b=>b.disabled=busy||!canEdit);
}
// Keep the proven state machine; replace its screen composition and user actions.
const humanOriginalInvalidate=invalidate;
invalidate=function(){humanStudio.dirtyScreen=humanStudio.screen;humanOriginalInvalidate()};
discardThen=function(action){if(!dirty){action();return}const dialog=$('discard-dialog');dialog.onclose=()=>{if(dialog.returnValue==='discard')action();else{humanStudio.kind='custom';humanNavigate(humanStudio.dirtyScreen||'builder')}};dialog.returnValue='cancel';dialog.showModal()};
hubDiscard=function(action){if(!hubDirty){action();return}const dialog=$('discard-dialog');dialog.onclose=()=>{if(dialog.returnValue==='discard')action();else{humanStudio.kind='template';humanNavigate('builder')}};dialog.returnValue='cancel';dialog.showModal()};
const humanOriginalAdd=addStep;
addStep=function(value){humanOriginalAdd(value);humanEnhanceSteps()};
// An example the AI cannot build right now is shown as unavailable instead of failing after a click.
function humanExampleAvailability(candidates){
  const ready=new Set((candidates||[]).filter(c=>c.executable).map(c=>c.contract_id));
  for(const button of document.querySelectorAll('.human-examples [data-contracts]')){
    const missing=button.dataset.contracts.split(' ').filter(c=>!ready.has(c));
    button.disabled=missing.length>0;
    button.title=missing.length?'Not available right now: '+missing.map(c=>c==='news.search.v1'?'News search':'Research and document search').join(', '):'';
  }
}
const humanOriginalSetOptions=setOptions;
setOptions=function(v){humanOriginalSetOptions(v);humanExampleAvailability(v.options?.candidates)};
const humanOriginalApply=applyFlow, humanOriginalReview=showReview, humanOriginalResults=showResults, humanOriginalLibrary=renderLibrary, humanOriginalHubOpen=hubOpen, humanOriginalLoadHub=loadHub, humanOriginalSyncHub=syncHub;
applyFlow=function(value){humanStudio.stepsExpanded=false;humanOriginalApply(value);humanStudio.kind='custom';humanStudio.phase='try';humanNavigate('builder')};
showReview=function(value){humanStudio.stepsExpanded=false;humanOriginalReview(value);
  if(value.state==='needs_details'){
    // Stay on the request and say what is missing; an earlier proposal must not look like the answer.
    review=null;humanStudio.kind='custom';humanStudio.phase='plan';humanNavigate('create');
    const need=(value.missing_requirements||[]).join(', ');
    let notice=$('human-create-notice');
    if(!notice){notice=humanEl('p',undefined,'human-create-notice');notice.id='human-create-notice';notice.setAttribute('role','alert');$('model').after(notice)}
    notice.textContent=(need?'Not available right now: '+need+'. ':'')+'No workflow was saved and no credits were used. Try a research or documentation search, or start from a template.';
    notice.hidden=false;$('human-plan-notice').hidden=true;return;
  }
  $('human-create-notice')?.setAttribute('hidden','');
  humanStudio.dirtyScreen='builder';humanStudio.kind='custom';humanStudio.phase='plan';humanNavigate('builder');$('human-plan-notice').hidden=true};
showResults=function(run){humanOriginalResults(run);
  const cards=[...$('results').querySelectorAll(':scope > article')];
  if(cards.length>1&&run?.status!=='running'){
    const last=[...cards].reverse().find(n=>n.dataset.status==='succeeded')||cards.at(-1);
    const primary=run?.status==='succeeded'?last:cards.find(n=>['failed','unknown','dispatched'].includes(n.dataset.status))||last;
    const other=humanEl('details',undefined,'human-details');other.append(humanEl('summary','See '+(cards.length-1)+' other step'+(cards.length===2?'':'s')));
    for(const card of cards)if(card!==primary)other.append(card);$('results').append(primary,other);
  }
  if(humanStudio.ready&&humanStudio.kind==='custom'&&run){humanStudio.phase='results';humanStudioSync()}};
renderLibrary=function(){humanOriginalLibrary();humanLibrary()};
hubOpen=function(product,draft=null){humanOriginalHubOpen(product,draft);humanStudio.kind='template';humanStudio.phase=draft?'try':'plan';humanNavigate('builder');humanStudioSync()};
loadHub=async function(){await humanOriginalLoadHub();humanLibrary()};
syncHub=function(){humanOriginalSyncHub();humanStudioSync()};
showStage=function(value,focus=false){if(!stages[value])return;stage=value;for(const [key,id] of Object.entries(stages)){
  $('stage-'+key).setAttribute('aria-selected',String(key===value));$('stage-'+key).tabIndex=-1;
}if(focus&&humanStudio.ready){humanStudio.kind='custom';humanStudio.phase=value==='test'?'try':value==='export'?'download':'plan';humanNavigate('builder')}humanStudioSync()};
// Preserve editable controls before their old visual containers are rebuilt.
humanStudioBuild();
const humanUnavailablePanel=humanEl('div');humanUnavailablePanel.id='human-unavailable';$('human-builder').append(humanUnavailablePanel);
const humanPlanNotice=humanEl('p',undefined,'human-empty');humanPlanNotice.id='human-plan-notice';humanPlanNotice.hidden=true;$('review-panel').prepend(humanPlanNotice);
const humanReviewButton=humanButton('Review changes',()=>{
  if(!$('name').reportValidity())return;
  // Let the reviewed controller explain malformed advanced data before native
  // required-field validation, which cannot describe a JSON parsing problem.
  try{for(const input of $('steps').querySelectorAll('[data-field=input],[data-field=bindings],[data-field=after],[data-field=when]'))JSON.parse(input.value)}
  catch{$('review').click();return}
  if([...$('steps').querySelectorAll('[data-role=query]')].every(n=>n.reportValidity()))$('review').click();
},'human-primary');humanReviewButton.id='human-review';$('human-save').before(humanReviewButton);
$('prepare').onclick=humanTryCustom;
$('hub-create-ai').onclick=()=>humanNavigate('create');
$('new-flow').onclick=()=>discardThen(()=>{invalidate();flow=null;$('name').value=$('objective').value='';$('steps').replaceChildren();addStep();addStep();dirty=false;uncertain=false;humanStudio.kind='custom';humanStudio.phase='plan';humanNavigate('create');$('objective').focus()});
$('workflow-search').addEventListener('input',humanLibrary);
$('objective').addEventListener('input',()=>$('human-create-notice')?.setAttribute('hidden',''));
// Sign-in ends after an hour without activity (12 hours at most); warn before it ends and keep the typed task across a new sign-in.
const humanDraftKey='workspace-objective-draft';
$('objective').addEventListener('input',()=>{try{sessionStorage.setItem(humanDraftKey,$('objective').value.slice(0,2000))}catch{}});
try{const kept=sessionStorage.getItem(humanDraftKey);if(kept&&!$('objective').value)$('objective').value=kept}catch{}
const humanSession={absolute:0,ends:0,timer:0};
function humanSessionWarn(){const status=$('status');if(!status)return;const at=new Date(humanSession.ends*1000).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});status.textContent=humanSession.ends>=humanSession.absolute?'Your sign-in ends at '+at+' (12-hour limit). Save your workflow now; your typed task is kept if you sign in again.':'Your sign-in ends at '+at+' unless you keep working. Any action keeps you signed in; your typed task is kept if you sign in again.'}
function humanSessionSchedule(ends){if(!Number.isFinite(ends)||ends<=0)return;humanSession.ends=humanSession.absolute?Math.min(ends,humanSession.absolute):ends;clearTimeout(humanSession.timer);const wait=humanSession.ends*1000-Date.now()-5*60*1000;if(wait<=0)humanSessionWarn();else humanSession.timer=setTimeout(humanSessionWarn,Math.min(wait,2147483000))}
document.addEventListener('workspace-session-expires',event=>{const detail=event.detail||{};humanSession.absolute=Number(detail.absolute)||0;humanSessionSchedule(Number(detail.expires))});
// The server extends the session on every request, so a successful call moves the warning an hour out.
document.addEventListener('workspace-session-activity',()=>{if(humanSession.ends)humanSessionSchedule(Date.now()/1000+3600)});
$('model').addEventListener('click',()=>{
  humanStudio.kind='custom';humanStudio.phase='plan';humanStudio.operation='generate';
  const goal=$('objective').value.trim().replace(/^(?:find|search for|look for)\s+/i,'').replace(/\s+(?:in|using|with)\s+(?:exactly\s+)?(?:two|three|four|five|six|seven|eight|nine|ten|[2-9]|10)\s+(?:connected\s+)?steps?\.?$/i,'').replace(/[.!]$/,'').replace(/\s+(?:separately|independently|respectively|individually|in parallel)$/i,'');
  // Names hold 80 characters; end on a whole word instead of "documentati".
  // A cut name must not end on a connector such as ", then find".
  const short=goal.length<=80?goal:goal.slice(0,81).replace(/\s+\S*$/,'').replace(/(?:[\s,;:]+(?:then|and|or|to|with|for|of|find|search|get|the|a|an|supporting|related|additional))+$/i,'').replace(/[\s,;:]+$/,'');
  $('name').value=short.charAt(0).toUpperCase()+short.slice(1);
},true);
$('human-confirm').addEventListener('cancel',()=>{$('run-consent').checked=$('hub-run-consent').checked=false});
window.addEventListener('beforeunload',event=>{if(hubDirty){event.preventDefault();event.returnValue=''}});
document.addEventListener('workspace-signout-request',event=>{if(dirty||hubDirty){event.preventDefault();event.stopImmediatePropagation();const d=$('discard-dialog');d.onclose=()=>{if(d.returnValue==='discard'){dirty=false;hubDirty=false;document.getElementById('workspace-signout').click()}};d.returnValue='cancel';d.showModal()}},true);
function humanHashRoute(){const route=location.hash.slice(1);if(['create','templates','library'].includes(route))humanNavigate(route,true);else if(route==='template-hub')humanNavigate('templates',true);else if(route==='workflow')humanNavigate(flow||review||hubProduct||dirty||humanStudio.kind==='unavailable'?'builder':'library',true)}
addEventListener('hashchange',humanHashRoute);humanHashRoute();
