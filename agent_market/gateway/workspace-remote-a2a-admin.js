/* Named staff may send once or explicitly inspect one retained remote task. */
(() => {
  'use strict';
  const PROFILE = 'private-a2a03-task-poll-v1', SESSION_PROFILE = 'private-a2a03-session-stream-v1', NOTICE = 'private-a2a-task-input-sharing-v1';
  const TERMINAL = new Set(['completed', 'canceled', 'failed', 'rejected', 'unknown', 'dispatched']);
  let dialog, status, history, detail, binding, input, sendConsent, sendButton, refreshButton;
  let workspace = '', session = '', epoch = 0, busy = false, uncertain = false, options = null, selected = null;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, value) => {const item = document.createElement(tag); if (value !== undefined) item.textContent = value; return item;};
  function taskIcon() {
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key, value] of Object.entries({viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true'})) icon.setAttribute(key, value);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'); icon.append(path); icon.style.marginRight = '10px'; return icon;
  }
  const button = (label, action) => {const item = node('button', label); item.type = 'button'; item.className = 'btn'; item.addEventListener('click', action); return item;};
  const stamp = () => ({epoch, workspace, session});
  const valid = mark => Boolean(dialog?.open && mark.epoch === epoch && mark.workspace === workspace && mark.session === session && session === identity() && document.getElementById('workspaceSelect')?.value === workspace);
  function leave() {
    epoch++; workspace = session = ''; options = selected = null; busy = uncertain = false;
    if (dialog) {dialog.close(); dialog.remove();}
    dialog = status = history = detail = binding = input = sendConsent = sendButton = refreshButton = null;
  }
  function onSession() {if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave();}
  function consent(parent, label, id) {
    const wrap = node('label'), item = node('input'); item.type = 'checkbox'; item.id = id;
    wrap.style.display = 'block'; wrap.style.margin = '12px 0'; wrap.append(item, document.createTextNode(' ' + label)); parent.append(wrap); return item;
  }
  function textField(parent, label, tag, id) {
    const wrap = node('label', label + ' '), item = node(tag); item.id = id; item.setAttribute('aria-label', label);
    Object.assign(wrap.style, {display: 'block', margin: '12px 0'}); Object.assign(item.style, {display: 'block', width: '100%', marginTop: '6px'});
    wrap.append(item); parent.append(wrap); return item;
  }
  function update() {
    if (!dialog) return;
    const available = options?.profile === PROFILE && options?.encryption_configured === true && options.bindings?.length > 0;
    binding.disabled = input.disabled = sendConsent.disabled = busy || !available || uncertain;
    sendButton.disabled = busy || !available || uncertain || !binding.value || !input.value.trim() || new TextEncoder().encode(input.value).length > 4000 || !sendConsent.checked;
    refreshButton.disabled = busy;
    for (const item of history.querySelectorAll('button')) item.disabled = busy;
    for (const item of detail.querySelectorAll('input,textarea,button')) item.disabled = busy || uncertain || !selected || TERMINAL.has(selected.state) && !selected.resume_available && !selected.cancel_available || selected.expires * 1000 <= Date.now();
    for (const action of ['poll', 'cancel', 'resume', 'continue']) {
      const check = document.getElementById('remoteA2A' + action + 'Consent'), command = document.getElementById('remoteA2A' + action + 'Once');
      if (command) command.disabled = command.disabled || !check.checked || action === 'continue' && !document.getElementById('remoteA2AContinuation')?.value.trim();
    }
  }
  async function request(mark, path, value) {
    if (!valid(mark)) throw Error('scope_changed');
    const response = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(mark.workspace)}/remote-a2a${path}`,
      value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (response?.ok === false) throw Error('unsupported_task');
    return response;
  }
  function fail(error, mutating) {
    if ([401, 403, 404].includes(error.status)) {leave(); return;}
    uncertain = mutating; options = null;
    selected = null; detail.replaceChildren(); sendConsent.checked = false;
    status.textContent = mutating ? 'The response could not be confirmed. Read retained history before considering another action. No command is retried automatically.' : 'Current task data is unavailable. Read retained history again after checking permission and configuration.';
  }
  function taskSummary(value) {
    return `${value.id} · ${value.state} · revision ${value.revision} · resource ${value.resource_id} · ${value.version_id}`;
  }
  function validTask(value) {
    return [PROFILE, SESSION_PROFILE].includes(value?.profile) && /^rtk_[a-f0-9]{32}$/.test(value.id) && Number.isSafeInteger(value.revision) && value.revision > 0 && Number.isFinite(value.expires) && typeof value.state === 'string';
  }
  function displayTask(value) {
    if (!validTask(value)) throw Error('unsupported_task');
    selected = value; detail.replaceChildren(); detail.append(node('h3', 'Retained task'), node('p', taskSummary(value)));
    detail.append(node('p', 'Reading this record does not poll the remote agent. Commands below use this exact task revision.'));
    if (typeof value.output_preview === 'string' && value.output_preview) {
      const preview = node('pre', value.output_preview); preview.setAttribute('aria-label', 'Retained output preview'); preview.style.whiteSpace = 'pre-wrap'; preview.style.overflowWrap = 'anywhere'; detail.append(preview);
      if (value.output_truncated === true) detail.append(node('p', 'Only the retained text preview is shown. The remote output was truncated.'));
    } else if (value.remote_output_retained) detail.append(node('p', 'Use Read retained task to inspect the stored text preview.'));
    if (TERMINAL.has(value.state) && !value.resume_available && !value.cancel_available) {
      detail.append(node('p', value.state === 'unknown' || value.state === 'dispatched' ? 'The external outcome is uncertain. Automatic polling, cancellation and resubmission are blocked.' : 'This retained task is terminal. No further remote command is available.'));
    } else {
      const actions = TERMINAL.has(value.state) ? [] : ['poll', 'cancel'];
      if (value.resume_available) actions.push('resume');
      if (value.cancel_available && !actions.includes('cancel')) actions.push('cancel');
      if (value.profile === SESSION_PROFILE && value.state === 'input-required') actions.push('continue');
      for (const action of actions) {
        const section = node('section'); section.className = 'card'; section.style.padding = '12px'; section.style.marginTop = '12px';
        if (action === 'continue') {const text = textField(section, 'New input for the same task context', 'textarea', 'remoteA2AContinuation'); text.maxLength = 4000; text.addEventListener('input', () => {const check = document.getElementById('remoteA2AcontinueConsent'); if(check) check.checked = false; update();});}
        const labels = {poll:'I authorize one remote status request for this exact retained task.', cancel:'I authorize one cancellation request for this exact retained task; cancellation is not guaranteed.', resume:'I authorize one read-only stream reconnection to this existing task. No task message will be resent.', continue:'I authorize sharing this new input with the same selected task and session context.'};
        const check = consent(section, labels[action], 'remoteA2A' + action + 'Consent');
        const submit = button({poll:'Poll once',cancel:'Request cancellation once',resume:'Resume existing task stream',continue:'Send next input once'}[action], () => command(action)); submit.id = 'remoteA2A' + action + 'Once';
        check.addEventListener('change', update); section.append(submit); detail.append(section);
      }
    }
    update();
  }
  function displayHistory(tasks) {
    if (!Array.isArray(tasks) || tasks.length > 100 || tasks.some(value => !validTask(value))) throw Error('unsupported_history');
    history.replaceChildren();
    if (!tasks.length) history.append(node('p', 'No retained tasks in this workspace.'));
    for (const task of tasks) {
      const row = node('section'); row.className = 'card'; row.style.padding = '12px'; row.style.margin = '10px 0';
      row.append(node('p', taskSummary(task)), button('Read retained task ' + task.id, () => readTask(task.id))); history.append(row);
    }
  }
  async function refresh() {
    if (busy) return;
    const mark = stamp(); busy = true; selected = null; detail.replaceChildren(); sendConsent.checked = false; update();
    try {
      const config = await request(mark, '/options'); if (!valid(mark)) return;
      if (config.profile !== PROFILE || config.notice !== NOTICE || !Array.isArray(config.bindings) || config.bindings.length > 20) throw Error('unsupported_options');
      const result = await request(mark, '/tasks'); if (!valid(mark)) return;
      options = config; binding.replaceChildren(new Option('Select an approved recorded binding', ''));
      for (const [index, item] of config.bindings.entries()) {
        if (!Number.isSafeInteger(item.resource_id) || item.resource_id < 1 || !/^cv_[a-f0-9]{32}$/.test(item.version_id)) throw Error('unsupported_binding');
        binding.add(new Option(`Resource ${item.resource_id} · ${item.version_id}`, String(index)));
      }
      displayHistory(result.tasks); uncertain = false;
      status.textContent = config.encryption_configured !== true || !config.bindings.length ? 'Remote A2A tasks are unavailable. No approved task binding and encrypted retention configuration are ready.' : 'Retained history loaded. Remote status changes appear only after an explicitly authorized Poll once action.';
    } catch (error) {if (valid(mark)) fail(error, false);}
    finally {if (valid(mark)) {busy = false; update();}}
  }
  async function readTask(id) {
    if (busy) return;
    const mark = stamp(); busy = true; selected = null; detail.replaceChildren(); sendConsent.checked = false; update();
    try {const result = await request(mark, '/tasks/' + encodeURIComponent(id)); if (!valid(mark)) return; uncertain = false; displayTask(result.task); status.textContent = 'Retained task read. No remote request was sent.';}
    catch (error) {if (valid(mark)) fail(error, false);}
    finally {if (valid(mark)) {busy = false; update();}}
  }
  function logicalId() {return 'rat_' + Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');}
  async function send() {
    update(); if (sendButton.disabled) return;
    const mark = stamp(), chosen = options.bindings[Number(binding.value)];
    const body = {logical_id: logicalId(), resource_id: chosen.resource_id, version_id: chosen.version_id, text: input.value, authorized: true, notice: NOTICE};
    busy = true; sendConsent.checked = false; selected = null; detail.replaceChildren(); update();
    try {
      const result = await request(mark, '/tasks', body); if (!valid(mark)) return;
      input.value = ''; displayTask(result.task);
      const retained = await request(mark, '/tasks'); if (!valid(mark)) return; displayHistory(retained.tasks);
      status.textContent = 'One task submission was recorded. No automatic poll or resubmission is scheduled.';
    } catch (error) {if (valid(mark)) fail(error, true);}
    finally {if (valid(mark)) {busy = false; update();}}
  }
  async function command(action) {
    const consent = document.getElementById('remoteA2A' + action + 'Consent');
    if (busy || uncertain || !selected || TERMINAL.has(selected.state) && !(action === 'resume' && selected.resume_available || action === 'cancel' && selected.cancel_available) || !consent?.checked || !valid(stamp())) return;
    const mark = stamp(), task = selected, body = {revision: task.revision, action, authorized: true, notice: NOTICE};
    if (action === 'continue') {delete body.action; body.logical_id = logicalId(); body.text = document.getElementById('remoteA2AContinuation').value;}
    busy = true;
    for (const check of detail.querySelectorAll('input[type=checkbox]')) check.checked = false;
    update();
    try {
      const result = await request(mark, '/tasks/' + encodeURIComponent(task.id) + (action === 'continue' ? '/messages' : ''), body); if (!valid(mark)) return; displayTask(result.task);
      const retained = await request(mark, '/tasks'); if (!valid(mark)) return; displayHistory(retained.tasks);
      status.textContent = {poll:'One remote status request was recorded. Authorize a fresh action to poll again.',cancel:'One cancellation request was recorded. Inspect the retained state; cancellation may not succeed.',resume:'One stream reconnection was recorded for the same task. No task message was resent.',continue:'One new input was recorded for the same task context.'}[action];
    } catch (error) {if (valid(mark)) fail(error, true);}
    finally {if (valid(mark)) {busy = false; update();}}
  }
  async function open(id) {
    leave(); if (!identity() || document.getElementById('workspaceSelect')?.value !== id) return;
    workspace = id; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceRemoteA2ADialog'; dialog.setAttribute('aria-labelledby', 'workspaceRemoteA2ATitle');
    Object.assign(dialog.style, {width: 'min(1060px, calc(100vw - 64px))', maxHeight: '86vh', overflow: 'auto', border: '1px solid var(--border, #cbd5e1)', borderRadius: '18px', padding: '24px', color: 'var(--text, #172235)', background: 'var(--surface, Canvas)'});
    const heading = node('h2', 'Remote A2A tasks'); heading.id = 'workspaceRemoteA2ATitle'; heading.prepend(taskIcon());
    dialog.append(heading, node('p', 'Selected private task profile only. Submission shares your entered task text with the approved agent. Use non-sensitive task text. This view never polls or retries automatically.'));
    status = node('p', 'Reading retained task history.'); status.setAttribute('role', 'status'); dialog.append(status);
    const actions = node('div'); actions.className = 'row'; actions.style.gap = '12px';
    refreshButton = button('Read retained history', refresh); actions.append(refreshButton, button('Close', leave)); dialog.append(actions);
    const form = node('section'); form.className = 'card'; form.style.padding = '16px'; form.append(node('h3', 'Submit one new task'));
    binding = textField(form, 'Approved recorded binding', 'select', 'remoteA2ABinding'); input = textField(form, 'Task text to share', 'textarea', 'remoteA2AText'); input.rows = 4; input.maxLength = 4000;
    sendConsent = consent(form, 'I authorize one submission of this exact task text to the selected approved agent.', 'remoteA2ASendConsent');
    sendButton = button('Send task once', send); sendButton.id = 'remoteA2ASendOnce'; form.append(sendButton); dialog.append(form);
    for (const field of [binding, input]) field.addEventListener('input', () => {sendConsent.checked = false; update();});
    sendConsent.addEventListener('change', update);
    history = node('section'); history.setAttribute('aria-label', 'Retained remote task history'); detail = node('section'); detail.setAttribute('aria-label', 'Selected retained remote task'); dialog.append(history, detail);
    dialog.addEventListener('cancel', event => {event.preventDefault(); leave();}); document.body.append(dialog); dialog.showModal(); await refresh();
  }
  document.getElementById('workspaceSelect')?.addEventListener('change', onSession);
  window.addEventListener('pagehide', leave);
  window.WorkspaceRemoteA2AAdmin = {open, leave, onSession};
})();
