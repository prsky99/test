function standaloneAppRuntime() {
  const cfg = JSON.parse(document.getElementById('wfData').textContent);
  const run = document.getElementById('runAppBtn'), cancel = document.getElementById('cancelAppBtn');
  const status = document.getElementById('appStatus'), output = document.getElementById('stepsContainer');
  const notice = document.getElementById('appNotice'), form = document.getElementById('workflowInputs');
  const client = createAgentConciergeClient(cfg), cards = new Map();
  let current = null, polling = null, generation = 0, cancellation = false, busy = false;
  const fields = [];
  for (const field of cfg.input_fields || []) {
    const label = document.createElement('label'); label.textContent = field.label;
    const input = document.createElement(field.type === 'boolean' ? 'select' : 'input');
    input.id = 'input-' + field.id;
    if (field.type === 'boolean') {
      for (const [value,text] of [['','Use workflow default'],['true','True'],['false','False']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = text; input.append(option);
      }
    } else {
      input.type = field.type === 'string' ? 'text' : 'number'; input.placeholder = 'Leave empty to use workflow default';
      if (field.type === 'string') input.maxLength = 4096;
      else { input.min = '-1000000'; input.max = '1000000'; input.step = field.type === 'integer' ? '1' : 'any'; }
    }
    label.htmlFor = input.id; label.append(input); form.append(label); fields.push({field,input});
  }
  function format(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value, null, 2); } catch (_) { return 'Output could not be displayed.'; }
  }
  function setStatus(value) { if (status.textContent !== value) status.textContent = value; }
  function render(data) {
    setStatus('Workflow: ' + data.status);
    if (notice.textContent === 'Reconnecting to status updates. The server run continues.') notice.replaceChildren();
    const items = Array.isArray(data.node_results) ? data.node_results : Array.isArray(data.results) ? data.results : [];
    const used = new Set();
    items.forEach((item, index) => {
      const key = typeof item.node_id === 'string' ? item.node_id : 'index-' + index;
      if (used.has(key)) return; used.add(key);
      let saved = cards.get(key);
      if (!saved) {
        const card = document.createElement('section'), heading = document.createElement('h2');
        const badge = document.createElement('span'), body = document.createElement('pre');
        badge.className = 'fallback-badge'; badge.textContent = 'Fallback agent'; badge.hidden = true;
        card.append(heading,badge,body); saved = {card,heading,badge,body}; cards.set(key,saved);
      }
      const heading = (item.name || 'Step ' + (index+1)) + ' · ' + (item.status || 'pending');
      const body = format(item.output ?? item.error ?? '');
      if (saved.heading.textContent !== heading) saved.heading.textContent = heading;
      if (saved.body.textContent !== body) saved.body.textContent = body;
      saved.badge.hidden = !(item.fallback_used === true || item.is_fallback === true);
      const position = output.children[index];
      if (position !== saved.card) output.insertBefore(saved.card, position || null);
    });
    for (const [key,saved] of cards) if (!used.has(key)) { saved.card.remove(); cards.delete(key); }
  }
  function reset() {
    current = null; polling = null; cancellation = false; busy = false;
    run.disabled = false; cancel.disabled = true; for (const {input} of fields) input.disabled = false;
  }
  async function monitor(handle, controller, token) {
    try {
      await client.wait(handle, {signal:controller.signal,onUpdate:render,
        onFallback:() => { notice.textContent = 'The gateway confirmed a fallback agent was used.'; },
        onRetry:() => { notice.textContent = 'Reconnecting to status updates. The server run continues.'; }});
      if (generation === token) reset();
    } catch (error) {
      if (generation !== token || controller.signal.aborted) return;
      setStatus(error.message);
      notice.textContent = cancellation ? 'Cancellation was requested. Resume status checks the same run without starting another run.' :
        'The run may still be active. Stop requests server cancellation; Resume status reconnects without starting another run.';
      const resume = document.createElement('button'); resume.textContent = 'Resume status'; resume.type = 'button';
      resume.onclick = () => { notice.replaceChildren(); polling = new AbortController(); monitor(handle,polling,token); };
      notice.append(document.createTextNode(' '),resume);
      cancel.disabled = cancellation;
    }
  }
  cancel.onclick = async () => {
    if (!current || cancellation) return;
    cancellation = true; cancel.disabled = true;
    const handle = current, token = generation;
    polling?.abort();
    try {
      await client.cancel(handle);
      if (generation !== token) return;
      setStatus('Cancellation requested. An in-flight request may finish before stopping.');
      notice.replaceChildren();
      const check = document.createElement('button'); check.type = 'button'; check.textContent = 'Check final status';
      check.onclick = () => {
        if (generation !== token) return;
        check.disabled = true; polling = new AbortController(); monitor(handle,polling,token);
      };
      notice.append(check);
      // Keep Run disabled until the server reports a terminal state.
    } catch (error) {
      if (generation === token) { cancellation = false; cancel.disabled = false; setStatus('Cancellation could not be confirmed. You may retry Stop.'); }
    }
  };
  run.onclick = async () => {
    if (busy) return;
    const input = {};
    for (const {field,input:element} of fields) {
      if (!element.reportValidity()) return;
      if (!element.value.trim()) continue;
      input[field.id] = field.type === 'string' ? element.value : field.type === 'boolean' ? element.value === 'true' : Number(element.value);
    }
    busy = true; run.disabled = true; cancel.disabled = true; generation += 1;
    const token = generation;
    for (const {input} of fields) input.disabled = true;
    output.replaceChildren(); cards.clear(); notice.replaceChildren(); setStatus('Starting workflow…');
    try {
      current = await client.run(cfg.workflow_id, Object.keys(input).length ? {input} : {});
      cancel.disabled = false; polling = new AbortController();
      monitor(current,polling,token);
    } catch (error) { setStatus(error.message); reset(); }
  };
}
standaloneAppRuntime();
