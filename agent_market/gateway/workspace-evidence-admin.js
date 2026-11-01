/* Scoped retained evidence. No evaluator, provider call or public badge is created. */
(() => {
  'use strict';
  const PROFILE = 'bounded-evidence-rollup-v1';
  let dialog = null, body = null, status = null, workspace = '', session = '', epoch = 0, busy = false, locked = false;
  let options = null, scope = null, resource = null;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
  const button = (text, action) => { const value = node('button', text); value.type = 'button'; value.className = 'btn'; value.addEventListener('click', action); return value; };
  const stamp = () => ({epoch, workspace, session, scope: scope?.value, resource: resource?.value});
  const valid = value => Boolean(dialog?.open && value.epoch === epoch && value.workspace === workspace && value.session === session && session === identity() && value.scope === scope?.value && value.resource === resource?.value);
  const tell = text => { if (status) status.textContent = text; };
  function leave() { epoch++; busy = locked = false; workspace = session = ''; if (dialog) { dialog.close(); dialog.remove(); } dialog = body = status = options = scope = resource = null; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, value) {
    const result = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/evidence${path}`, value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (result?.ok !== true || result.profile !== PROFILE) throw Error('unsupported_evidence');
    return result.result;
  }
  function clear() { epoch++; busy = locked = false; body?.replaceChildren(); tell('Read current retained evidence for the selected scope.'); }
  function line(parent, text) { parent.append(node('p', text)); }
  function failure(error) { tell([401, 403, 404].includes(error?.status) ? 'Current session or scoped evidence access changed. Close and reopen this view.' : 'The evidence result could not be confirmed. Read current state before any new request.'); }
  function date(value) { return typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toISOString() : 'Unavailable'; }
  async function refresh() {
    if (busy) return;
    const rid = Number(resource.value); if (!Number.isSafeInteger(rid) || rid < 1 || rid >= 2147483648) { tell('Enter one valid catalog resource reference.'); return; }
    epoch++; const current = stamp(); busy = true; body.replaceChildren(); tell('Revalidating current authority, version, retention and expiry.');
    try {
      const report = await request(`/rollup?resource_id=${rid}&scope=${encodeURIComponent(scope.value)}`);
      if (!valid(current)) return;
      locked = false;
      line(body, `Resource ${report.current.resource_id} · ${report.current.protocol.toUpperCase()} · ${report.current.profile_version}`);
      line(body, `Current version: ${report.current.version_id}. Evidence scope: ${report.scope}.`);
      line(body, 'Quality is unassessed. Retained metadata does not establish source fidelity, independent review, operating quality or an execution permission.');
      line(body, `Current execution controls: ${report.current.execution_controls_enabled ? 'enabled' : 'paused'}. Observations do not authorize a new call.`);
      if (!report.groups.length) line(body, 'Insufficient evidence: no eligible retained observations are available.');
      for (const group of report.groups) {
        const card = node('section'); card.className = 'card'; card.style.margin = '12px 0'; card.style.padding = '16px';
        card.append(node('h3', `${group.evidence_scope} · ${group.contract_id || 'Execution profile'}`));
        line(card, `Dataset ${group.dataset_version} · validator ${group.validator_version}`);
        line(card, `Logical observations ${group.logical_samples}; succeeded ${group.outcomes.succeeded}; failed ${group.outcomes.failed}; unknown ${group.outcomes.unknown}. Duplicate attempts removed: ${group.duplicates_removed}.`);
        line(card, group.minimum_sample_met ? 'The metadata sample threshold is met; no quality certification follows.' : 'Insufficient evidence: the metadata sample threshold is not met.');
        line(card, `Observed interval p50 ${group.latency_ms.p50 ?? 'Unavailable'} ms; p95 ${group.latency_ms.p95 ?? 'Unavailable'} ms. Scope: ${report.policy.latency_scope}; provider latency is not inferred.`);
        body.append(card);
      }
      const excluded = Object.entries(report.excluded_sources).filter(([, count]) => count > 0).map(([key, count]) => `${key}: ${count}`).join('; ');
      line(body, `Excluded retained records: ${excluded || 'none'}. Next evidence boundary: ${date(report.valid_until)}.`);
      if (report.truncated) line(body, 'This bounded view is truncated. Counts describe the retained sources inspected here, not all history.');
      for (const source of report.sources) {
        const card = node('section'); card.className = 'card'; card.style.padding = '12px'; card.style.margin = '10px 0';
        line(card, `${source.source_ref} · ${source.state} · observed ${date(source.observed_at)} · expires ${date(source.expires)}`);
        if (options.can_withdraw && source.withdrawal_revision === 0) {
          const label = node('label'), consent = node('input'); consent.type = 'checkbox'; consent.checked = false;
          label.append(consent, ' ', node('span', 'Withdraw this exact source from this workspace scope. This is permanent and does not delete or rewrite the original record.'));
          card.append(label, button('Withdraw source', async () => {
            if (busy || locked || !consent.checked || !valid(current)) return;
            consent.checked = false; busy = locked = true;
            try {
              await request('/withdrawals', {scope: current.scope, resource_id: rid, source_ref: source.source_ref, revision: 0, reason: 'source_withdrawn', authorized: true, notice: options.withdrawal_notice});
              if (!valid(current)) return;
              busy = false; await refresh();
            } catch (error) { if (valid(current)) { failure(error); tell('Withdrawal could not be confirmed. Read current evidence before trying another command.'); } }
            finally { if (valid(current)) busy = false; }
          }));
        }
        body.append(card);
      }
      tell('Current retained evidence loaded. No provider calls were made.');
    } catch (error) { if (valid(current)) failure(error); }
    finally { if (valid(current)) busy = false; }
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceEvidenceDialog';
    Object.assign(dialog.style, {width: 'min(1000px,94vw)', maxWidth: '94vw', maxHeight: '86vh', boxSizing: 'border-box', borderRadius: '18px', padding: '22px', overflow: 'auto', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const header = node('div'); Object.assign(header.style, {display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: '0', zIndex: '1', background: 'inherit'});
    const title = node('h2', 'Retained evidence'); title.id = 'workspaceEvidenceTitle'; dialog.setAttribute('aria-labelledby', title.id);
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '22'); icon.setAttribute('height', '22'); icon.setAttribute('fill', 'none'); icon.setAttribute('stroke', 'currentColor'); icon.setAttribute('stroke-width', '2'); icon.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M3 3v18h18M18 17V9M13 17V5M8 17v-3'); icon.append(path);
    title.prepend(icon, document.createTextNode(' ')); header.append(title, button('Close evidence', leave));
    status = node('p', 'Reading available evidence scopes.'); status.setAttribute('role', 'status');
    body = node('div'); body.style.overflowWrap = 'anywhere'; dialog.append(header, status, body); document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal();
    const captured = {epoch, workspace, session};
    try {
      options = await request('/options');
      if (!dialog?.open || captured.epoch !== epoch || captured.workspace !== workspace || captured.session !== identity()) return;
      const controls = node('div'); controls.className = 'row'; controls.style.gap = '12px';
      const scopeLabel = node('label', 'Evidence scope '); scope = node('select');
      for (const value of options.scopes) scope.append(new Option(value === 'catalog' ? 'Catalog administrative metadata' : 'This workspace private executions', value));
      scopeLabel.append(scope);
      const resourceLabel = node('label', 'Resource reference '); resource = node('input'); resource.type = 'number'; resource.min = '1'; resource.max = '2147483647'; resource.value = String(options.resources[0]?.resource_id || 1); resourceLabel.append(resource);
      scope.addEventListener('change', clear); resource.addEventListener('input', clear);
      controls.append(scopeLabel, resourceLabel, button('Read current evidence', refresh)); dialog.insertBefore(controls, body);
      await refresh();
    } catch (error) { if (dialog?.open && captured.epoch === epoch) failure(error); }
  }
  window.WorkspaceEvidenceAdmin = {open, leave, onSession};
})();
