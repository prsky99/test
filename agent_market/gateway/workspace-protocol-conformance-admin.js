/* Private synthetic wire checks reuse retained TEST_UNIT records only. */
(() => {
  'use strict';
  let dialog, content, status, workspace = '', session = '', epoch = 0, busy = false, uncertain = false;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; return item; };
  const button = (text, action) => { const item = node('button', text); item.type = 'button'; item.className = 'btn'; item.addEventListener('click', action); return item; };
  const stamp = () => ({epoch, workspace, session});
  const valid = value => Boolean(dialog?.open && value.epoch === epoch && value.workspace === workspace && value.session === session && session === identity());
  function leave() { epoch++; workspace = session = ''; busy = uncertain = false; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = status = null; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path = '', value) {
    const response = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/protocol-conformance${path}`,
      value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (response?.ok !== true || response.profile !== 'workspace-protocol-conformance-v1') throw Error('unsupported_private_review');
    return response.result;
  }
  function field(parent, label, choices) {
    const wrap = node('label', label + ' '), select = node('select'); select.setAttribute('aria-label', label);
    for (const choice of choices) select.append(new Option(choice.label, choice.id));
    Object.assign(wrap.style, {display: 'block', margin: '12px 0'}); wrap.append(select); parent.append(wrap); return select;
  }
  function showReport(report, parent) {
    const section = node('section'); section.className = 'card'; section.append(node('h3', report.event_reference));
    section.append(node('p', `${report.profile_id} · ${report.restored ? 'Restored historical report' : 'Historical observation'} · wire subset ${report.wire_checks.passed ? 'passed' : 'unassessed'}.`));
    section.append(node('p', `Existing TEST_UNIT ledger: ${report.ledger.receipt_state}; capture ${report.ledger.capture_units}; refunded ${report.ledger.refunded_units}; remaining ${report.ledger.remaining_units}; balance ${report.ledger.balanced ? 'verified' : 'unassessed'}.`));
    const states = node('ul');
    for (const key of ['authorization', 'commitment', 'claim', 'settlement', 'finality', 'refund', 'payout', 'business_outcome']) states.append(node('li', `${key}: ${report.states[key]}`));
    section.append(states, node('p', 'No network signature, real escrow, AP2 credential, payment finality or provider payout was verified. A local allocation is not a payment.'));
    parent.append(section);
  }
  async function refresh() {
    if (busy) return; busy = true; const captured = stamp();
    try {
      const value = await request(); if (!valid(captured)) return;
      uncertain = false; content.replaceChildren();
      content.append(node('p', 'This review creates a signed report only. It does not create capture or refund events, send payments, call providers or enable commerce.'));
      const matrix = node('section'); matrix.className = 'card'; matrix.append(node('h3', 'SDK and protocol compatibility'));
      for (const row of value.compatibility) matrix.append(node('p', `${row.product} · ${row.product_version || row.protocol_revision} · ${row.gateway_profile} · ${row.migration}.`));
      matrix.append(node('p', value.security_boundary)); content.append(matrix);
      if (value.cryptographic_profile) {
        const section = node('section'); section.className = 'card';
        section.append(node('h3', 'Offline EIP-3009 signature inspection'));
        section.append(node('p', 'Check a Base Sepolia USDC public authorization against independently reviewed requirements, sender, nonce and resource. This does not verify balances, nonce use, finality, refunds or payment settlement. Enter public proof data only.'));
        const input = node('textarea'); input.setAttribute('aria-label', 'Public proof and independently pinned context'); input.rows = 7; input.maxLength = 15000;
        input.style.width = '100%'; section.append(input);
        const checkLabel = node('label'), approve = node('input'); approve.type = 'checkbox';
        checkLabel.append(approve, ' Inspect this exact public proof without authorizing any transaction.'); section.append(checkLabel);
        const output = node('p'); output.setAttribute('role', 'status'); output.setAttribute('aria-label', 'Offline signature inspection status');
        const inspect = button('Inspect offline signature', async () => {
          if (busy || !value.can_write || !approve.checked) return;
          const current = stamp(); let payload;
          try { payload = JSON.parse(input.value); } catch (_) { output.textContent = 'Provide one JSON proof and independently pinned context.'; return; }
          approve.checked = false; inspect.disabled = true; busy = true;
          try {
            const result = await request('/cryptographic-check', {...payload, authorized: true, notice: value.cryptographic_profile.notice});
            if (valid(current)) output.textContent = result.signature_valid === true && result.verified_payment === false && result.settlement_authorized === false ?
              'Signature and local context matched. Chain checks, nonce consumption and settlement remain unverified. No transaction or ledger event was created.' : 'The proof could not be verified.';
          } catch (_) { if (valid(current)) output.textContent = 'The proof or current permission could not be validated. No transaction was submitted.'; }
          finally { if (valid(current)) busy = false; }
        });
        const resetProof = event => { if (event.target !== approve) approve.checked = false; inspect.disabled = busy || !value.can_write || !approve.checked || !input.value.trim(); };
        section.addEventListener('input', resetProof); section.addEventListener('change', resetProof);
        inspect.disabled = true; approve.disabled = !value.can_write; section.append(inspect, output); content.append(section);
      }
      const form = node('section'); form.className = 'card'; form.append(node('h3', 'Review existing sandbox evidence'));
      const profiles = field(form, 'Synthetic wire profile', value.profiles.map(item => ({id: item.id, label: item.id})));
      const captures = value.sources.filter(item => item.action === 'capture');
      const capture = field(form, 'Existing sandbox capture', [{id: '', label: 'Select one retained capture'}, ...captures.map(item => ({id: item.id, label: `${item.event_reference} · ${item.units} TEST_UNIT`}))]);
      const refunds = value.sources.filter(item => item.action === 'refund');
      const refund = field(form, 'Existing sandbox refund', [{id: '', label: 'No refund selected'}, ...refunds.map(item => ({id: item.id, label: `${item.event_reference} · ${item.units} TEST_UNIT`}))]);
      const label = node('label'), consent = node('input'); consent.type = 'checkbox'; consent.checked = false;
      label.append(consent, ' Review these exact retained sandbox records without creating financial events.'); form.append(label);
      const submit = button('Record synthetic conformance review', async () => {
        if (busy || uncertain || !value.can_write || !consent.checked || !capture.value) return;
        const current = stamp(); busy = true; consent.checked = false; submit.disabled = true;
        status.textContent = 'Checking current authority, signatures and exact ledger source references.';
        try {
          const reference = 'conformance_' + crypto.randomUUID().replaceAll('-', '');
          const report = await request('/runs', {profile_id: profiles.value, capture_intent_id: capture.value,
            refund_intent_id: refund.value || null, event_reference: reference, authorized: true, notice: value.notice});
          if (!valid(current)) return;
          busy = false; await refresh(); if (valid(current)) status.textContent = `Report retained: ${report.event_reference}. No financial event was created.`;
        } catch (error) {
          if (valid(current)) { uncertain = true; status.textContent = 'The report response could not be confirmed. Read current history before another action. No request is retried automatically.'; }
        } finally { if (valid(current)) busy = false; }
      });
      const reset = event => { if (event.target !== consent) consent.checked = false; submit.disabled = !value.can_write || !consent.checked || !capture.value || busy || uncertain; };
      form.addEventListener('input', reset); form.addEventListener('change', reset);
      submit.disabled = true; consent.disabled = !value.can_write; form.append(submit); content.append(form);
      for (const report of value.reports) showReport(report, content);
      status.textContent = 'Current private review state loaded. Chain verification and actual transactions remain disabled.';
    } catch (error) { if (valid(captured)) status.textContent = 'The current signed workspace evidence is unavailable. No action has been authorized.'; }
    finally { if (valid(captured)) busy = false; }
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceProtocolConformanceDialog';
    Object.assign(dialog.style, {width: 'min(1000px,94vw)', maxWidth: '94vw', maxHeight: '86vh', overflow: 'auto',
      borderRadius: '18px', padding: '22px', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const title = node('h2', 'Protocol conformance and ledger review'); title.id = 'workspaceProtocolConformanceTitle'; dialog.setAttribute('aria-labelledby', title.id);
    status = node('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-label', 'Protocol review status'); content = node('div'); content.style.overflowWrap = 'anywhere';
    dialog.append(title, button('Close protocol review', leave), button('Read current protocol history', refresh), status, content);
    document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal(); await refresh();
  }
  window.WorkspaceProtocolConformanceAdmin = {open, leave, onSession};
})();
