/* Private read evaluation, trust preview and zero-dispatch routing controls. */
(() => {
  'use strict';
  let dialog = null, content = null, status = null, workspace = '', session = '', epoch = 0, busy = false;
  let evaluationOptions = null, evaluationState = null, routingState = null, workerState = null, latestCorpus = null;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
  const line = (parent, text) => parent.append(node('p', text));
  const button = (text, action) => { const value = node('button', text); value.type = 'button'; value.className = 'btn'; value.addEventListener('click', action); return value; };
  const stamp = () => ({workspace, session, epoch});
  const valid = captured => Boolean(dialog?.open && captured.workspace === workspace && captured.session === session && captured.epoch === epoch && session === identity() && document.getElementById('workspaceSelect')?.value === workspace);
  const tell = text => { if (status) status.textContent = text; };
  const time = value => typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toISOString() : 'Unavailable';
  const randomId = prefix => `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('')}`;
  const ids = input => { const values = input.value.split(',').map(item => Number(item.trim())); if (!values.length || values.length > 6 || values.some(value => !Number.isSafeInteger(value) || value < 1 || value >= 2147483648) || new Set(values).size !== values.length) throw Error('invalid_reference'); return values; };
  function field(parent, text, initial, type = 'text') { const label = node('label', `${text} `), input = node('input'); input.type = type; input.value = initial; label.append(input); parent.append(label); return input; }
  function consent(parent, text) { const label = node('label'), input = node('input'); input.type = 'checkbox'; input.checked = false; label.append(input, ' ', node('span', text)); parent.append(label); return input; }
  function section(title) { const value = node('section'); value.className = 'card'; Object.assign(value.style, {padding: '16px', margin: '14px 0', borderRadius: '14px'}); value.append(node('h3', title)); content.append(value); return value; }
  function leave() { epoch++; busy = false; workspace = session = ''; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = status = evaluationOptions = evaluationState = routingState = workerState = latestCorpus = null; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, value) {
    const result = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/reliability${path}`, value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (result?.ok !== true || typeof result.result !== 'object') throw Error('unconfirmed_result');
    return result.result;
  }
  async function run(action) {
    if (busy) return;
    const captured = stamp(); busy = true;
    try { await action(captured); }
    catch (error) { if (valid(captured)) tell([401, 403, 404].includes(error?.status) ? 'Current session or workspace access changed. Close and reopen this view.' : 'The request could not be confirmed. Read current state before another command.'); }
    finally { if (valid(captured)) busy = false; }
  }
  async function refresh(captured = stamp()) {
    const values = await Promise.all([request('/evaluation/options'), request('/evaluation/status'), request('/routing/status'),
      request('/evaluation/worker/status').catch(error => { if (error?.status === 404) return null; throw error; })]);
    if (!valid(captured)) return;
    [evaluationOptions, evaluationState, routingState, workerState] = values;
    render(); tell('Current private controls loaded. No business calls were made.');
  }
  function render() {
    content.replaceChildren();
    const summary = section('Evaluation coverage');
    const coverage = evaluationState.coverage;
    line(summary, `Expected cases ${coverage.expected_cases}; scheduled cases ${coverage.scheduled_cases}; coverage debt ${coverage.debt_cases}.`);
    line(summary, `Latest actual observation: ${time(coverage.latest_actual_observed_at)}. Oldest due: ${time(coverage.oldest_due_at)}.`);
    line(summary, `Evaluation switch: ${evaluationState.control.enabled ? 'enabled' : 'paused'}. Trusted read evaluator: ${evaluationOptions.evaluator_configured ? 'configured' : 'unavailable'}.`);
    if (evaluationState.control.restore_quarantined || evaluationState.plan?.restore_quarantined) line(summary, 'Restored evaluation authority is quarantined. Review and explicitly approve a new control and plan. Old jobs remain blocked.');
    line(summary, 'Coverage debt never refreshes a verification time. Scheduler outcomes do not establish independent quality.');
    if (evaluationOptions.can_write) {
      const authorization = consent(summary, 'Authorize this evaluation switch change for the current workspace.');
      summary.append(button(evaluationState.control.enabled ? 'Pause evaluations' : 'Enable evaluation reservations', () => run(async captured => {
        if (!authorization.checked) { tell('Select the evaluation switch authorization.'); return; }
        authorization.checked = false;
        await request('/evaluation/control', {revision: evaluationState.control.revision, enabled: !evaluationState.control.enabled, authorized: true, notice: evaluationOptions.notice});
        if (valid(captured)) await refresh(captured);
      })));
    }
    const worker = section('Bounded evaluation worker');
    line(worker, workerState?.configured ? `Configured worker: ${workerState.running ? 'running' : 'stopped'}. Workspace activation: ${workerState.active ? 'active' : 'inactive'}.` : 'Automatic evaluation is unavailable. Trusted server configuration is required; selecting a checkbox does not configure a worker.');
    line(worker, 'Activation applies only to the current approved corpus, plan revision and owner session. Contract checks do not establish independent task quality. Shutdown, withdrawal or changed authority blocks new calls; an uncertain call is never replayed.');
    if (workerState?.active) line(worker, `Active plan revision: ${workerState.plan_revision}.`);
    if (evaluationOptions.can_write) {
      const approved = consent(worker, 'Activate the current approved evaluation plan with the configured bounded worker. This authorizes only the approved read evaluation corpus.');
      const revision = evaluationState.plan?.revision;
      const activate = button('Activate evaluation worker', () => run(async captured => {
        if (!approved.checked) { tell('Select the exact worker activation authorization.'); return; }
        approved.checked = false;
        await request('/evaluation/worker/activate', {revision, authorized: true, notice: evaluationOptions.notice});
        if (valid(captured)) await refresh(captured);
      }));
      const ready = workerState?.configured === true && workerState.running === true && evaluationOptions.evaluator_configured === true
        && evaluationState.control.enabled === true && Number.isSafeInteger(revision) && revision > 0 && workerState.active !== true;
      approved.disabled = !ready; activate.disabled = !ready; worker.append(activate);
      const pauseConsent = consent(worker, 'Deactivate this workspace worker without retrying any dispatched evaluation.');
      const pause = button('Deactivate evaluation worker', () => run(async captured => {
        if (!pauseConsent.checked) { tell('Select the worker deactivation authorization.'); return; }
        pauseConsent.checked = false;
        await request('/evaluation/worker/deactivate', {revision: evaluationState.plan?.revision || 0, authorized: true, notice: evaluationOptions.notice});
        if (valid(captured)) await refresh(captured);
      }));
      pauseConsent.disabled = workerState?.active !== true; pause.disabled = workerState?.active !== true; worker.append(pause);
    }
    if (evaluationOptions.can_write) {
      const corpus = section('Approved evaluation corpus');
      const contract = node('select'); contract.setAttribute('aria-label', 'Evaluation contract'); contract.append(new Option('Documentation search', 'docs.search.v1'), new Option('News search', 'news.search.v1')); corpus.append(contract);
      const query = field(corpus, 'Synthetic evaluation question', 'Public documentation search'); query.maxLength = 500;
      const authorized = consent(corpus, 'I authorize this synthetic or licensed corpus, without personal data, for this exact read evaluation purpose.');
      corpus.append(button('Approve corpus version', () => run(async captured => {
        if (!authorized.checked) { tell('Select the corpus authorization.'); return; }
        const input = {query: query.value, language: 'en', limit: 2}; if (contract.value === 'news.search.v1') input.from_utc = '2020-01-01T00:00:00Z';
        const result = await request('/evaluation/corpora', {corpus_id: randomId('rcp'), version: 'owner-corpus-v1', contract_id: contract.value, cases: [{case_id: 'holdout-1', kind: 'repeatability', split: 'holdout', input}], training_hashes: [], authorized: true, notice: evaluationOptions.notice, data_attestation: 'synthetic_or_licensed_no_personal_data'});
        if (!valid(captured)) return; latestCorpus = result; authorized.checked = false; tell('Immutable corpus approved. Configure its bounded plan separately.');
      })));
      const plan = section('Bounded evaluation plan');
      const resources = field(plan, 'Evaluation resource references', '1');
      const approved = consent(plan, 'Authorize this exact corpus and current contract pins for at most one reservation per host every ten minutes, with jitter and a one-hour expiry.');
      plan.append(button('Save evaluation plan', () => run(async captured => {
        if (!approved.checked || !latestCorpus) { tell('Approve a corpus and select the exact plan authorization.'); return; }
        const result = await request('/evaluation/plans', {revision: evaluationState.plan?.revision || 0, corpus_id: latestCorpus.id, resource_ids: ids(resources), interval_seconds: 600, jitter_seconds: 30, per_host_budget: 1, expires: Date.now()/1000+3600, authorized: true, notice: evaluationOptions.notice});
        if (valid(captured)) { approved.checked = false; await refresh(captured); tell(`Evaluation plan revision ${result.revision} saved. No evaluation was dispatched.`); }
      })));
      if (evaluationState.plan) {
        const reserve = consent(plan, 'Reserve eligible cases for the current approved plan. Reservations make no provider calls.');
        plan.append(button('Reserve due evaluations', () => run(async captured => {
          if (!reserve.checked) { tell('Select the reservation authorization.'); return; }
          reserve.checked = false;
          await request('/evaluation/reserve', {revision: evaluationState.plan.revision, authorized: true, notice: evaluationOptions.notice});
          if (valid(captured)) await refresh(captured);
        })));
      }
    }
    const jobs = section('Evaluation jobs');
    if (!evaluationState.jobs.length) line(jobs, 'No scheduled jobs.');
    for (const job of evaluationState.jobs.slice(0, 30)) {
      const row = node('div'); line(row, `Resource ${job.resource_id} · ${job.case_id} · ${job.state} · observed ${time(job.observed_at)} · expires ${time(job.expires)}.`);
      if (evaluationOptions.can_write && ['reserved', 'prepared', 'dispatched'].includes(job.state)) {
        const cancel = consent(row, `Cancel evaluation ${job.case_id} for resource ${job.resource_id}. A dispatched job remains uncertain.`);
        row.append(button('Cancel evaluation', () => run(async captured => {
          if (!cancel.checked) { tell('Select the exact job cancellation authorization.'); return; }
          cancel.checked = false;
          await request(`/evaluation/jobs/${encodeURIComponent(job.id)}/cancel`, {authorized: true, notice: evaluationOptions.notice});
          if (valid(captured)) await refresh(captured);
        })));
      }
      jobs.append(row);
    }
    const trust = section('Private trust preview');
    const resource = field(trust, 'Trust resource reference', '1', 'number'), output = node('div'); output.setAttribute('role', 'region'); output.setAttribute('aria-label', 'Trust evidence result');
    trust.append(button('Read trust preview', () => run(async captured => {
      const rid = Number(resource.value); if (!Number.isSafeInteger(rid) || rid < 1 || rid >= 2147483648) throw Error('invalid_reference');
      const result = await request(`/trust/${rid}`); if (!valid(captured)) return;
      output.replaceChildren(); line(output, `${result.state === 'last_verified' ? 'Last verified' : result.state === 'verification_expired' ? 'Verification expired' : 'Evidence pending'} · ${result.agent_version}`);
      line(output, `Last verified: ${time(result.last_verified_at)}. Expires: ${time(result.expires_at)}. Public activation is disabled.`);
      line(output, `Contract scope: ${result.contract_id || 'Unqualified'}; revision ${result.contract_revision ?? 'Unavailable'}.`);
      line(output, result.notice); tell('Current trust evidence revalidated. No provider call was made.');
    })), output);
    const routing = section('Offline routing and decision shadow');
    line(routing, 'This profile only recommends a candidate. Business calls: 0. Any future admission profile is limited to one business call and zero replacements. Existing fallback cannot be combined with it.');
    if (routingState.policy) line(routing, `Policy ${routingState.policy.revision} · ${routingState.policy.mode} · ${routingState.policy.enabled ? 'enabled' : 'paused'} · expires ${time(routingState.policy.expires)}.`);
    if (routingState.policy?.restore_quarantined) line(routing, 'Restored routing authority is quarantined. A new explicit owner policy is required.');
    if (routingState.can_write) {
      const workflow = field(routing, 'Workflow reference', String(routingState.policy?.workflow_id || 1), 'number');
      const candidates = field(routing, 'Candidate resource references', routingState.policy?.resource_ids.join(', ') || '1');
      const mode = node('select'); mode.setAttribute('aria-label', 'Routing mode'); mode.append(new Option('Offline replay', 'offline'), new Option('Decision shadow', 'decision_shadow')); routing.append(mode);
      mode.value = routingState.policy?.mode || 'offline';
      const contract = node('select'); contract.setAttribute('aria-label', 'Routing contract'); contract.append(new Option('Documentation search', 'docs.search.v1'), new Option('News search', 'news.search.v1')); contract.value = routingState.policy?.contract_id || 'docs.search.v1'; routing.append(contract);
      const authorized = consent(routing, 'Authorize this exact candidate list and input-sharing scope for private recommendations only. This grants no execution permission.');
      routing.append(button('Save routing preview policy', () => run(async captured => {
        if (!authorized.checked) { tell('Select the routing and input-sharing authorization.'); return; }
        const references = ids(candidates);
        await request('/routing/configure', {revision: routingState.policy?.revision || 0, workflow_id: Number(workflow.value), contract_id: contract.value, resource_ids: references, share_resource_ids: references, mode: mode.value, enabled: true, expires: Date.now()/1000+3600, authorized: true, notice: routingState.notice});
        if (valid(captured)) await refresh(captured);
      })));
      if (routingState.policy) {
        const approve = consent(routing, 'Record one recommendation with current evidence and authority. No provider will be invoked.');
        routing.append(button('Record routing decision', () => run(async captured => {
          if (!approve.checked) { tell('Select the decision authorization.'); return; }
          approve.checked = false;
          await request('/routing/decide', {revision: routingState.policy.revision, logical_id: randomId('rld'), authorized: true, notice: routingState.notice});
          if (valid(captured)) await refresh(captured);
        })));
        const replay = node('div'); replay.setAttribute('role', 'region'); replay.setAttribute('aria-label', 'Offline replay comparison');
        routing.append(button('Replay recorded routing decisions', () => run(async captured => {
          const report = await request('/routing/replay', {revision: routingState.policy.revision, authorized: true, notice: routingState.notice});
          if (!valid(captured)) return;
          replay.replaceChildren();
          line(replay, `Replayed ${report.replayed_decisions} decisions; deterministic matches ${report.deterministic_matches}.`);
          line(replay, `Baseline observations ${report.baseline_history.logical_observations}; selected observations ${report.selected_history.logical_observations}; extra attempts ${report.extra_attempts}.`);
          line(replay, 'These are separate retained histories. A paired corpus benchmark and an improvement in task outcomes have not been established.');
          tell('Historical rule replay completed. No provider was invoked.');
        })), replay);
        const pause = consent(routing, 'Pause this private routing preview policy immediately.');
        routing.append(button('Pause routing preview', () => run(async captured => {
          if (!pause.checked) { tell('Select the pause authorization.'); return; }
          const policy = routingState.policy;
          await request('/routing/configure', {revision: policy.revision, workflow_id: policy.workflow_id, contract_id: policy.contract_id, resource_ids: policy.resource_ids, share_resource_ids: policy.resource_ids, mode: policy.mode, enabled: false, expires: Date.now()/1000+3600, authorized: true, notice: routingState.notice});
          if (valid(captured)) await refresh(captured);
        })));
      }
    }
    for (const decision of routingState.decisions.slice(0, 10)) line(routing, `${decision.mode} · ${decision.reason} · selected resource ${decision.selected_resource_id ?? 'none'} · eligible ${decision.eligible.length} · excluded ${decision.excluded.length} · business calls ${decision.business_calls}.`);
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceReliabilityControlsDialog';
    Object.assign(dialog.style, {width: 'min(1000px,94vw)', maxWidth: '94vw', maxHeight: '86vh', boxSizing: 'border-box', borderRadius: '18px', padding: '22px', overflow: 'auto', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const header = node('div'); Object.assign(header.style, {display: 'flex', alignItems: 'center', justifyContent: 'space-between'});
    const title = node('h2', 'Reliability controls'); title.id = 'workspaceReliabilityControlsTitle'; dialog.setAttribute('aria-labelledby', title.id);
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key, value] of Object.entries({viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'aria-hidden': 'true'})) icon.setAttribute(key, value);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11m-4-11 3 3 5-5'); icon.append(path); title.prepend(icon, document.createTextNode(' '));
    header.append(title, button('Close reliability controls', leave), button('Read current reliability controls', () => run(refresh)));
    status = node('p', 'Revalidating scoped reliability controls.'); status.setAttribute('role', 'status'); content = node('div'); content.style.overflowWrap = 'anywhere';
    dialog.append(header, status, content); document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal();
    await run(refresh);
  }
  window.WorkspaceReliabilityControlsAdmin = {open, leave, onSession};
})();
