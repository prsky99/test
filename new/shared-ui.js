/* Shared Learn interactions and semantic badge presentation. */
'use strict';
(() => {
  const all=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const q=(selector,root=document)=>root.querySelector(selector);
  const guide=q('.reference-learn-body');
  const topics=guide?all('[data-learn-tab]',guide):[];
  function activate(topic,focus=false) {
    const tab=topics.find(node=>node.dataset.learnTab===topic);
    if(!tab)return;
    for(const node of topics){const selected=node===tab;node.classList.toggle('active',selected);node.setAttribute('aria-selected',String(selected));node.tabIndex=selected?0:-1;}
    for(const panel of all('.reference-learn-panels>[role="tabpanel"]',guide))panel.hidden=panel.id!==tab.getAttribute('aria-controls');
    if(focus)tab.focus({preventScroll:true});
  }
  if(guide&&topics.length){
    const search=document.createElement('section');search.className='learn-guide-search card';
    const label=document.createElement('label');label.htmlFor='learnGuideSearch';label.textContent='Search learning guides';
    const input=document.createElement('input');input.type='search';input.id='learnGuideSearch';input.className='input';input.maxLength=120;input.autocomplete='off';input.placeholder='Try MCP, workflows, or verification';input.setAttribute('aria-controls','learnGuideResults');
    const results=document.createElement('div');results.id='learnGuideResults';results.className='learn-guide-results';
    const status=document.createElement('p');status.className='muted';status.setAttribute('role','status');
    search.append(label,input,status,results);guide.prepend(search);
    input.addEventListener('input',()=>{
      results.replaceChildren();const query=input.value.trim().toLocaleLowerCase();
      if(!query){status.textContent='';return;}
      const matches=all('.reference-learn-panels>[role="tabpanel"] h2,.reference-learn-panels>[role="tabpanel"] h3',guide).filter(heading=>{
        const section=heading.closest('.card,article,section')||heading.parentElement;
        return section.textContent.toLocaleLowerCase().includes(query);
      }).slice(0,20);
      const protocols=Object.entries(protocolDetails).filter(([key,values])=>(key+' '+values.join(' ')).toLocaleLowerCase().includes(query));
      const count=matches.length+protocols.length;
      status.textContent=count?count+' matching guides':'No matching guides. Try a protocol or task name.';
      for(const [key,values] of protocols){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=values[0];button.addEventListener('click',()=>{activate('basics');q('[data-learn-protocol="'+key+'"]')?.click();q('#learn-protocol-context')?.scrollIntoView({block:'center'});});results.append(button);}
      for(const heading of matches){
        const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=heading.textContent;
        button.addEventListener('click',()=>{const panel=heading.closest('[role="tabpanel"]');const tab=topics.find(t=>t.getAttribute('aria-controls')===panel?.id);if(tab)activate(tab.dataset.learnTab);heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});});
        results.append(button);
      }
    });
  }
  const protocolDetails={
    a2a:['A2A: agent collaboration','Use an agent’s supported connection to delegate a task and inspect its returned result.','Review the selected agent, its expected input and the scope of the task before connecting.'],
    mcp:['MCP: tools and resources','An agent can use exposed tools, data and resources through a supported MCP connection.','Inspect the available capability, its required arguments and the information it receives.'],
    x402:['x402: HTTP service access','A service can communicate its access requirements through HTTP.','Review the provider’s current requirements and the intended request before using the service.']
  };
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-learn-tab]');if(tab&&guide?.contains(tab)){activate(tab.dataset.learnTab);return;}
    const protocol=event.target.closest('[data-learn-protocol]');if(!protocol||!protocolDetails[protocol.dataset.learnProtocol])return;
    activate('basics');
    for(const node of all('[data-learn-protocol]')){const selected=node===protocol;node.setAttribute('aria-pressed',String(selected));node.closest('.card')?.classList.toggle('protocol-selected',selected);}
    const context=q('#learn-protocol-context');if(!context)return;
    const [title,description,review]=protocolDetails[protocol.dataset.learnProtocol];
    const heading=document.createElement('h3');heading.textContent=title;
    const text=document.createElement('p');text.textContent=description;
    const note=document.createElement('p');note.textContent=review;
    context.replaceChildren(heading,text,note);context.hidden=false;
  });
  guide?.addEventListener('keydown',event=>{
    const tab=event.target.closest('[data-learn-tab]');if(!tab)return;
    const key=event.key;if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(key))return;
    event.preventDefault();const index=topics.indexOf(tab),next=key==='Home'?0:key==='End'?topics.length-1:(index+(['ArrowUp','ArrowLeft'].includes(key)?-1:1)+topics.length)%topics.length;
    activate(topics[next].dataset.learnTab,true);
  });
  const selector='.kind-badge,.badge.protocol,.chat-protocol';
  function decorate(root) {
    if(!(root instanceof Element))return;
    const nodes=[...(root.matches(selector)?[root]:[]),...all(selector,root)];
    for(const node of nodes){const key=node.textContent.trim().toLowerCase();if(!['a2a','mcp','x402','any'].includes(key))continue;const label={a2a:'A2A',mcp:'MCP',x402:'x402',any:'Any'}[key];if(node.textContent!==label)node.textContent=label;if(node.dataset.protocol!==key)node.dataset.protocol=key;}
  }
  // Reconstruct official contact links after edge HTML processing. No injected
  // email-decoding script or broader script policy is needed.
  function contacts(root) {
    if(!(root instanceof Element))return;
    const links=[...(root.matches('[data-service-mailbox]')?[root]:[]),...all('[data-service-mailbox]',root)];
    for(const link of links){const box=link.dataset.serviceMailbox;if(!['contact','privacy','security','support'].includes(box))continue;const address=box+'@'+'agentconcierge.biz';if(link.getAttribute('href')!=='mailto:'+address)link.href='mailto:'+address;if(link.textContent!==address)link.textContent=address;}
  }
  contacts(document.body);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)contacts(node);}).observe(document.body,{childList:true,subtree:true});
  decorate(document.body);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)decorate(node);}).observe(document.body,{childList:true,subtree:true});
})();
