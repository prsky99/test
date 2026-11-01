/* Private versioned evaluation contracts and purpose-scoped source retention. */
(() => {
  'use strict';
  const PROFILE = 'bounded-reliability-evidence-v1';
  let dialog, content, status, workspace = '', session = '', epoch = 0, options, busy = false;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const id = prefix => `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(16)), v => v.toString(16).padStart(2, '0')).join('')}`;
  const button = (text, run) => { const n = node('button', text); n.type = 'button'; n.className = 'btn'; n.addEventListener('click', run); return n; };
  const line = (parent, text) => parent.append(node('p', text));
  const field = (parent, label, value = '', type = 'text') => { const l = node('label', `${label} `), input = node(type === 'textarea' ? 'textarea' : 'input'); if (type !== 'textarea') input.type = type; input.value = value; input.style.width = '100%'; input.style.boxSizing = 'border-box'; if (type === 'textarea') { input.rows = 7; input.spellcheck = false; } l.append(input); parent.append(l); return input; };
  const consent = (parent, text) => { const l = node('label'), input = node('input'); input.type = 'checkbox'; input.checked = false; l.append(input, ' ', node('span', text)); parent.append(l); return input; };
  const stamp = () => ({epoch, workspace, session});
  const valid = s => dialog?.open && s.epoch === epoch && s.workspace === workspace && s.session === session && identity() === session;
  const tell = text => { if (status) status.textContent = text; };
  function leave() { epoch++; workspace = session = ''; busy = false; dialog?.close(); dialog?.remove(); dialog = content = status = options = null; }
  function onSession() { if (session && (identity() !== session || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, body) {
    const response = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/reliability${path}`, body === undefined ? {silent: true} : {method: 'POST', json: body, silent: true});
    if (response?.ok !== true || response.profile !== PROFILE) throw Error('invalid_reliability_response');
    return response.result;
  }
  async function perform(path, body, confirmation) {
    if (busy || !confirmation.checked) { tell('Select the purpose-specific authorization before submitting.'); return; }
    confirmation.checked = false; busy = true; const captured = stamp();
    try { await request(path, body); if (valid(captured)) { busy = false; await refresh(); tell('Saved. Current authority and evidence have been read again.'); } }
    catch (error) { if (valid(captured)) tell([401,403,404].includes(error?.status) ? 'Session or scoped access changed. Close and reopen this view.' : 'This command could not be confirmed. Read current state before submitting again.'); }
    finally { if (valid(captured)) busy = false; }
  }
  const section = title => { const n = node('section'); n.className = 'card'; Object.assign(n.style, {padding: '16px', margin: '12px 0', overflowWrap: 'anywhere'}); n.append(node('h3', title)); content.append(n); return n; };
  const templates = {
    plan: {dataset_version: 'approved-corpus-v1', dataset_hash: '0'.repeat(64), rubric_version: 'task-rubric-v1', rubric_hash: '0'.repeat(64), minimum_samples: 20, window_seconds: 86400, confidence: 'wilson-95-v1', environment: 'isolated', evaluator_version: 'trusted-evaluator-v1'},
    case: {plan_id: 'Choose a saved plan', plan_revision: 1, case_version: 'baseline-v1', case_hash: '0'.repeat(64), category: 'baseline'},
    cohort: {plan_id: 'Choose a saved plan', plan_revision: 1, case_ids: [], resource_id: 1, contract_id: 'news.search.v1', purpose: 'independent-read-evaluation'}
  };
  function editor(objects) {
    const card = section('Immutable plans, cases and cohorts');
    line(card, 'Save a new version after a change. Authorization pins the exact current plan, cases, agent, contract, schema and owner authority. A saved contract does not dispatch an evaluation.');
    const kindLabel = node('label', 'Contract kind '), kind = node('select'); for (const k of ['plan','case','cohort']) kind.append(new Option(k, k)); kindLabel.append(kind); card.append(kindLabel);
    const objectId = field(card, 'Object reference', id('reo')), revision = field(card, 'Expected current revision', '0', 'number'), spec = field(card, 'Bounded contract specification', JSON.stringify(templates.plan, null, 2), 'textarea');
    const confirm = consent(card, 'Authorize this exact version for private evaluation contract preparation.');
    kind.addEventListener('change', () => { objectId.value = id('reo'); revision.value = '0'; spec.value = JSON.stringify(templates[kind.value], null, 2); confirm.checked = false; });
    card.append(button('Save immutable version', () => { let parsed; try { parsed = JSON.parse(spec.value); } catch { tell('Provide a valid bounded contract specification.'); return; } perform('/objects', {command_id: id('rec'), object_id: objectId.value, kind: kind.value, revision: Number(revision.value), spec: parsed, authorized: true, notice: options.notices.contract}, confirm); }));
    for (const item of objects) {
      const row = node('div'); row.className = 'card'; row.style.padding = '12px'; row.style.margin = '8px 0';
      line(row, `${item.kind} · ${item.id} · revision ${item.revision}${item.revoked ? ' · permanently revoked' : ''}`);
      const details = node('details'); details.append(node('summary', 'Inspect immutable specification'), node('pre', JSON.stringify(item.spec, null, 2))); details.style.whiteSpace = 'pre-wrap'; row.append(details);
      row.append(button('Prepare next version', () => { kind.value = item.kind; objectId.value = item.id; revision.value = String(item.revision); spec.value = JSON.stringify(item.spec, null, 2); confirm.checked = false; objectId.focus(); }));
      if (!item.revoked) { const revoke = consent(row, 'Permanently revoke this object and make dependent evidence ineligible.'); row.append(button('Revoke contract', () => perform('/erasures', {command_id: id('rec'), target_id: item.id, target_kind: 'object', reason: 'withdrawn', authorized: true, notice: options.notices.erase}, revoke))); }
      card.append(row);
    }
  }
  function authorization(objects, inventory) {
    const card = section('Purpose-specific cohort authorization');
    const cohort = field(card, 'Cohort reference', objects.filter(v => v.kind === 'cohort' && !v.revoked).at(-1)?.id || ''), revision = field(card, 'Cohort revision', '1', 'number'), retention = field(card, 'Retention seconds (60–604800)', '3600', 'number');
    line(card, 'Source retention requires configured authenticated encryption. Separate evaluation permission never authorizes provider dispatch, public certification or marketing.');
    const confirm = consent(card, 'Authorize this exact cohort for private independent read evaluation and encrypted source retention until its stated expiry.');
    card.append(button('Authorize cohort retention', () => perform('/consents', {command_id: id('rec'), consent_id: id('ren'), cohort_id: cohort.value, cohort_revision: Number(revision.value), retention_seconds: Number(retention.value), authorized: true, notice: options.notices.retain}, confirm)));
    for (const item of inventory.consents) {
      const row = node('div'); line(row, `${item.id} · ${item.cohort_id} · ${item.current ? 'current' : 'inactive, expired or authority changed'} · expires ${new Date(item.expires*1000).toISOString()}`);
      const erase = consent(row, 'Permanently withdraw this authorization and erase its retained source bundles.'); row.append(button('Withdraw authorization', () => perform('/erasures', {command_id: id('rec'), target_id: item.id, target_kind: 'consent', reason: 'withdrawn', authorized: true, notice: options.notices.erase}, erase))); card.append(row);
    }
  }
  function sources(inventory) {
    const card = section('Encrypted private source bundles');
    const consentId = field(card, 'Current consent reference', inventory.consents.find(v => v.current)?.id || ''), bundle = field(card, 'Source bundle (input, output and sources)', JSON.stringify({input: {}, output: null, sources: []}, null, 2), 'textarea');
    const confirm = consent(card, 'Retain only this necessary source bundle for the selected purpose and expiry.');
    card.append(button('Retain encrypted source', () => { let parsed; try { parsed = JSON.parse(bundle.value); } catch { tell('Provide one bounded source bundle.'); return; } perform('/sources', {command_id: id('rec'), source_id: id('res'), consent_id: consentId.value, bundle: parsed, authorized: true, notice: options.notices.retain}, confirm); }));
    for (const item of inventory.sources) {
      const row = node('section'); row.className = 'card'; row.style.padding = '12px'; line(row, `${item.id} · ${item.retained ? 'retained' : 'expired'} · ${item.cohort_id}`);
      const inspect = consent(row, 'Inspect this private source for the authorized evaluation purpose.');
      row.append(button('Inspect private source', async () => { if (busy || !inspect.checked) return; inspect.checked = false; busy = true; const captured = stamp(); try { const value = await request(`/sources/${encodeURIComponent(item.id)}/inspect`, {authorized: true, notice: options.notices.retain}); if (valid(captured)) { const pre = node('pre', JSON.stringify(value.bundle, null, 2)); pre.style.whiteSpace = 'pre-wrap'; row.append(pre); } } catch { if (valid(captured)) tell('The current private source is unavailable.'); } finally { if (valid(captured)) busy = false; } }));
      const erase = consent(row, 'Permanently erase this source and prevent this bundle from qualifying again.'); row.append(button('Erase source permanently', () => perform('/erasures', {command_id: id('rec'), target_id: item.id, target_kind: 'source', reason: 'source_deleted', authorized: true, notice: options.notices.erase}, erase))); card.append(row);
    }
    line(card, `Permanent revocation and erasure tombstones: ${inventory.permanent_tombstones}.`);
    const cleanup = consent(card, 'Permanently erase all expired retained source bundles in this workspace.');
    card.append(button('Erase expired source bundles', () => perform('/retention-cleanup', {command_id: id('rec'), authorized: true, notice: options.notices.erase}, cleanup)));
  }
  function observations(inventory, objects) {
    const card = section('Bind an actual retained execution');
    line(card, 'The run must occur after current cohort authorization. Input and output must match the signed original execution. Failed and unknown outcomes remain separate; duplicate logical tasks and attempts count once.');
    const consentId = field(card, 'Observation consent reference', inventory.consents.find(v => v.current)?.id || ''), caseId = field(card, 'Case reference', objects.find(v => v.kind === 'case' && !v.revoked)?.id || ''), sourceId = field(card, 'Retained source reference', inventory.sources[0]?.id || ''), runRef = field(card, 'Signed private run reference'), logical = field(card, 'Logical task reference', id('ret'));
    const confirm = consent(card, 'Bind this actual execution and retained source to the selected evaluation case.');
    card.append(button('Record bound observation', () => perform('/observations', {command_id: id('rec'), observation_id: id('reb'), consent_id: consentId.value, case_id: caseId.value, source_id: sourceId.value, run_ref: runRef.value, logical_task_id: logical.value, authorized: true, notice: options.notices.contract}, confirm)));
    for (const item of inventory.observations) line(card, `${item.id} · ${item.case_id} · ${item.outcome} · logical task ${item.logical_task_id}`);
  }
  function reporting() {
    const card = section('Current private evaluation report'), rid = field(card, 'Report resource reference', '1', 'number'), output = node('div');
    card.append(button('Read current evaluation report', async () => { if (busy) return; busy = true; const captured = stamp(); output.replaceChildren(); try { const report = await request(`/report?resource_id=${encodeURIComponent(rid.value)}`); if (!valid(captured)) return; for (const group of report.groups) { line(output, `${group.contract_id} · ${group.environment} · ${group.logical_samples} logical samples · quality ${group.quality_status} · source fidelity ${group.source_fidelity}`); line(output, `Succeeded ${group.outcomes.succeeded}; failed ${group.outcomes.failed}; unknown ${group.outcomes.unknown}; unassessed ${group.quality_outcomes.unassessed}; duplicate attempts removed ${group.duplicates_removed}.`); line(output, `Threshold ${group.minimum_sample_met ? 'met' : 'not met'}; success interval ${group.success_interval.lower.toFixed(3)}–${group.success_interval.upper.toFixed(3)}; gateway interval p50 ${group.latency_ms.p50.toFixed(1)} ms, p95 ${group.latency_ms.p95.toFixed(1)} ms.`); } if (!report.groups.length) line(output, 'Insufficient evidence. No current eligible bound observations.'); line(output, 'No operating qualification or public activation is granted.'); } catch { if (valid(captured)) tell('The current scoped report is unavailable.'); } finally { if (valid(captured)) busy = false; } }), output);
  }
  async function refresh() {
    if (busy) return; epoch++; const captured = stamp(); busy = true; content.replaceChildren(); tell('Reading current versions, authority and retention.');
    try { const [objects, inventory] = await Promise.all([request('/objects'), request('/inventory')]); if (!valid(captured)) return; if (options.can_manage) { editor(objects); authorization(objects, inventory); sources(inventory); observations(inventory, objects); } else { for (const item of objects) line(content, `${item.kind} · ${item.id} · revision ${item.revision}`); } reporting(); tell('Private evaluation contracts loaded. No provider calls were made.'); }
    catch { if (valid(captured)) tell('Current scoped evaluation data could not be read.'); }
    finally { if (valid(captured)) busy = false; }
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceReliabilityDialog';
    Object.assign(dialog.style, {width:'min(1040px,94vw)',maxWidth:'94vw',maxHeight:'88vh',boxSizing:'border-box',borderRadius:'18px',padding:'24px',overflow:'auto',color:'var(--text,#172235)',background:'var(--card,#fff)',border:'1px solid var(--border,#dce3ee)'});
    const heading = node('h2', 'Private evaluation evidence'); heading.id = 'workspaceReliabilityTitle'; dialog.setAttribute('aria-labelledby', heading.id);
    const icon = document.createElementNS('http://www.w3.org/2000/svg','svg'); for (const [k,v] of Object.entries({viewBox:'0 0 24 24',width:'22',height:'22',fill:'none',stroke:'currentColor','stroke-width':'2','aria-hidden':'true'})) icon.setAttribute(k,v); const path = document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d','M9 3h6l1 2h4v16H4V5h4l1-2M8 11h8M8 15h5'); icon.append(path); heading.prepend(icon,document.createTextNode(' '));
    status = node('p'); status.setAttribute('role','status'); content = node('div');
    dialog.append(heading,button('Close evaluation evidence',leave),button('Read current contract state',refresh),status,content); document.body.append(dialog); dialog.addEventListener('cancel',leave); dialog.showModal();
    const captured = stamp(); try { options = await request('/options'); if (valid(captured)) { line(dialog, `Trusted evaluator ${options.trusted_evaluator_configured ? 'configured' : 'unconfigured; quality remains unassessed'}. Source encryption ${options.encryption_configured ? 'configured' : 'unconfigured; retention unavailable'}.`); await refresh(); } } catch { if (valid(captured)) tell('The current administrator session or workspace is unavailable.'); }
  }
  window.WorkspaceReliabilityAdmin = {open,leave,onSession};
})();
