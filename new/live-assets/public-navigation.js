/* Native links and history share the operating page state and security gates. */
'use strict';
(() => {
  const q=selector=>document.querySelector(selector);
  const paths=Object.fromEntries([...document.querySelectorAll('#navTabs a[data-tab]')].map(link=>[link.dataset.tab,new URL(link.href).pathname]));
  paths.overview='/';
  const policies={terms:'tos',privacy:'privacy','privacy-choices':'ccpa',accessibility:'accessibility',disclosures:'ai',notifications:'cancellation',contact:'contact',cookies:'cookie-preferences'};
  let restoring=false;
  const modified=event=>event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey;
  function route(tab){
    const fragment=location.hash;
    return (paths[tab]||'/')+(fragment.startsWith('#'+tab+'?')?fragment:'#'+tab);
  }
  function focusHeading(tab){
    if(tab==='chat')return;
    const heading=q('[data-panel="'+tab+'"] h1')||q('[data-panel="'+tab+'"] h2');
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
  }
  const previousSwitch=switchTab;
  switchTab=function(tab){
    const changed=currentTab!==tab,initial=initialRoutingComplete;
    q('#unknownRouteNotice')?.remove();
    if(restoring)initialRoutingComplete=false;
    for(const id of ['legalModal','cookiePrefsModal'])if(q('#'+id)?.open)q('#'+id).close();
    try{previousSwitch(tab);}finally{initialRoutingComplete=initial;}
    history.replaceState(null,'',route(currentTab));
    if(changed)focusHeading(currentTab);
  };
  const previousLegal=openLegalModal;
  openLegalModal=function(doc='tos'){
    const safe=VALID_LEGAL_DOCS.has(doc)?doc:'tos',modal=q('#legalModal');
    if(location.hash!=='#'+safe&&!restoring)history.pushState(null,'','/#'+safe);
    if(!modal.open||q('#legalModalTitle')?.textContent!==LEGAL_DOCS[safe]?.title)previousLegal(safe);
    modal.dataset.route=safe;
    history.replaceState(null,'','/#'+safe);
    document.title=(LEGAL_DOCS[safe]?.title||'Information')+' | Agent Concierge';
  };
  q('#legalModal')?.addEventListener('close',()=>{
    if(!LEGAL_ROUTES.includes(location.hash.slice(1))){history.replaceState(null,'',route(currentTab));updatePageMeta(currentTab);}
  });
  q('#cookiePrefsModal')?.addEventListener('close',()=>{
    if(location.hash==='#cookie-preferences')history.replaceState(null,'',route(currentTab));
  });
  const previousDoc=switchLegalDoc;
  switchLegalDoc=function(doc){previousDoc(doc);if(q('#legalModal')?.open)document.title=(LEGAL_DOCS[doc]?.title||'Information')+' | Agent Concierge';};
  function syncLocation(){
    const raw=location.hash.slice(1).split('?')[0];
    const hash=['ai-transparency','legal/ai'].includes(raw)?'ai':raw;
    restoring=true;
    try{
      if(LEGAL_ROUTES.includes(hash)){openLegalModal(hash);return;}
      if(hash==='cookie-preferences'){if(!q('#cookiePrefsModal')?.open)openCookiePrefsModal();return;}
      if(hash&&!TABS.includes(hash)) {
        if(raw.startsWith('stop-updates=')||document.getElementById(hash))return;
        let notice=q('#unknownRouteNotice');
        if(!notice){notice=document.createElement('section');notice.id='unknownRouteNotice';notice.className='card';
          const heading=document.createElement('h1');heading.textContent='This page could not be found.';
          const text=document.createElement('p');text.textContent='Use the navigation or explore the agent catalog to continue.';
          const link=document.createElement('a');link.href='/new/en/explore.html';link.className='btn';link.textContent='Explore agents';
          notice.append(heading,text,link);(q('main')||document.body).append(notice);}
        for(const panel of document.querySelectorAll('.tab-panel[data-panel]'))panel.classList.add('hidden');
        document.title='Page not found | Agent Concierge';notice.tabIndex=-1;notice.focus({preventScroll:true});
        return;
      }
      const tab=TABS.includes(hash)?hash:(Object.keys(paths).find(key=>paths[key]===location.pathname)||document.body.dataset.pearlEntry);
      if(tab){
        if(currentTab!==tab||q('#legalModal')?.open||q('#cookiePrefsModal')?.open)switchTab(tab);
        else history.replaceState(null,'',route(tab));
      }
    }finally{restoring=false;}
  }
  addEventListener('popstate',syncLocation);
  addEventListener('hashchange',syncLocation);
  for(const link of document.querySelectorAll('#navTabs a[data-tab]'))link.onclick=event=>{
    if(modified(event))return;
    event.preventDefault();switchTab(link.dataset.tab);
  };
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]');if(!link)return;
    if(modified(event)){event.stopImmediatePropagation();return;}
    const key=link.dataset.footerKey;if(!key)return;
    event.preventDefault();event.stopImmediatePropagation();
    if(key==='cookies'){
      if(location.hash!=='#cookie-preferences')history.pushState(null,'','/#cookie-preferences');
      openCookiePrefsModal();
    }else openLegalModal(policies[key]||'tos');
  },true);
  syncLocation();

  // This local feedback complements the server's DNS and SSRF checks.
  function endpointError(value){
    if(!value.trim())return 'Enter your public endpoint URL.';
    if(/[\s\x00-\x1f\x7f]/.test(value.trim()))return 'Enter a complete endpoint URL without spaces or control characters.';
    let url;try{url=new URL(value);}catch{return 'Enter a complete http:// or https:// endpoint URL.';}
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return 'Use an http:// or https:// URL without embedded login credentials.';
    const host=url.hostname.toLowerCase().replace(/^\[|\]$/g,'').replace(/\.$/,'');
    if(!host.includes(':')&&(!host.includes('.')||host.split('.').some(label=>!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))))
      return 'Enter a valid public hostname or IP address.';
    const parts=host.split('.').map(Number);
    const privateIP=parts.length===4&&parts.every(n=>Number.isInteger(n)&&n>=0&&n<=255)&&
      (parts[0]===0||parts[0]===10||parts[0]===127||parts[0]>=224||parts[0]===169&&parts[1]===254||
       parts[0]===172&&parts[1]>=16&&parts[1]<=31||parts[0]===192&&parts[1]===168||
       parts[0]===100&&parts[1]>=64&&parts[1]<=127||parts[0]===198&&[18,19].includes(parts[1]));
    if(privateIP||host==='localhost'||host.endsWith('.localhost')||host.endsWith('.local')||
       host.endsWith('.internal')||host==='::'||host==='::1'||/^f[cd][0-9a-f]*:|^fe[89ab][0-9a-f]*:|^::ffff:/i.test(host))
      return 'Use a publicly reachable endpoint. Local and private network addresses are reserved for private connections.';
    return '';
  }
  function validateEndpoint(input,show=true){
    if(!input)return true;
    const error=endpointError(input.value);input.setCustomValidity(error);
    input.setAttribute('aria-invalid',String(Boolean(error)));
    let message=q('#'+input.id+'Error');
    if(!message){
      message=document.createElement('p');message.id=input.id+'Error';message.className='caption endpoint-feedback';message.setAttribute('role','alert');
      input.after(message);input.setAttribute('aria-describedby',((input.getAttribute('aria-describedby')||'')+' '+message.id).trim());
    }
    message.textContent=show?error:'';message.hidden=!show||!error;
    return !error;
  }
  for(const id of ['regUrl','regAutoUrl']){
    const input=q('#'+id);if(!input)continue;
    input.addEventListener('blur',()=>validateEndpoint(input,Boolean(input.value)));
    input.addEventListener('input',()=>{input.setCustomValidity('');input.removeAttribute('aria-invalid');const note=q('#'+id+'Error');if(note)note.hidden=true;});
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('#regSubmitBtn,#regInspectBtn,#uxInspectEndpoint');if(!button)return;
    if(button.id==='regSubmitBtn'){
      const authority=q('#pearlRegAuthority'),consent=q('#regTermsConsent');
      if(authority&&!authority.checked||consent&&!consent.checked)return;
    }
    const input=q(button.id==='regInspectBtn'?'#regAutoUrl':'#regUrl');
    if(!validateEndpoint(input)){event.preventDefault();event.stopImmediatePropagation();input.focus();}
  },true);
})();
