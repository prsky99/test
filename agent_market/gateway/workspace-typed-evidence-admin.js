/* Private typed lineage. Source retention never dispatches an agent. */
(() => {
  'use strict';
  const PROFILE = 'p2-01-typed-evidence-profile-v1';
  let dialog, content, status, workspace = '', session = '', epoch = 0, busy = false;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
  const id = prefix => `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('')}`;
  const stamp = () => ({epoch, workspace, session});
  const valid = captured => dialog?.open && captured.epoch === epoch && captured.workspace === workspace && captured.session === session && identity() === session;
  const tell = text => { if (status) status.textContent = text; };
  const button = (label, run) => { const element = node('button', label); element.type = 'button'; element.className = 'btn'; element.addEventListener('click', run); return element; };
  const field = (parent, text, tag = 'input') => { const label = node('label', text), input = node(tag); if (tag === 'textarea') { input.rows = 10; input.spellcheck = false; } input.style.width = '100%'; input.style.boxSizing = 'border-box'; label.append(input); parent.append(label); return input; };
  const line = (parent, text) => parent.append(node('p', text));
  function leave() { epoch++; workspace = session = ''; busy = false; dialog?.close(); dialog?.remove(); dialog = content = status = null; }
  function onSession() { if (session && (identity() !== session || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, body) {
    const value = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/reliability/typed${path}`, body === undefined ? {silent: true} : {method: 'POST', json: body, silent: true});
    if (value?.ok !== true || value.profile !== PROFILE) throw Error('invalid_typed_lineage');
    return value.result;
  }
  async function refresh() {
    if (busy) return; epoch++; busy = true; const captured = stamp(); content.replaceChildren(); tell('Reading current typed lineage authority.');
    try {
      const options = await request('/options'); if (!valid(captured)) return;
      line(content, 'Review existing signed executions. Retention uses each node’s current cohort permission and makes no provider calls. Quality and business outcomes remain independently unassessed.');
      const flow = field(content, 'Typed flow ', 'select'); flow.append(new Option('Choose a private typed flow', ''));
      for (const item of options.flows) flow.append(new Option(item.name || item.id, item.id));
      const runs = field(content, 'Signed execution ', 'select'), output = node('section'); content.append(output);
      const bindings = field(content, 'Current node consent and case references ', 'textarea'); bindings.value = '[]';
      const label = node('label'), confirm = node('input'); confirm.type = 'checkbox'; confirm.checked = false;
      label.append(confirm, ' Authorize encrypted retention of this existing run’s necessary node sources for the selected current evaluation purposes.'); content.append(label);
      if (!options.can_manage) { bindings.disabled = true; confirm.disabled = true; }
      let activeRun = null;
      const render = value => {
        output.replaceChildren(); activeRun = value;
        line(output, `${value.status} · ${value.attempts} dispatched node attempts · one logical run · ${value.closed_actions} observed closed actions.`);
        line(output, value.evidence_current ? 'Current retained sources are available. Independent quality remains separate.' : 'Source fidelity is unassessable until current permitted sources are retained.');
        for (const item of value.nodes) {
          const section = node('section'); section.className = 'card'; section.style.padding = '12px'; section.style.margin = '10px 0';
          line(section, `${item.node_id} · ${item.status} · ${item.contract_id} · ${item.source_fidelity}`);
          line(section, `Parent nodes: ${item.parents.join(', ') || 'none'}. Projection fields: ${Object.keys(item.projections).join(', ') || 'none'}.`);
          if (item.branch) line(section, `Conditional path: ${item.branch.taken ? 'selected' : 'skipped or unreached'}.`);
          output.append(section);
        }
      };
      flow.addEventListener('change', async () => {
        if (busy) return; epoch++; const selected = stamp(); busy = true; activeRun = null; output.replaceChildren(); runs.replaceChildren(); confirm.checked = false; bindings.value = '[]';
        try { if (flow.value) { const values = await request(`/runs?flow_id=${encodeURIComponent(flow.value)}`); if (!valid(selected)) return; runs.append(new Option('Choose a signed execution', '')); for (const item of values) runs.append(new Option(`${item.id} · ${item.status}`, item.id)); } }
        catch { if (valid(selected)) tell('Current private executions could not be read.'); }
        finally { if (valid(selected)) busy = false; }
      });
      runs.addEventListener('change', async () => {
        if (busy) return; epoch++; const selected = stamp(); busy = true; confirm.checked = false; activeRun = null; output.replaceChildren();
        try { if (runs.value) { const value = await request(`/runs/${encodeURIComponent(runs.value)}?flow_id=${encodeURIComponent(flow.value)}`); if (!valid(selected)) return; render(value); bindings.value = JSON.stringify(value.nodes.map(item => ({node_id: item.node_id, consent_id: '', case_id: '', source_id: id('res'), observation_id: id('reb')})), null, 2); tell('Current signed lineage loaded. No provider calls were made.'); } }
        catch { if (valid(selected)) tell('Authority or signed execution evidence is unavailable.'); }
        finally { if (valid(selected)) busy = false; }
      });
      const capture = button('Retain existing node sources', async () => {
        if (busy) return;
        if (!options.can_manage || !confirm.checked || !activeRun) { tell('Choose an execution and select the purpose-specific retention authorization.'); return; }
        let parsed; try { parsed = JSON.parse(bindings.value); } catch { tell('Provide the exact bounded node references.'); return; }
        confirm.checked = false; busy = true; const selected = stamp();
        try {
          await request('/captures', {command_id: id('rec'), flow_id: flow.value, run_id: runs.value, logical_task_id: id('ret'), bindings: parsed, authorized: true, notice: options.notice});
          const value = await request(`/runs/${encodeURIComponent(runs.value)}?flow_id=${encodeURIComponent(flow.value)}`);
          if (valid(selected)) { render(value); tell('Existing sources retained under current permission. No provider calls were made.'); }
        } catch (error) { if (valid(selected)) tell([401,403,404].includes(error?.status) ? 'Session or scoped access changed. Close and reopen this view.' : 'The capture could not be confirmed. Read current state before submitting again.'); }
        finally { if (valid(selected)) busy = false; }
      });
      capture.disabled = !options.can_manage || !options.encryption_configured; content.append(capture);
      if (!options.encryption_configured) line(content, 'Authenticated source encryption is not configured. Retention remains unavailable.');
      tell('Private typed lineage ready. No provider calls were made.');
    } catch { if (valid(captured)) tell('The current staff session or private workspace is unavailable.'); }
    finally { if (valid(captured)) busy = false; }
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceTypedEvidenceDialog';
    Object.assign(dialog.style, {width: 'min(1040px,94vw)', maxWidth: '94vw', maxHeight: '88vh', boxSizing: 'border-box', borderRadius: '18px', padding: '24px', overflow: 'auto', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const heading = node('h2', 'Private typed execution evidence'); heading.id = 'workspaceTypedEvidenceTitle'; dialog.setAttribute('aria-labelledby', heading.id);
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); for (const [key,value] of Object.entries({viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'aria-hidden': 'true'})) icon.setAttribute(key,value);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M9 3h6l1 2h4v16H4V5h4l1-2M8 11h8M8 15h5'); icon.append(path); heading.prepend(icon,document.createTextNode(' '));
    status = node('p'); status.setAttribute('role', 'status'); content = node('div');
    dialog.append(heading,button('Close typed evidence',leave),button('Read current lineage state',refresh),status,content); document.body.append(dialog); dialog.addEventListener('cancel',leave); dialog.showModal(); await refresh();
  }
  window.WorkspaceTypedEvidenceAdmin = {open, leave, onSession};
})();
