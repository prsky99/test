/* Reviewed private plans and a single-provider pilot under current staff authority. */
(() => {
  'use strict';
  let dialog, content, status, workspace = '', session = '', generation = 0, busy = false, uncertain = false;
  const element = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const button = (text, action) => { const value = element('button', text); value.type = 'button'; value.className = 'btn'; value.addEventListener('click', action); return value; };
  const field = (parent, label, value = '') => { const row = element('label', label+' '), input = element('input'); input.value = value; row.style.display = 'block'; row.style.margin = '10px 0'; row.append(input); parent.append(row); return input; };
  const consent = (parent, label) => { const input = field(parent, label); input.type = 'checkbox'; input.checked = false; return input; };
  const tell = value => { if (status) status.textContent = value; };
  const stamp = () => ({generation, workspace, session});
  const valid = state => Boolean(dialog?.open && state.generation === generation && state.workspace === workspace && state.session === identity() && document.getElementById('workspaceSelect')?.value === workspace);
  function leave() { generation++; workspace = session = ''; busy = uncertain = false; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = status = null; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, body) {
    const answer = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}${path}`, body === undefined ? {silent: true} : {method: 'POST', json: body, silent: true});
    if (answer?.ok !== true || !answer.result) throw Error('private_result_unconfirmed');
    return answer.result;
  }
  async function command(action, done) {
    if (busy || uncertain) return;
    const captured = stamp(); busy = true;
    try { const result = await action(); if (valid(captured)) done(result); }
    catch { if (valid(captured)) { uncertain = true; tell('The command could not be confirmed. Read current state before another action; no request is retried automatically.'); } }
    finally { if (valid(captured)) busy = false; }
  }
  function reviewedPlans() {
    const section = element('section'); section.append(element('h3', 'Reviewed plan proposals'));
    section.append(element('p', 'Describe two to six supported steps separated by then. Ambiguous or unsupported goals request details. Saving creates a new private draft; existing runs and releases remain separate.'));
    const purpose = field(section, 'Task', 'Documentation about public research then documentation about current references'); purpose.id = 'researchIntent';
    const name = field(section, 'New workflow name', 'Reviewed multi-step workflow');
    const definition = element('textarea'); definition.id = 'researchDefinition'; definition.rows = 7; definition.style.width = '100%'; definition.setAttribute('aria-label', 'Optional explicit typed graph JSON'); section.append(definition);
    const base = field(section, 'Existing flow to review as a new draft (optional)'), revision = field(section, 'Existing flow revision (optional)'); revision.type = 'number';
    const preview = element('div'); section.append(preview);
    let review = null, inputRevision = 0, modelOptions = null;
    const approved = consent(section, 'I reviewed every exact input and destination and authorize saving a new private draft.'); approved.id = 'researchPlanConsent';
    const modelConsent = consent(section, 'I authorize one advisory model proposal using only this public objective and approved candidate references. I confirm the objective contains no personal, private or confidential information. Existing graphs and outputs are not shared.'); modelConsent.id = 'researchModelConsent'; modelConsent.disabled = true;
    const save = button('Save reviewed new draft', () => {
      if (!approved.checked || !review || review.expires*1000 <= Date.now()) return;
      const current = review; approved.checked = false; review = null; save.disabled = true;
      command(() => request('/app-factory/commits', {review_id: current.review_id, authorized: true, notice: current.notice}), value => tell(`Saved new draft ${value.id}. Test and release it separately; no agent was called by saving.`));
    }); save.id = 'researchSavePlan'; save.disabled = true;
    const reset = () => { inputRevision++; review = null; approved.checked = modelConsent.checked = false; save.disabled = true; modelProposal.disabled = true; preview.replaceChildren(); };
    for (const input of [purpose, name, definition, base, revision]) input.addEventListener('input', reset);
    approved.addEventListener('change', () => { save.disabled = !approved.checked || !review || review.expires*1000 <= Date.now() || uncertain; });
    const showReview = (result, requestedRevision) => {
        if (requestedRevision !== inputRevision) return;
        if (result.state === 'needs_details') { preview.append(element('p', result.questions.join(' '))); tell('Provide the missing intent details before preparing another plan.'); return; }
        if (!Number.isFinite(result.expires) || result.expires*1000 <= Date.now()) { tell('The review expired. Prepare it again.'); return; }
        review = result; preview.append(element('p', 'Exact new draft proposal. Saving grants no execution or release authority.'));
        if (result.base_flow) {
          preview.append(element('p', `Reviewed base flow ${result.base_flow.id}; revision ${result.base_flow.revision}; version ${result.base_flow.version_id}.`));
          const changes = element('ul'); changes.setAttribute('aria-label', 'Reviewed plan changes');
          if (!result.changes.length) changes.append(element('li', 'No graph changes from the reviewed base revision.'));
          for (const change of result.changes) changes.append(element('li', `${change.node_id}: ${change.change}.`));
          preview.append(changes);
        } else preview.append(element('p', 'New plan without a base flow. No existing flow is changed.'));
        for (const destination of result.destinations) preview.append(element('p', `${destination.node_id}: agent ${destination.resource_id}, ${destination.contract_id}, tool ${destination.tool}`));
        const graph = element('pre', JSON.stringify(result.definition, null, 2)); graph.style.whiteSpace = 'pre-wrap'; preview.append(graph); tell('Review the exact graph, inputs and destinations.');
    };
    const prepare = button('Prepare reviewed plan', () => {
      if (busy || uncertain) return; reset(); const requestedRevision = inputRevision;
      command(() => {
        if (definition.value.trim()) return request('/app-factory/plan-reviews', {name: name.value, definition: JSON.parse(definition.value), base_flow_id: base.value || null, base_revision: base.value ? Number(revision.value) : null});
        if (base.value || revision.value) throw Error('explicit_definition_required');
        return request('/app-factory/intent-reviews', {purpose: purpose.value, name: name.value, resource_ids: null, from_utc: null, criteria: []});
      }, result => showReview(result, requestedRevision));
    }); prepare.id = 'researchPreparePlan';
    const modelProposal = button('Propose from the public objective', () => {
      if (busy || uncertain || !modelConsent.checked || modelOptions?.model_proposal_configured !== true) return;
      if (definition.value.trim() || base.value || revision.value) { modelConsent.checked = false; modelProposal.disabled = true; tell('Clear the private graph and base references before sharing only a public objective.'); return; }
      reset(); const requestedRevision = inputRevision;
      command(() => request('/app-factory/model-proposals', {objective: purpose.value, name: name.value,
        authorized: true, notice: modelOptions.model_proposal_notice,
        data_attestation: 'public_objective_without_personal_or_private_data'}), result => showReview(result, requestedRevision));
    }); modelProposal.id = 'researchModelProposal'; modelProposal.disabled = true;
    modelConsent.addEventListener('change', () => { modelProposal.disabled = !modelConsent.checked || modelOptions?.model_proposal_configured !== true || uncertain; });
    const readModel = button('Read optional model proposal availability', () => {
      if (busy || uncertain) return; modelOptions = null; modelConsent.checked = false; modelConsent.disabled = true; modelProposal.disabled = true;
      command(() => request('/app-factory/options'), result => {
        modelOptions = result; modelConsent.disabled = result.can_edit !== true || result.model_proposal_configured !== true;
        tell(modelConsent.disabled ? 'Optional model proposals are unavailable. Explicit typed reviews and bounded intent remain available.' : 'Optional advisory proposals are available. Share only a public objective with separate consent, then review every exact input and destination before saving.');
      });
    }); readModel.id = 'researchReadModel';
    section.append(prepare, save, readModel, modelProposal); content.append(section);
  }
  function admissionView(value) {
    const section = element('section'); section.append(element('h3', 'Single-provider pilot'));
    section.append(element('p', value.configured ? 'This explicitly configured pilot permits one selected call and zero replacement calls. Every dispatch rechecks current policy and quality evidence.' : 'Single-provider execution is disabled in server configuration. Private policy review does not enable it.'));
    section.append(element('p', 'Early-stop intervention awaits paired evidence; remote cancellation and long-task execution are not enabled by this pilot.'));
    const history = element('div'); history.setAttribute('aria-label', 'Retained admissions'); section.append(history);
    for (const item of value.admissions) history.append(element('p', `${item.id}: ${item.state}; agent ${item.resource_id}. Unknown outcomes require reconciliation, never automatic replay.`));
    if (value.can_write) {
      const shadow = field(section, 'Current decision-shadow policy revision', String(value.policy?.shadow_revision || 1)); shadow.type = 'number';
      const enable = consent(section, 'Enable this private pilot policy (server configuration is independently required).');
      const approve = consent(section, 'I approve this one-call, no-replacement policy for up to ten percent and ten admissions over the next five minutes.');
      section.append(button('Apply pilot policy', () => { if (!approve.checked) return; approve.checked = false; command(() => request('/reliability/admission/configure', {revision: value.policy?.revision || 0, shadow_revision: Number(shadow.value), enabled: enable.checked, percent: 10, max_runs: 10, expires: Math.floor(Date.now()/1000)+300, authorized: true, notice: value.notice}), () => tell('Policy recorded. Read current state before preparing a task.')); }));
      for (const input of [shadow, enable]) input.addEventListener('input', () => { approve.checked = false; });
      if (value.configured && value.policy?.enabled) {
        const query = field(section, 'Contract input JSON', '{"query":"Public documentation","language":"en","limit":2}'); query.id = 'pilotInput';
        const prepareConsent = consent(section, 'Prepare one explicitly reviewed task within the current input-sharing policy.');
        let admission = null, inputRevision = 0; const preview = element('pre'); preview.id = 'pilotExactPreview'; preview.style.whiteSpace = 'pre-wrap'; section.append(preview);
        const runConsent = consent(section, 'I approve sending this exact reviewed input to the selected agent once.'); runConsent.id = 'pilotRunConsent';
        const current = () => Boolean(admission && admission.state === 'prepared' && Number.isFinite(admission.expires) && admission.expires*1000 > Date.now());
        const invalidate = () => { inputRevision++; prepareConsent.checked = runConsent.checked = false; admission = null; run.disabled = true; preview.textContent = ''; };
        const showPreview = (result, revision) => {
          if (revision !== inputRevision) return;
          const item = result.admission;
          if (result.current !== true || result.requires_run_confirmation !== true || item?.state !== 'prepared' || !Number.isFinite(item.expires) || item.expires*1000 <= Date.now() || result.notice !== value.notice || !result.preview) {
            invalidate(); tell(`Admission ${item?.state || 'unconfirmed'}. Read current state; no provider was called.`); return;
          }
          admission = item; runConsent.checked = false; run.disabled = true;
          preview.textContent = JSON.stringify({admission_id: item.id, expires: item.expires, preview: result.preview}, null, 2);
          tell('Review the selected agent and exact input before authorizing execution.');
        };
        const run = button('Run selected agent once', () => {
          if (!runConsent.checked || !current()) { invalidate(); return; }
          const id = admission.id; invalidate();
          for (const retained of history.querySelectorAll('button[data-admission-id]')) if (retained.dataset.admissionId === id) retained.remove();
          command(() => request(`/reliability/admission/${encodeURIComponent(id)}/execute`, {authorized: true, notice: value.notice}), result => tell(`Execution ${result.run.status}. Replacement calls: ${result.replacement_calls}.`));
        }); run.id = 'pilotRunOnce'; run.disabled = true;
        runConsent.addEventListener('change', () => { run.disabled = !runConsent.checked || !current() || uncertain; });
        query.addEventListener('input', invalidate);
        for (const input of [shadow, enable]) input.addEventListener('input', invalidate);
        for (const item of value.admissions) {
          if (item.state !== 'prepared' || !Number.isFinite(item.expires) || item.expires*1000 <= Date.now()) continue;
          const retained = button(`Review prepared admission ${item.id}`, () => {
            if (busy || uncertain) return; invalidate(); const revision = inputRevision;
            command(() => request(`/reliability/admission/${encodeURIComponent(item.id)}/review`), result => showPreview(result, revision));
          }); retained.dataset.admissionId = item.id; history.append(retained);
        }
        section.append(button('Prepare one task', () => {
          if (!prepareConsent.checked || busy || uncertain) return;
          invalidate(); const revision = inputRevision;
          command(() => { const bytes = crypto.getRandomValues(new Uint8Array(16)); return request('/reliability/admission/prepare', {revision: value.policy.revision, logical_id: 'rld_'+Array.from(bytes, v => v.toString(16).padStart(2,'0')).join(''), input: JSON.parse(query.value), name: 'Explicit single-provider pilot task', authorized: true, notice: value.notice}); }, result => {
            if (result.state !== 'prepared') { tell(`Admission ${result.state}. No provider was called.`); return; }
            showPreview({admission: result, preview: result.preview, notice: result.notice, current: true, requires_run_confirmation: result.requires_run_confirmation}, revision);
          });
        }), run);
      }
    }
    content.append(section);
  }
  function evidenceControls(canWrite) {
    const section = element('section'); section.append(element('h3', 'Operating evidence and circuit controls'));
    section.append(element('p', 'These private controls require explicit reads and separate authorization. No provider call, automatic failure ingestion, probe dispatch or public activation occurs here.'));
    const rid = field(section, 'Evidence and circuit resource reference'); rid.id = 'researchEvidenceResource'; rid.inputMode = 'numeric';
    const resource = () => { const value = Number(rid.value); if (!Number.isSafeInteger(value) || value < 1 || value >= 2147483648) throw Error('explicit_resource_required'); return value; };
    let operating = null, circuit = null, operatingRid = null, circuitRid = null, revision = 0;
    const operatingResult = element('p', 'Operating evidence has not been read.'); operatingResult.id = 'researchOperatingStatus'; section.append(operatingResult);
    const operatingConsent = consent(section, 'I authorize this exact operating qualification or withdrawal after reviewing the current independent evidence status.'); operatingConsent.id = 'researchOperatingConsent';
    const operatingReady = () => Boolean(canWrite && operating?.configured === true && operating.notice === 'independent-operating-read-qualification-v1' && operating.resource_id === operatingRid && operatingRid === Number(rid.value) && Number.isSafeInteger(operating.revision) && !uncertain);
    const qualify = button('Qualify current operating evidence', () => operatingAction('qualify'));
    const withdraw = button('Withdraw operating qualification', () => operatingAction('withdraw'));
    const circuitResult = element('p', 'Circuit state has not been read.'); circuitResult.id = 'researchCircuitStatus';
    const policyLabel = element('label', 'Explicit circuit policy JSON '), policy = element('textarea'); policy.rows = 6; policy.maxLength = 12000; policy.style.width = '100%'; policy.id = 'researchCircuitPolicy'; policy.setAttribute('aria-label', 'Explicit circuit policy JSON'); policy.placeholder = 'Enter the separately reviewed exact policy, including resource_id and current revision. No thresholds are assumed.'; policyLabel.append(policy);
    const source = field(section, 'Retained circuit observation source reference'), job = field(section, 'Separately approved probe job reference');
    const circuitConsent = consent(section, 'I authorize only the selected circuit command with this exact resource, current revision and reviewed input. No probe dispatch is authorized.'); circuitConsent.id = 'researchCircuitConsent';
    const circuitReady = () => Boolean(canWrite && circuit?.server_enabled === true && (!circuit.circuit || circuit.circuit.resource_id === circuitRid) && !circuit.restore_quarantined && circuitRid === Number(rid.value) && !uncertain);
    const configure = button('Save explicit circuit policy', () => circuitAction('configure'));
    const ingest = button('Ingest one retained observation', () => circuitAction('ingest'));
    const bind = button('Bind separately approved probe', () => circuitAction('bind-probe'));
    const refreshProbe = button('Read completed bound probe', () => circuitAction('refresh-probe'));
    const update = () => {
      operatingConsent.disabled = !operatingReady(); qualify.disabled = !operatingReady() || !operatingConsent.checked; withdraw.disabled = !operatingReady() || operating.revision < 1 || !operatingConsent.checked;
      circuitConsent.disabled = !circuitReady(); configure.disabled = !circuitReady() || !circuitConsent.checked;
      for (const action of [ingest, bind, refreshProbe]) action.disabled = !circuitReady() || !circuit.circuit?.enabled || !circuitConsent.checked;
    };
    const clearConsent = () => { operatingConsent.checked = circuitConsent.checked = false; update(); };
    const clearReads = () => { revision++; operating = circuit = null; operatingRid = circuitRid = null; operatingResult.textContent = 'Operating evidence has not been read.'; circuitResult.textContent = 'Circuit state has not been read.'; clearConsent(); };
    rid.addEventListener('input', clearReads);
    for (const input of [policy, source, job]) input.addEventListener('input', clearConsent);
    for (const input of [operatingConsent, circuitConsent]) input.addEventListener('change', update);
    function operatingAction(action) {
      if (!operatingReady() || !operatingConsent.checked || busy) return;
      const selected = operatingRid, currentRevision = operating.revision; clearReads();
      command(() => request(`/reliability/operating/${action}`, {resource_id: selected, revision: currentRevision, authorized: true, notice: 'independent-operating-read-qualification-v1'}), () => tell('Operating evidence command recorded. Read the exact current status before another command.'));
    }
    function circuitAction(action) {
      if (!circuitReady() || !circuitConsent.checked || busy) return;
      const selected = circuitRid, currentRevision = circuit.circuit?.revision || 0;
      let body;
      try {
        if (action === 'configure') {
          body = JSON.parse(policy.value);
          if (!body || Array.isArray(body) || typeof body !== 'object' || body.resource_id !== selected || body.revision !== currentRevision) throw Error('exact_policy_required');
        } else body = {revision: currentRevision, ...(action === 'ingest' ? {source_ref: source.value} : action === 'bind-probe' ? {job_id: job.value} : {})};
      } catch { circuitConsent.checked = false; update(); tell('Provide the exact explicitly reviewed circuit JSON with the selected resource and current revision.'); return; }
      clearReads();
      command(() => request(`/reliability/circuits/${encodeURIComponent(selected)}/${action}`, {...body, authorized: true, notice: 'separate-approved-evaluation-probe-v1'}), () => tell('Circuit command recorded. Read current state again. No provider or probe was dispatched.'));
    }
    section.append(button('Read operating evidence status', () => {
      if (busy || uncertain) return; operatingConsent.checked = false; operating = null; update(); const readRevision = revision;
      command(() => { const selected = resource(); return request(`/reliability/operating/${selected}`).then(result => ({selected, result})); }, value => {
        if (readRevision !== revision) return; operating = value.result; operatingRid = value.selected;
        operatingResult.textContent = operating.configured ? `Agent ${operating.resource_id}; revision ${operating.revision}; qualified operating evidence ${operating.qualified_operating_evidence === true ? 'confirmed' : 'not established'}. Qualification still requires current independent evidence.` : 'Operating qualification is disabled: no independent operating qualifier is configured. No operational quality is inferred.'; update();
      });
    }), qualify, withdraw, circuitResult, policyLabel, button('Read circuit state', () => {
      if (busy || uncertain) return; circuitConsent.checked = false; circuit = null; update(); const readRevision = revision;
      command(() => { const selected = resource(); return request(`/reliability/circuits/${selected}`).then(result => ({selected, result})); }, value => {
        if (readRevision !== revision) return; circuit = value.result; circuitRid = value.selected;
        circuitResult.textContent = circuit.server_enabled !== true ? 'Circuit commands are disabled in server configuration.' : circuit.restore_quarantined ? 'Circuit is restore quarantined. A new explicit approval and separate probe are required.' : circuit.circuit ? `Agent ${circuit.circuit.resource_id}; revision ${circuit.circuit.revision}; state ${circuit.circuit.state}; reason ${circuit.circuit.reason}; bound probe ${circuit.circuit.probe_job_id || 'none'}.` : `Agent ${circuitRid}; revision 0; no circuit policy. Enter the explicit reviewed thresholds before configuring.`; update();
      });
    }), configure, ingest, bind, refreshProbe);
    clearConsent(); content.append(section);
  }
  async function readCurrent() {
    if (busy) return; const captured = stamp(); busy = true; uncertain = false;
    try { const value = await request('/reliability/admission/status'); if (!valid(captured)) return; content.replaceChildren(); admissionView(value); reviewedPlans(); evidenceControls(value.can_write === true); tell('Current scoped state loaded. No agent was called.'); }
    catch { if (valid(captured)) { uncertain = true; tell('Current scoped state is unavailable.'); } }
    finally { if (valid(captured)) busy = false; }
  }
  async function open(ws) {
    leave(); if (!/^ws_[a-f0-9]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = element('dialog'); dialog.id = 'workspaceResearchControlsDialog';
    Object.assign(dialog.style, {width: 'min(1000px,94vw)', maxHeight: '86vh', boxSizing: 'border-box', borderRadius: '18px', padding: '22px', overflow: 'auto', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const heading = element('h2', 'Reviewed plans and single-provider pilot'); heading.id = 'workspaceResearchControlsTitle'; dialog.setAttribute('aria-labelledby', heading.id);
    status = element('p'); status.setAttribute('role', 'status'); content = element('div'); content.style.overflowWrap = 'anywhere';
    dialog.append(heading, button('Close research controls', leave), button('Read current state', readCurrent), status, content); document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal(); await readCurrent();
  }
  window.WorkspaceResearchControlsAdmin = {open, leave, onSession};
})();
