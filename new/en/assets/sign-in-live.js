(()=>{'use strict';
/* Private page memory only: never persist customer data or replay a mutation. */
(()=>{'use strict';
const transport=window.fetch.bind(window),reads=new Map(),pending=new Map(),actions=new Map(),buttons=new Map();
let revision=0,sequence=0,timer=null;
let interaction=false,navigationEnd=null,navigationBlocked=false,leaving=false;
let authenticated=false;
document.addEventListener('workspace-session-ready',()=>{authenticated=true});
function signInTarget(expired=false){
 const target=new URL('/new/en/sign-in.html',location.origin);
 target.searchParams.set('next',location.pathname+location.search+location.hash);
 if(expired)target.searchParams.set('result','expired');
 return target.pathname+target.search;
}
function noteInteraction(){interaction=true;navigationBlocked=false;setTimeout(()=>{interaction=false},0)}
for(const type of ['click','submit','change'])document.addEventListener(type,noteInteraction,true);
// Show navigation feedback only after the page's own guards accept the click.
document.addEventListener('click',event=>{
 const link=event.target.closest?.('a[href]');
 if(!link||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.hasAttribute('download')||link.target&&link.target!=='_self')return;
 const target=new URL(link.href,location.href);
 if(target.origin!==location.origin||!target.pathname.startsWith('/customer/')||target.pathname===location.pathname&&target.search===location.search)return;
 queueMicrotask(()=>{if(event.defaultPrevented||navigationBlocked)return;navigationEnd?.();navigationEnd=begin(link.dataset.workspaceSection==='flows'?'Opening your workflows…':'Opening your workspace…',link)});
});

// A cancelled unsaved-change prompt must not leave navigation progress running.
addEventListener('beforeunload',event=>setTimeout(()=>{if(event.defaultPrevented||event.returnValue){navigationBlocked=true;navigationEnd?.();navigationEnd=null}},0));
addEventListener('pagehide',()=>{navigationEnd?.();navigationEnd=null});
function clearReads(){revision++;reads.clear();pending.clear()}
function expiredSession(response,url){
 if(response.status!==401||url.origin!==location.origin||!url.pathname.startsWith('/api/customer-')||!location.pathname.startsWith('/customer/')||location.pathname==='/new/en/sign-in.html'||leaving)return;
 clearReads();
 leaving=true;
 // Conceal the private document before a navigation can paint another frame.
 const main=document.querySelector('main');if(main){main.hidden=true;main.inert=true}
 for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close('cancel');
 location.replace(signInTarget(authenticated));
}
function progress(){let bar=document.getElementById('workspace-progress');if(!bar){bar=document.createElement('div');bar.id='workspace-progress';bar.className='workspace-progress';bar.setAttribute('role','status');bar.setAttribute('aria-live','polite');const spinner=document.createElement('span');spinner.className='workspace-spinner';spinner.setAttribute('aria-hidden','true');const label=document.createElement('span');label.id='workspace-progress-label';const elapsed=document.createElement('span');elapsed.id='workspace-progress-elapsed';bar.append(spinner,label,elapsed);document.body.append(bar)}return bar}
function update(){const bar=progress(),entry=actions.values().next().value;bar.hidden=!entry;if(!entry)return;document.getElementById('workspace-progress-label').textContent=entry.label;document.getElementById('workspace-progress-elapsed').textContent=Math.floor((performance.now()-entry.started)/1000)+'s'}
function begin(label='Loading your workspace…',source=document.activeElement){if(!interaction&&!actions.size)return()=>{};const id=++sequence,button=source?.matches?.('button')?source:null;actions.set(id,{label,started:performance.now()});if(button){buttons.set(button,(buttons.get(button)||0)+1);button.setAttribute('aria-busy','true')}update();if(timer===null)timer=setInterval(update,1000);let ended=false;return()=>{if(ended)return;ended=true;actions.delete(id);if(button){const count=buttons.get(button)-1;if(count)buttons.set(button,count);else{buttons.delete(button);button.removeAttribute('aria-busy')}}update();if(!actions.size){clearInterval(timer);timer=null}}}
function paint(){return new Promise(resolve=>{let done=false;const complete=()=>{if(!done){done=true;resolve()}};requestAnimationFrame(complete);setTimeout(complete,50)})}
// Initial navigation ends after session checks, dependent reads and the final paint.
async function ready(){
 if(!document.body.hasAttribute('data-workspace-loading')||leaving)return;
 if(document.readyState!=='complete')await new Promise(resolve=>addEventListener('load',resolve,{once:true}));
 if(document.fonts)await document.fonts.ready;
 if(leaving)return;
 document.body.removeAttribute('data-workspace-loading');
 await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 if(!leaving)document.getElementById('workspace-entry-progress')?.setAttribute('hidden','');
}
function redirect(path){leaving=true;location.replace(path)}
function cacheable(url,method,options){return method==='GET'&&!options.fresh&&url.origin===location.origin&&!url.search&&!url.hash&&/^\/api\/customer-organizations\/ws_[a-f0-9]{32}\/authoring\/typed\/flows(?:\/wtf_[a-f0-9]{32})?$/.test(url.pathname)}
async function request(path,options={}){
 const url=new URL(path,location.href),method=(options.method||'GET').toUpperCase(),{fresh,...supplied}=options;
 const eligible=cacheable(url,method,options),key=url.href;
 if(method!=='GET')clearReads();
 const cached=eligible?reads.get(key):null;
 if(cached&&cached.until>performance.now())return cached.response.clone();
 if(cached)reads.delete(key);
 if(eligible&&pending.has(key))return(await pending.get(key)).clone();
 const stamp=revision,end=begin(method==='GET'?'Loading current workspace information…':'Processing your reviewed request…');
 const job=(async()=>{await paint();try{const response=await transport(path,{...supplied,credentials:'same-origin',cache:'no-store'});if(!response.ok){clearReads();expiredSession(response,url);return response}if(url.origin===location.origin&&url.pathname==='/api/customer-auth/session')authenticated=true;if(eligible&&stamp===revision&&response.headers.get('content-type')?.includes('application/json')){const copy=response.clone(),text=await copy.text();if(text.length<=262144&&stamp===revision){if(reads.size>=20)reads.delete(reads.keys().next().value);reads.set(key,{response:response.clone(),until:performance.now()+10000})}}return response}catch(error){clearReads();throw error}finally{end();if(method!=='GET')clearReads();if(pending.get(key)===job)pending.delete(key)}})();
 if(eligible)pending.set(key,job);
 return(await job).clone();
}
window.workspaceUI=Object.freeze({request,begin,paint,clearReads,ready,redirect});
addEventListener('pagehide',clearReads);document.addEventListener('visibilitychange',()=>{if(document.hidden)clearReads()});
})();


const status=document.getElementById('status'),retry=document.getElementById('retry');
const buttons={google:document.getElementById('google'),github:document.getElementById('github')};
const message=new URLSearchParams(location.search).get('result');
let destination="/customer/workspaces";
if(!destination.includes('#')&&['#account','#detail','#templates'].includes(location.hash))destination+=location.hash;
if(location.search)history.replaceState(null,'','/new/en/sign-in.html'+(destination==='/new/en/workspace.html'?'':'?next='+encodeURIComponent(destination)));
let available=new Set(),busy=false;
async function load(){
  retry.hidden=true;available.clear();for(const b of Object.values(buttons))b.disabled=true;
  try{
    const session=await window.workspaceUI.request('/api/customer-auth/status',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!session.ok)throw Error();const current=await session.json();
    if(current.authenticated===true){window.workspaceUI.redirect(destination);return;}
    if(current.authenticated!==false)throw Error();
    const response=await window.workspaceUI.request('/api/customer-auth/options',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error();const value=await response.json();
    for(const p of value.providers||[])if(buttons[p.id]&&p.configured===true)available.add(p.id);
    for(const [p,b]of Object.entries(buttons))b.disabled=!available.has(p);
    status.textContent=available.size?(message==='cancelled'?'Sign-in was cancelled. Choose a provider to try again.':message==='failed'?'Sign-in could not be completed. Choose a provider to try again.':message==='expired'?'Your session expired. Sign in again to continue.':'Choose a sign-in provider.'):'Customer sign-in is currently unavailable.';
    retry.hidden=available.size>0;
  }catch{status.textContent='Sign-in is currently unavailable. Please try again.';retry.hidden=false;}
}
retry.addEventListener('click',load);
for(const [provider,button]of Object.entries(buttons))button.addEventListener('click',async()=>{
  if(busy||!available.has(provider))return;busy=true;for(const b of Object.values(buttons))b.disabled=true;
  const label=button.querySelector('.signin-label'),spinner=button.querySelector('.workspace-spinner'),original=label.textContent;
  button.dataset.signinPending='true';button.setAttribute('aria-busy','true');spinner.hidden=false;
  label.textContent='Opening '+(provider==='google'?'Google':'GitHub')+'…';
  status.textContent='Opening secure sign-in.';
  try{
    const r=await window.workspaceUI.request('/api/customer-auth/begin',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(15000),body:JSON.stringify({provider,next:destination})});
    button.setAttribute('aria-busy','true');
    const v=await r.json();if(!r.ok||typeof v.authorization_url!=='string')throw Error();const u=new URL(v.authorization_url);
    if(u.username||u.password||u.hash||!((provider==='google'&&u.origin==='https://accounts.google.com'&&u.pathname==='/o/oauth2/v2/auth')||(provider==='github'&&u.origin==='https://github.com'&&u.pathname==='/login/oauth/authorize')))throw Error();
    location.assign(u.href);
  }catch{delete button.dataset.signinPending;button.removeAttribute('aria-busy');spinner.hidden=true;label.textContent=original;busy=false;for(const [p,b]of Object.entries(buttons))b.disabled=!available.has(p);status.textContent='Sign-in could not be started. Please try again.';}
});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
load();

/* Shared navigation and approachable account surfaces. No customer data is cached. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id),el=(tag,copy,className)=>{const n=document.createElement(tag);if(copy!==undefined)n.textContent=copy;if(className)n.className=className;return n};
  const toggle=$('workspace-menu'),nav=$('workspace-navigation'),close=$('workspace-nav-close'),main=$('workspace-main');
  const explicitWorkspace=location.pathname.match(/^\/customer\/organizations\/(ws_[a-f0-9]{32})\//)?.[1]||new URLSearchParams(location.search).get('workspace');
  if(/^ws_[a-f0-9]{32}$/.test(explicitWorkspace||'')){
    const flows='/customer/organizations/'+explicitWorkspace+'/flows';
    for(const [section,path]of Object.entries({overview:'/customer/organizations?workspace='+explicitWorkspace,flows,templates:flows+'#templates',connections:'/customer/organizations/'+explicitWorkspace+'/connections',members:'/customer/organizations?workspace='+explicitWorkspace+'#detail',credits:'/customer/plan?workspace='+explicitWorkspace})){
      const link=nav?.querySelector('[data-workspace-section="'+section+'"]');if(link)link.href=path;
    }
    for(const link of document.querySelectorAll('.workspace-start-link'))link.href=flows;
  }
  if(toggle&&nav){
    const mobileSignout=el('button','Sign out');mobileSignout.type='button';mobileSignout.id='workspace-mobile-signout';mobileSignout.onclick=()=>{set(false);($('workspace-signout')||$('logout'))?.click()};nav.append(mobileSignout);
    const mask=el('button',undefined,'workspace-nav-mask');mask.type='button';mask.setAttribute('aria-label','Close workspace navigation');mask.hidden=true;document.body.append(mask);
    const set=open=>{const mobile=matchMedia('(max-width:900px)').matches;document.body.dataset.workspaceMenu=String(open&&mobile);toggle.setAttribute('aria-expanded',String(open&&mobile));toggle.setAttribute('aria-label',open&&mobile?'Close workspace navigation':'Open workspace navigation');mask.hidden=!(open&&mobile);if(main)main.inert=open&&mobile;if(open&&mobile)close.focus();};
    toggle.onclick=()=>set(toggle.getAttribute('aria-expanded')!=='true');close.onclick=()=>{set(false);toggle.focus()};mask.onclick=close.onclick;
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&toggle.getAttribute('aria-expanded')==='true'){set(false);toggle.focus()}});
    nav.addEventListener('click',event=>{if(event.target.closest('a'))set(false)});
    nav.addEventListener('keydown',event=>{
      if(event.key!=='Tab'||toggle.getAttribute('aria-expanded')!=='true')return;
      const items=[...nav.querySelectorAll('a,button,summary')].filter(n=>n.getClientRects().length),first=items[0],last=items.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
    });
    matchMedia('(max-width:900px)').addEventListener('change',()=>set(false));set(false);
    const mark=()=>{const templates=location.hash==='#templates'||location.hash==='#template-hub';if(/\/flows\/?$/.test(location.pathname)){
      for(const link of nav.querySelectorAll('[data-workspace-section]'))link.removeAttribute('aria-current');nav.querySelector('[data-workspace-section="'+(templates?'templates':'flows')+'"]').setAttribute('aria-current','page');
    }const selected=nav.querySelector('[aria-current="page"]');const group=selected?.closest('details');if(group)group.open=true;};addEventListener('hashchange',mark);mark();
  }
  // An account reference is an optional team setting, not the workspace's purpose.
  const account=$('account'),detail=$('detail');
  if(account&&detail&&$('organizations')){
    document.body.classList.add('human-overview');
    const content=$('content'),oldGrid=content.querySelector('.grid'),chooser=$('organizations').closest('section');
    content.append(account);
    const group=el('details',undefined,'human-workspace-chooser');group.append(el('summary','Choose or create a workspace'));chooser.before(group);group.append(chooser);
    const invitations=$('invitations').closest('section'),invites=el('details',undefined,'human-invitations');invites.append(el('summary','Invitations'));invitations.before(invites);invites.append(invitations);
    if(oldGrid)oldGrid.classList.add('human-overview-grid');
    const header=main.querySelector('header');if(header){const title=header.querySelector('h1');if(title)title.textContent='Your workspace';const copy=title?.nextElementSibling;if(copy)copy.textContent='Pick up where you left off, or turn a new idea into a workflow.';}
    const start=$('workflow-studio')?.closest('.workspace-start');
    if(start){start.querySelector('h3').textContent='What would you like to build?';start.querySelector('p').textContent='Start with an idea or a template.';
      const primary=$('workflow-studio'),oldParagraph=primary.closest('p');primary.textContent='Create with AI';const actions=el('div',undefined,'overview-primary-actions');actions.append(primary);if(oldParagraph)oldParagraph.remove();
      const templates=el('a','Browse templates','btn');templates.id='human-overview-templates';templates.href='/customer/workflows';actions.append(templates);start.append(actions);}
    const wrap=(parent,className,elements)=>{const box=el('div',undefined,className);for(const item of elements)if(item)box.append(item);parent.append(box);return box;};
    const owner=$('owner-actions'),settings=$('organization-settings'),rename=$('rename');
    // Keep management visibility bound to the existing owner permission.
    const ownerSettings=wrap(settings,'overview-owner-settings',[rename]);ownerSettings.hidden=owner.hidden;
    const permission=()=>ownerSettings.hidden=owner.hidden;new MutationObserver(permission).observe(owner,{attributes:true,attributeFilter:['hidden']});
    settings.insertBefore(ownerSettings,settings.querySelector('.row'));
    const invite=$('invite'),inviteHeading=invite.previousElementSibling.previousElementSibling,inviteCopy=invite.previousElementSibling;
    wrap(owner,'overview-invite',[inviteHeading,inviteCopy,invite]);
    for(const [id,name]of [['members','overview-members'],['sent','overview-sent']]){
      const list=$(id),heading=list.previousElementSibling;const panel=wrap(owner,name,[heading,list]);
      const empty=el('p',id==='members'?'No active members.':'No sent invitations.','overview-empty');panel.append(empty);
      const reflect=()=>empty.hidden=list.children.length>0;new MutationObserver(reflect).observe(list,{childList:true});reflect();
    }
    for(const id of ['rename','invite','create','new-draft']){
      const form=$(id);form.classList.add('overview-form');
      for(const label of [...form.querySelectorAll(':scope > label[for]')]){
        const input=$(label.htmlFor);if(!input)continue;const field=el('div',undefined,'overview-field');form.insertBefore(field,label);field.append(label,input);
      }
    }
    for(const disclosure of [group,invites,$('member-panel'),$('individual-panel'),settings]){
      disclosure.classList.add('overview-disclosure');const body=el('div',undefined,'overview-disclosure-body');
      for(const child of [...disclosure.children])if(child.tagName!=='SUMMARY')body.append(child);disclosure.append(body);
    }
    const pageStatus=$('status'),quiet=new Set(['Your organization access is current.','Workspace details refreshed.']);
    const statusVisibility=()=>pageStatus.hidden=quiet.has(pageStatus.textContent);new MutationObserver(statusVisibility).observe(pageStatus,{childList:true,characterData:true,subtree:true});statusVisibility();
    new MutationObserver(()=>{invites.open=Boolean($('invitations').querySelector('button'))}).observe($('invitations'),{childList:true});
    const copyLinks=()=>{const a=$('workflow-studio'),template=$('human-overview-templates');if(a&&template&&/\/flows$/.test(a.getAttribute('href')||'')){const target=a.getAttribute('href')+'#templates';if(template.getAttribute('href')!==target)template.href=target;}};
    new MutationObserver(copyLinks).observe($('org-actions'),{attributes:true,subtree:true,attributeFilter:['href']});copyLinks();
    const reference=$('reference');if(reference){const button=el('button','Copy invitation code');button.type='button';button.onclick=async()=>{try{await navigator.clipboard.writeText(reference.textContent);button.textContent='Invitation code copied'}catch{button.textContent='Select the invitation code above to copy it'}};reference.after(button);}
    const route=()=>{const own=location.hash==='#account',members=location.hash==='#detail';account.hidden=!own;oldGrid.hidden=own;
      if(members)$('member-panel').open=true;
      const title=main.querySelector('header h1');if(title)title.textContent=own?'Your account':members?'Team and workspace':'Your workspace';
      const intro=title?.nextElementSibling;if(intro?.tagName==='P')intro.textContent=own?'Manage your invitation code and account access.':members?'Manage the people who can access this workspace.':'Pick up where you left off, or turn a new idea into a workflow.';
      const accountHeading=account.querySelector('h2');if(accountHeading)accountHeading.textContent='Invitation code';
      if(own)account.scrollIntoView({block:'start'});};
    addEventListener('hashchange',route);route();
    new MutationObserver(()=>{const empty=$('organizations').querySelectorAll('button').length===0;group.open=empty;if(empty&&$('org-name')&&!$('org-name').value)$('org-name').placeholder='My workspace';}).observe($('organizations'),{childList:true});
  }
  const enroll=$('enroll'),active=$('active');
  if(enroll&&active&&$('balance')){
    document.body.classList.add('human-credits');
    const continuation=active.querySelector('.workspace-start-link')?.closest('p');
    if(continuation){$('balance').closest('section').append(continuation);const reveal=()=>continuation.hidden=active.hidden;new MutationObserver(reveal).observe(active,{attributes:true,attributeFilter:['hidden']});reveal();}
    const first=$('balance').closest('section'),soon=el('details',undefined,'human-plan-soon');soon.append(el('summary','Paid plans and top-ups · Coming soon'));
    for(const element of [...first.children])if(element.tagName==='BUTTON'||element.tagName==='P'&&element.textContent.startsWith('Paid plans,'))soon.append(element);first.append(soon);
    const closing=el('details',undefined,'human-plan-settings');closing.append(el('summary','Plan settings'));
    for(const element of [...active.children])if(!element.querySelector?.('.workspace-start-link'))closing.append(element);active.append(closing);first.append(active);
    const history=$('history')?.closest('section');if(history){const details=el('details',undefined,'human-credit-history');details.append(el('summary','View credit history'));history.before(details);details.append(history);}
    const policy=$('terms').closest('section'),disclosure=el('details',undefined,'human-credit-policy');disclosure.append(el('summary','Read your credit terms'));policy.before(disclosure);disclosure.append(policy);
    // Enrollment must display all required terms before its unchecked agreements.
    const show=()=>{disclosure.open=!enroll.hidden;disclosure.dataset.enrolling=String(!enroll.hidden)};
    new MutationObserver(show).observe(enroll,{attributes:true,attributeFilter:['hidden']});show();
  }
  // Preserve controls and listeners while grouping related, existing actions.
  const actionsFor=ids=>{
    const items=ids.map($).filter(Boolean);if(items.length<2||!items.every(item=>item.parentElement===items[0].parentElement))return;
    const row=el('div',undefined,'layout-actions');items[0].before(row);row.append(...items);
  };
  if(/\/build\/?$/.test(location.pathname)&&main&&!main.classList.contains('human-studio')){
    main.classList.add('layout-legacy-task');
    for(const label of [...main.querySelectorAll('label[for]')]){
      const input=$(label.htmlFor);if(!input||input.parentElement!==label.parentElement)continue;
      const field=el('div',undefined,'layout-field');label.before(field);field.append(label,input);
    }
    for(const [id,button,copy]of [['draft','load','Saved draft'],['snapshot','refresh','Snapshot']]){
      const input=$(id),action=$(button);if(!input||!action||input.parentElement!==action.parentElement)continue;
      const field=el('div',undefined,'layout-field'),label=el('label',copy),row=el('div',undefined,'layout-select-action');label.htmlFor=id;
      input.before(field);row.append(input,action);field.append(label,row);
    }
  }
  if(/\/recovery\/?$/.test(location.pathname)&&main){
    main.classList.add('layout-recovery');actionsFor(['enroll','revoke']);actionsFor(['refresh','withdraw','finalize']);
  }
})();

})();
