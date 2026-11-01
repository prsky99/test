/* Local design interactions. No live API calls or authentication requests. */
'use strict';
(() => {
  const q = (s, root = document) => root.querySelector(s);
  const all = (s, root = document) => [...root.querySelectorAll(s)];
  const dialog = q('#preview-dialog');
  const dialogBody = q('#dialog-body');
  let returnFocus = null;
  let toastTimer;
  let visibleLimit = 4;
  let released = false;
  let retainedProtocol = 'A2A';
  let protocolWasSelected = false;
  const safeStorage = {
    get(key) { try { return sessionStorage.getItem('pearl-preview:' + key); } catch { return null; } },
    set(key, value) { try { sessionStorage.setItem('pearl-preview:' + key, value); } catch { /* Storage is optional. */ } },
    remove(key) { try { sessionStorage.removeItem('pearl-preview:' + key); } catch { /* Storage is optional. */ } }
  };
  const toast = message => {
    const el = q('#toast');
    if (!el) return;
    clearTimeout(toastTimer);
    el.textContent = message;
    el.hidden = false;
    toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
  };
  const cloneTemplate = name => {
    const source = q('#template-' + name) || q('#policy-' + name);
    if (!source) return document.createTextNode('This surface is a design preview.');
    const fragment = source.content.cloneNode(true);
    const map = new Map();
    all('[id]', fragment).forEach(el => { map.set(el.id, 'dialog-' + el.id); el.id = 'dialog-' + el.id; });
    all('[for]', fragment).forEach(el => { if (map.has(el.htmlFor)) el.htmlFor = map.get(el.htmlFor); });
    all('[data-enable]', fragment).forEach(el => { if (map.has(el.dataset.enable)) el.dataset.enable = map.get(el.dataset.enable); });
    all('[aria-controls], [aria-labelledby]', fragment).forEach(el => ['aria-controls','aria-labelledby'].forEach(attr => { const value = el.getAttribute(attr); if (map.has(value)) el.setAttribute(attr, map.get(value)); }));
    return fragment;
  };
  const openDialog = (title, content, type = '') => {
    if (!dialog) return;
    if (!dialog.open) returnFocus = document.activeElement;
    q('#dialog-title').textContent = title;
    dialogBody.replaceChildren(typeof content === 'string' ? document.createTextNode(content) : content);
    dialog.classList.toggle('reference-modal', type === 'reference');
    dialog.classList.toggle('drawer', type === 'drawer');
    if (!dialog.open) dialog.showModal();
    q('[data-action="close-dialog"]', dialog).focus();
  };
  const closeDialog = () => { if (dialog?.open) dialog.close(); };
  dialog?.addEventListener('close', () => { if (returnFocus?.isConnected) returnFocus.focus(); });
  dialog?.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(); } });
  async function busy(button, fn, label = 'Reviewing…') {
    if (!button || button.disabled || button.getAttribute('aria-busy') === 'true') return;
    const old = button.textContent;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = label;
    try {
      await new Promise(resolve => setTimeout(resolve, 320));
      await fn();
    } catch {
      toast('This preview action could not be completed. Your input is kept.');
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      button.textContent = old;
    }
  }
  function chosenProtocol(name) { return q('input[name="' + name + '"]:checked')?.value || 'A2A'; }
  function search(reset = true) {
    const text = (q('#query')?.value || '').trim().toLowerCase();
    const protocol = chosenProtocol('search-protocol');
    const category = q('#category')?.value || 'All categories';
    const normalized = text.replace(/technology\s+news/g, 'news');
    const words = normalized.split(/\s+/).filter(Boolean);
    const cards = all('#agent-results .agent-card');
    if (reset) visibleLimit = 4;
    let matches = 0, shown = 0;
    cards.forEach(card => {
      const corpus = card.textContent.toLowerCase();
      const matchText = !words.length || words.every(word => corpus.includes(word));
      const matchProtocol = protocol === 'Any' || card.dataset.agentProtocol === protocol;
      const tags = card.dataset.agentTags.toLowerCase();
      const categoryTags = {
        'Docs, Knowledge Bases & RAG': /documentation|reference/,
        'Web Search & Scraping': /research/,
        'Data Utilities & Format Conversion': /data|conversion/,
        'Database & Analytics': /analysis/
      };
      const matchCategory = category === 'All categories' || (categoryTags[category] ? categoryTags[category].test(tags) : category === 'News & Research' ? /news|research/.test(tags) : tags.includes(category.toLowerCase()));
      const matchEvidence = !q('#execution')?.checked || card.dataset.execution === 'true';
      const index = matchText && matchProtocol && matchCategory && matchEvidence ? matches++ : -1;
      card.hidden = index < 0 || index >= visibleLimit;
      if (!card.hidden) shown++;
    });
    q('#search-count').textContent = shown + ' of ' + matches + ' matching example agents';
    q('#search-empty').hidden = matches > 0;
    q('#load-more').hidden = matches <= shown;
  }
  function initSearch() {
    const extra = q('#extra-agents');
    if (!extra) return;
    q('#agent-results').append(extra.content.cloneNode(true));
    all('#agent-results .agent-card').forEach((card, index) => { card.hidden = index >= 4; });
    q('#search-count').textContent = '4 of 8 example agents shown';
    const params = new URLSearchParams(location.search);
    const requestedProtocol = params.get('protocol');
    const requestedCategory = params.get('category');
    const requestedView = params.get('view');
    let applied = false;
    if (['A2A','MCP','x402','Any'].includes(requestedProtocol)) {
      q('input[name="search-protocol"][value="' + requestedProtocol + '"]').checked = true;
      applied = true;
    }
    if (all('#category option').some(option => option.value === requestedCategory)) {
      q('#category').value = requestedCategory;
      applied = true;
    }
    if (applied) search();
    if (applied || requestedView === 'new') {
      const context = q('#catalog-context');
      context.textContent = requestedView === 'new'
        ? 'New arrivals · This design preview shows a small example collection. Live arrival ordering is not connected.'
        : 'Catalog selection applied to the example collection. Live catalog search is not connected in this design preview.';
      context.hidden = false;
    }
  }
  function updateChatProtocol(question) {
    const explicit = question.match(/\b(A2A|MCP|x402)\b/i);
    const selected = chosenProtocol('chat-protocol');
    // The explicit selector takes precedence over a protocol written in a question.
    const canonical = explicit ? ['A2A','MCP','x402'].find(p => p.toLowerCase() === explicit[1].toLowerCase()) : null;
    retainedProtocol = protocolWasSelected ? selected : (canonical || selected || retainedProtocol);
    const radio = q('input[name="chat-protocol"][value="' + retainedProtocol + '"]');
    if (radio) radio.checked = true;
    all('[data-selected-protocol]').forEach(el => { el.textContent = retainedProtocol; });
    all('.recommendation .badge.protocol').forEach(el => { el.textContent = retainedProtocol; });
  }
  const actions = {
    'refresh-status'(button) {
      return busy(button, () => {
        q('#snapshot-feedback').textContent = 'Snapshot reviewed · 19 Oct 2026, 10:07 UTC. Live updates are not connected in this design preview.';
      }, 'Reviewing snapshot…');
    },
    theme(button) {
      const dark = document.body.dataset.theme !== 'dark';
      document.body.dataset.theme = dark ? 'dark' : 'light';
      all('[data-action="theme"]').forEach(el => el.setAttribute('aria-pressed', String(dark)));
      safeStorage.set('theme', dark ? 'dark' : 'light');
    },
    menu(button) {
      const open = button.getAttribute('aria-expanded') !== 'true';
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
      q('#public-nav')?.classList.toggle('is-open', open);
    },
    reference() {
      const img = document.createElement('img');
      const value = document.body.dataset.reference;
      if (!value?.startsWith('../design/')) return;
      img.src = value;
      img.alt = 'Original Pearl Connection design reference';
      openDialog('Design reference', img, 'reference');
    },
    'close-dialog': closeDialog,
    'agent-details'(button) {
      openDialog('Agent details', cloneTemplate('agent'), 'drawer');
      const card = button?.closest('.agent-card');
      if (card) {
        const name = q('h3', card)?.textContent;
        if (name) q('h3', dialogBody).textContent = name;
        const description = q(':scope > p', card)?.textContent;
        if (description) q('p', dialogBody).textContent = description;
        retainedProtocol = card.dataset.agentProtocol || retainedProtocol;
      }
      if (document.body.dataset.page === 'chat.html') {
        q('h3', dialogBody).textContent = q('.recommendation [data-rec-name]')?.textContent || 'Research assistant';
        q('p', dialogBody).textContent = 'Helps you find and summarize relevant public research sources with clear citations.';
      }
      all('[data-selected-protocol]', dialog).forEach(el => { el.textContent = retainedProtocol; });
    },
    report(button) { openDialog('Recorded report', cloneTemplate('report')); const name = q('h3', button?.closest('.agent-card') || document)?.textContent; if (button?.closest('.agent-card') && name) q('h3', dialogBody).textContent = name; },
    connection() { openDialog('Review connection', 'Example preview · Inspect the selected protocol, public endpoint and exact input in the live service before connecting.'); },
    'quick-search'(button) { q('#query').value = button.dataset.query; search(); },
    'clear-search'() { q('#query').value = ''; q('#category').selectedIndex = 0; q('input[name="search-protocol"][value="Any"]').checked = true; search(); },
    'load-more'(button) { return busy(button, () => { visibleLimit += 4; search(false); }, 'Loading more…'); },
    example(button) {
      all('[data-action="example"]').forEach(el => el.classList.toggle('active', el === button));
      all('[data-example-title]').forEach(el => { el.textContent = button.dataset.example; });
      q('#test-request').value = 'Find public information about ' + button.dataset.example.toLowerCase() + ' with source links.';
    },
    'reset-test'() { q('#test-request').value = 'Find recent technology news with source links.'; },
    'example-source'() { openDialog('Illustrative source', 'This is a source layout example. No current article or external execution is represented.'); },
    'workflow-template'(button) {
      all('[data-action="workflow-template"]').forEach(el => el.classList.toggle('active', el === button));
      q('#workflow-name').textContent = button.dataset.name;
      q('#workflow-input').value = 'Find public information about ' + button.dataset.name.toLowerCase() + '.';
      toast('Example template selected. Review its inputs before running.');
    },
    'workflow-review'() { openDialog('Review before running', cloneTemplate('run')); },
    'run-reviewed'(button) {
      return busy(button, () => { closeDialog(); toast('Illustrative test complete. No external agent was executed.'); }, 'Running preview…');
    },
    'webapp-run'(button) {
      return busy(button, () => { const status = q('#webapp-status'); if (status) status.textContent = 'Preview complete · Illustrative result'; toast('Preview complete. No external agent was executed.'); }, 'Running preview…');
    },
    download() {
      const a = document.createElement('a');
      a.href = 'assets/webapp-preview.zip';
      a.download = 'agent-concierge-webapp-preview.zip';
      document.body.append(a); a.click(); a.remove();
      toast('Downloading the local web app preview.');
    },
    alternative() { const name = q('.recommendation [data-rec-name]'); if (name) { name.textContent = name.textContent === 'Research assistant' ? 'Public knowledge agent' : 'Research assistant'; const side = all('.chat-layout aside h3').at(-1); if (side) side.textContent = name.textContent; } toast('One alternative example shown.'); },
    provider(button) { openDialog('Continue with ' + button.dataset.provider, 'This is a design preview. Provider sign-in is not connected here. No account is created and no provider request is sent.'); },
    availability() { toast('Provider availability must be checked in the live service.'); },
    'create-workspace'() { openDialog('Create workspace', cloneTemplate('create')); },
    'invite-review'() { openDialog('Review invitation', cloneTemplate('invitation')); },
    'accept-invite'() { closeDialog(); toast('Invitation acceptance preview. No workspace access was changed.'); },
    'decline-invite'() { closeDialog(); toast('Invitation decline preview. No invitation was changed.'); },
    'revoke-invite'() { openDialog('Revoke invitation?', 'This invitation is illustrative. No actual access will be changed.'); },
    'rename-workspace'() { openDialog('Rename workspace', cloneTemplate('create')); },
    'leave-workspace'() { openDialog('Leave workspace?', 'This is an example workspace. No real membership will be changed.'); },
    'save-draft'(button) { return busy(button, () => { safeStorage.set('draft-name', q('#draft-name')?.value || 'Technology news brief'); toast('Draft name saved for this design preview session.'); }, 'Saving…'); },
    'select-step'(button) { q('#selected-step').textContent = button.dataset.step; },
    'add-step'() { openDialog('Add a reviewed step', 'The private workflow design supports two to six read-only tasks. Review the chosen agent, inputs and prior result connections before saving.'); },
    'connect-step'() { toast('Select a prior result in the selected-step inspector, then review the change.'); },
    'review-change'() { openDialog('Review this change', 'Review the selected agent, input and prior result connection before saving a new private draft. No task will run.'); },
    suggest() { openDialog('Suggestion requires review', 'A suggestion does not run or release a workflow. Review all selected agents and inputs first.'); },
    'create-release'(button) { return busy(button, () => { released = true; toast('Release preview created for this page only.'); }); },
    'authorize-origin'() {
      const origin = q('#app-origin');
      let valid = false;
      try { const u = new URL(origin.value); valid = u.protocol === 'https:' && u.origin === origin.value && !u.username && !u.password; } catch { /* Invalid origins are rejected. */ }
      if (!released || !valid) { toast('Create the example release and enter an exact HTTPS origin first.'); return; }
      q('#download-reviewed').disabled = false;
      toast('Origin authorization preview. No live deployment was authorized.');
    },
    'sign-out'() { safeStorage.remove('draft-name'); location.assign('signed-out.html'); },
    'cookie-settings'() { openDialog('Cookie preferences', cloneTemplate('cookies')); },
    'accept-cookies'() { safeStorage.set('analytics-choice', 'allowed'); toast('Optional analytics selected for this preview. No analytics is sent.'); closeDialog(); },
    'reject-cookies'() { safeStorage.set('analytics-choice', 'rejected'); all('input[id^="analytics"]').forEach(el => { el.checked = false; }); toast('Non-essential storage rejected in this preview.'); closeDialog(); },
    'save-cookies'() { const source = dialog?.open ? dialog : document; safeStorage.set('analytics-choice', q('input[id*="analytics"]', source)?.checked ? 'allowed' : 'rejected'); toast('Example browser preferences saved. No telemetry is sent.'); closeDialog(); },
    'privacy-opt-out'() { safeStorage.set('analytics-choice', 'rejected'); toast('Preview opt-out recorded for this session. No live request was sent.'); },
    'pause-updates'() { toast('Pause preview. No live update request was changed.'); },
    'renew-updates'() { toast('Renewal preview. No live update request was changed.'); },
    'stop-updates'() { openDialog('Stop task updates?', 'This design preview has no active update request. No live request will be stopped.'); },
    'withdraw-marketing'() { toast('Withdrawal preview. No marketing preference was changed.'); },
    'delete-notifications'() { openDialog('Delete notification data?', 'Notification data is separate from conversation records. This preview contains no real notification data.'); },
    'notification-setup'() { openDialog('Browser notification verification', 'The live service requires native browser permission, a PushSubscription and confirmation by clicking a delivered test notification. This preview does not create a subscription.'); },
    'decline-verification'() { toast('Pending-verification deletion preview. No live request exists here.'); },
    import() { openDialog('Import public information', cloneTemplate('import')); },
    'sample-search'(button) { return busy(button, () => toast('Example search complete. Input retained.'), 'Searching…'); },
    'sample-more'(button) { return busy(button, () => toast('Example additional results loaded.'), 'Loading more…'); },
    sample() { toast('Example interaction complete.'); },
    toast() { toast('Example preference saved.'); },
    policy(button) { openDialog(button.dataset.policy === 'tos' ? 'Terms of Service' : 'Privacy Policy', cloneTemplate(button.dataset.policy)); },
    'delete-node'() { openDialog('Delete this node?', 'The selected draft step and its connections would be removed after confirmation. This design preview keeps its example graph.'); },
    'confirm-delete-node'() { toast('Delete-node preview. The example graph is retained.'); },
    'reset-template'() { openDialog('Reset template?', 'Unsaved changes would be replaced by the default template. This preview keeps the example graph.'); }
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (!button || button.disabled) return;
    const fn = actions[button.dataset.action];
    if (fn) { event.preventDefault(); fn(button); }
  });
  function activateTab(tab) {
    const parent = tab.parentElement;
    all('[data-tab]', parent).forEach(el => { el.setAttribute('aria-selected', String(el === tab)); el.tabIndex = el === tab ? 0 : -1; });
    const scope = parent.parentElement;
    all('[data-tab-panel]', scope).forEach(panel => { panel.hidden = panel.dataset.tabPanel !== tab.dataset.tab; });
  }
  // Tab buttons are independent of command actions.
  document.addEventListener('click', event => { const tab = event.target.closest('[data-tab]'); if (tab) activateTab(tab); });
  document.addEventListener('change', event => {
    const field = event.target;
    if (field.matches('[data-enable]')) {
      const scope = field.closest('dialog') || document;
      const target = q('#' + field.dataset.enable, scope);
      if (target) target.disabled = !field.checked;
    }
    if (field.name === 'chat-protocol') { protocolWasSelected = true; retainedProtocol = field.value; updateChatProtocol(''); }
  });
  document.addEventListener('keydown', event => {
    const currentTab = event.target.closest('[role="tab"]');
    if (currentTab && ['ArrowRight','ArrowLeft','Home','End'].includes(event.key)) {
      const tabs = all('[role="tab"]', currentTab.parentElement);
      const offset = event.key === 'ArrowLeft' ? -1 : 1;
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (tabs.indexOf(currentTab) + offset + tabs.length) % tabs.length;
      event.preventDefault(); activateTab(tabs[index]); tabs[index].focus();
    }
    if (event.key === 'Escape') { const menu = q('#public-nav'); if (menu?.classList.contains('is-open')) { menu.classList.remove('is-open'); const button = q('[data-action="menu"]'); button.setAttribute('aria-expanded', 'false'); button.focus(); } }
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('[data-form]')) return;
    event.preventDefault();
    if (!form.reportValidity()) return;
    const submitter = event.submitter || q('button:not([type="button"])', form);
    const type = form.dataset.form;
    if (type === 'home') { const p = q('#home-protocol').value; safeStorage.set('chat-protocol', p); location.assign('chat.html'); return; }
    if (type === 'search') { busy(submitter, () => search(), 'Searching…'); return; }
    if (type === 'test') { busy(submitter, () => toast('Illustrative test complete. No external agent was executed.'), 'Running preview…'); return; }
    if (type === 'chat') {
      busy(submitter, () => { updateChatProtocol(q('#chat-input').value); const el = document.createElement('p'); el.className = 'note'; el.textContent = 'Example recommendation updated for the selected protocol. Review one relevant agent and its recorded checks.'; q('#chat-messages').prepend(el); q('#chat-input').value = ''; toast('One example recommendation is shown.'); }, 'Finding…'); return;
    }
    if (type === 'create-workspace') { closeDialog(); toast('Workspace creation preview. No workspace was created.'); return; }
    if (type === 'invite') { toast('Invitation preview. No message or access grant was sent.'); return; }
    if (type === 'import') {
      const value = q('textarea', form).value;
      try {
        const parsed = JSON.parse(value); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
        const target = q('main form[data-form="listing"]');
        if (target) {
          for (const [key, selector] of [['name','#agent-name'],['description','#description']]) { const input = q(selector, target); if (input && typeof parsed[key] === 'string') input.value = parsed[key].slice(0,1000); }
          if (typeof parsed.url === 'string') { const u = new URL(parsed.url); if (u.protocol === 'https:' && !u.username && !u.password) q('#public-endpoint', target).value = u.href; }
        }
        toast('Public fields prepared for review. Nothing was submitted.'); closeDialog();
      }
      catch { toast('Enter a valid public JSON object. Your input is kept.'); }
      return;
    }
    if (type === 'task-updates') { toast('Request review preview. No update request or permission was created.'); return; }
    if (type === 'listing' || type === 'contact') { busy(submitter, () => toast('Example form reviewed. Nothing was submitted.'), 'Reviewing…'); return; }
    if (type === 'node') { toast('Node change reviewed. No workflow was executed.'); return; }
  });
  const savedTheme = safeStorage.get('theme');
  if (!document.body.hasAttribute('data-theme')) document.body.dataset.theme = savedTheme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  all('[data-action="theme"]').forEach(el => el.setAttribute('aria-pressed', String(document.body.dataset.theme === 'dark')));
  const savedName = safeStorage.get('draft-name');
  if (savedName && q('#draft-name')) q('#draft-name').value = savedName;
  const savedProtocol = safeStorage.get('chat-protocol');
  if (savedProtocol && ['A2A','MCP','x402','Any'].includes(savedProtocol)) { const input = q('input[name="chat-protocol"][value="' + savedProtocol + '"]'); if (input) input.checked = true; }
  initSearch();
  all('[role="tab"]').forEach(el => { el.tabIndex = el.getAttribute('aria-selected') === 'true' ? 0 : -1; });
  if (q('#compare-page')) {
    const pages = window.PEARL_PAGES || [];
    function compare(file) {
      const selected = pages.find(p => p.file === file) || pages[0];
      if (!selected) return;
      q('#compare-page').value = selected.file;
      q('#compare-frame').src = selected.file;
      q('#compare-reference').src = selected.reference;
      q('#compare-reference').alt = selected.title + ' — original design reference';
      q('#compare-publication').src = 'assets/previews/' + selected.file.replace(/\.html$/, '') + '-' + q('#compare-width').value + '.png';
      q('#compare-publication').alt = selected.title + ' — real browser capture';
      q('#compare-open').href = selected.file;
    }
    compare(new URLSearchParams(location.search).get('page'));
    q('#compare-page').addEventListener('change', event => compare(event.target.value));
    q('#compare-width').addEventListener('change', () => compare(q('#compare-page').value));
  }
})();
/* Shared reference interactions. */
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
  decorate(document.body);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)decorate(node);}).observe(document.body,{childList:true,subtree:true});
})();
