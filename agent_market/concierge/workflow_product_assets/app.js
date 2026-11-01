'use strict';
const form = document.querySelector('form');
const statusLine = document.querySelector('[role="status"]');
const results = document.querySelector('#results');
const submit = form.querySelector('button');
let current = null;
const origin = 'https://agentconcierge.biz';
async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(origin + path, {...options, credentials:'omit', redirect:'error', signal:controller.signal});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'The request could not be completed.');
    return value;
  } finally { clearTimeout(timer); }
}
function show(value) {
  results.replaceChildren();
  function section(name, records) {
    const heading = document.createElement('h2'); heading.textContent = name; results.append(heading);
    if (!records.length) {const empty = document.createElement('p'); empty.textContent = 'No matching records were returned.'; results.append(empty);}
    for (const record of records) {
      const article = document.createElement('article');
      const title = document.createElement('h3'); title.textContent = record.title || 'Source record'; article.append(title);
      try {
        const url = new URL(record.url);
        if (url.protocol === 'https:') {
          const link = document.createElement('a'); link.href = url.href; link.textContent = 'Open original source';
          link.target = '_blank'; link.rel = 'noopener noreferrer'; article.append(link);
        }
      } catch (_) {}
      const excerpt = document.createElement('p'); excerpt.textContent = record.excerpt || ''; article.append(excerpt);
      const stamp = document.createElement('p'); stamp.className = 'muted';
      stamp.textContent = 'Retrieved: ' + (record.retrieved_at || record.accessed_at || 'Not available'); article.append(stamp);
      results.append(article);
    }
  }
  if (Array.isArray(value.first)) {section('First topic',value.first); section('Second topic',value.second || []);}
  else section('Source records',value.items || value.references || []);
  if (value.partial || value.first_partial || value.second_partial) {
    const note = document.createElement('p'); note.textContent = 'Some source records are unavailable. Review the original sources.'; results.prepend(note);
  }
}
form.addEventListener('submit',async event => {
  event.preventDefault(); if (current) return;
  submit.disabled = true; form.setAttribute('aria-busy','true'); results.replaceChildren();
  const input = {};
  for (const field of form.querySelectorAll('[data-input]')) input[field.name] = field.type === 'number' ? Number(field.value) : field.value.trim();
  const consent = document.querySelector('#consent');
  const body = {template_id:Number(form.dataset.workflow),definition_hash:form.dataset.version,input,
    allow_fallback:consent.checked,fallback_notice:'readonly-fallback-v1'};
  consent.checked = false;
  const started = Date.now(); const clock = setInterval(() => {statusLine.textContent = 'Working… ' + Math.floor((Date.now()-started)/1000) + 's';},1000);
  try {
    statusLine.textContent = 'Starting research…';
    current = await request('/api/workflows/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    let state;
    for (let i=0;i<80;i++) {
      await new Promise(resolve => setTimeout(resolve,Math.min(2500,700+i*100)));
      state = await request('/api/workflows/runs/'+encodeURIComponent(current.run_id),{headers:{'X-Workflow-Key':current.run_key}});
      if (['succeeded','failed','cancelled'].includes(state.status)) break;
    }
    if (state?.status !== 'succeeded') throw new Error('Research could not be completed. An unavailable or uncertain request was not automatically repeated.');
    const nodes = state.node_results || [];
    const output = nodes[nodes.length-1]?.data || {};
    show(output.structuredContent || output);
    clearInterval(clock);
    statusLine.textContent = nodes.some(n => n.fallback_used) ? 'Complete. One verified alternative source was used.' : 'Complete. Original sources returned the results.';
  } catch (error) {
    clearInterval(clock); statusLine.textContent = error.name === 'AbortError' ? 'The response was delayed. This request was not automatically resubmitted.' : error.message;
  } finally {clearInterval(clock); current = null; submit.disabled = false; form.setAttribute('aria-busy','false');}
});
