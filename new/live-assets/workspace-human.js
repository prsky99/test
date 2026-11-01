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
