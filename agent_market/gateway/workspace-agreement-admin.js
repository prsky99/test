/* Private provider term records and integer simulation. Real commerce stays disabled. */
(() => {
  'use strict';
  const PROFILE = 'workspace-advancement-tools-v1';
  const NOTICE = 'workspace-agreement-simulation-v1';
  let dialog = null, content = null, status = null, workspace = '', session = '', epoch = 0;
  let busy = false, locked = false;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
  const button = (label, handler) => { const value = node('button', label); value.type = 'button'; value.className = 'btn'; value.addEventListener('click', handler); return value; };
  const field = (label, type = 'text', initial = '') => {
    const host = node('label', label), input = node('input');
    host.className = 'form-group'; input.type = type; input.value = initial; input.autocomplete = 'off';
    host.style.minWidth = '0'; input.style.maxWidth = '100%'; input.style.boxSizing = 'border-box';
    host.append(input); return {host, input};
  };
  const check = label => { const host = node('label'), input = node('input'); input.type = 'checkbox'; input.checked = false; host.append(input, ' ', node('span', label)); return {host, input}; };
  const tell = message => { if (status) status.textContent = message; };
  const mark = () => ({epoch, workspace, session});
  const valid = value => Boolean(dialog?.open && value.epoch === epoch && value.workspace === workspace && value.session === session && session === identity());
  const integer = (input, minimum, maximum) => { const value = Number(input.value); return Number.isSafeInteger(value) && value >= minimum && value <= maximum ? value : null; };
  const reference = () => 'sim_' + Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');
  function leave() { epoch++; busy = false; locked = false; workspace = ''; session = ''; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = status = null; }
  function onSession() { const selected = document.getElementById('workspaceSelect'); if (session && (identity() !== session || selected?.value && selected.value !== workspace)) leave(); }
  async function request(path, value) {
    const options = value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true};
    const result = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/advancement${path}`, options);
    if (result?.ok !== true || result.profile !== PROFILE) throw Error('unsupported_profile');
    return result.result;
  }
  function failure(error) {
    tell([401, 403, 404].includes(error?.status) ? 'Current owner access or endpoint control changed. Close and reopen this view.' : 'The result could not be confirmed. Refresh the recorded history before making a new request. No request is retried automatically.');
  }
  async function change(path, value) {
    if (busy || locked) return;
    const current = mark(); busy = true; locked = true; tell('Submitting one reviewed simulation request.');
    try {
      await request(path, value); if (!valid(current)) return;
      busy = false; await refresh();
    } catch (error) { if (valid(current)) failure(error); }
    finally { if (valid(current)) busy = false; }
  }
  function line(parent, text) { parent.append(node('p', text)); }
  function formRow(...children) { const row = node('div'); row.className = 'row'; row.style.gap = '10px'; row.style.flexWrap = 'wrap'; row.append(...children); return row; }
  function allocation(parent, value) {
    line(parent, `Gross ${value.gross_units} TEST_UNIT; processing ${value.processing_units}; tax ${value.tax_units}; distributable ${value.distributable_units}.`);
    line(parent, `Provider ${value.provider_units}; platform ${value.platform_units}. Integer remainders belong to the platform at capture.`);
  }
  function createForm(options, versions, claims) {
    const section = node('section'); section.className = 'card'; section.append(node('h3', 'Record a provider agreement version'));
    line(section, 'This is a platform integrity record. A document hash and endpoint challenge do not prove legal provider assent.');
    const claimLabel = node('label', 'Current verified endpoint claim '), claim = node('select');
    claim.style.maxWidth = '100%'; claim.style.minWidth = '0'; claim.style.boxSizing = 'border-box';
    claim.append(new Option('Select a verified resource', ''));
    for (const value of claims.filter(value => value.status === 'verified' && !value.revoked && value.valid_until > Date.now() / 1000)) claim.append(new Option(`Resource ${value.resource_id} · ${value.id}`, value.id));
    claimLabel.append(claim);
    const document = field('Opaque terms document reference'), digest = field('Terms document SHA-256');
    document.input.maxLength = 64; digest.input.maxLength = 64;
    const processing = field('Processing deduction basis points', 'number', '0'), fixed = field('Processing fixed TEST_UNIT', 'number', '0'), tax = field('Tax deduction basis points', 'number', '0');
    processing.input.min = fixed.input.min = tax.input.min = '0'; processing.input.max = '2500'; tax.input.max = '5000'; fixed.input.max = String(options.max_units);
    const consent = check('Record this exact 70% provider / 30% platform TEST_UNIT simulation agreement as legally unverified.');
    section.append(claimLabel, document.host, digest.host, formRow(processing.host, fixed.host, tax.host), consent.host);
    const submit = button('Record agreement version', () => {
      if (!consent.input.checked) return;
      const selected = claims.find(value => value.id === claim.value), p = integer(processing.input, 0, 2500), f = integer(fixed.input, 0, options.max_units), t = integer(tax.input, 0, 5000);
      if (!selected || p === null || f === null || t === null || !/^[a-z][a-z0-9_-]{0,63}$/.test(document.input.value) || !/^[0-9a-f]{64}$/.test(digest.input.value)) { tell('Select a verified claim and review the bounded document reference, SHA-256 and integer deductions.'); return; }
      consent.input.checked = false;
      const head = versions.heads.find(value => value.resource_id === selected.resource_id);
      change('/agreements', {resource_id: selected.resource_id, claim_id: selected.id, claim_revision: selected.revision, revision: head?.revision || 0,
        expires: Math.min(Date.now() / 1000 + 86400, selected.valid_until), authorized: true, notice: NOTICE,
        terms: {asset: 'TEST_UNIT', scale: 0, provider_bps: 7000, platform_bps: 3000, base: 'gross_less_processing_then_tax',
          deductions: {processing_bps: p, processing_fixed_units: f, tax_bps: t}, refund_responsibility: 'proportional_original_components',
          rounding: 'floor_provider_platform_remainder', document_reference: document.input.value, document_sha256: digest.input.value}});
    });
    for (const input of [claim, document.input, digest.input, processing.input, fixed.input, tax.input]) input.addEventListener('input', () => { consent.input.checked = false; });
    section.append(submit); if (!claims.length) line(section, 'No verified endpoint claim is available. Complete a current control challenge first.'); content.append(section);
  }
  function versionCard(value, options) {
    const section = node('section'); section.className = 'card'; section.append(node('h3', `Resource ${value.resource_id} · agreement version ${value.ordinal}`));
    line(section, `${value.status} · revision ${value.revision} · current endpoint control: ${value.current_control_verified ? 'verified' : 'unavailable'}.`);
    line(section, `Document reference: ${value.terms.document_reference}. Legal acceptance: unverified.`);
    if (value.status === 'active') {
      const revoke = check('Revoke this exact agreement version for new simulation captures.');
      section.append(revoke.host, button('Revoke version', () => { if (!revoke.input.checked) return; revoke.input.checked = false; change(`/agreements/${encodeURIComponent(value.id)}/revoke`, {revision: value.revision}); }));
    }
    if (value.status === 'active' && value.current_control_verified) {
      const amount = field(`Gross TEST_UNIT for version ${value.ordinal}`, 'number', '100'); amount.input.min = '1'; amount.input.max = String(options.max_units);
      const preview = node('div'); let quote = null, quoteEpoch = 0;
      const clear = () => { quote = null; quoteEpoch++; preview.replaceChildren(); };
      amount.input.addEventListener('input', clear);
      section.append(amount.host, button('Preview allocation', async () => {
        if (busy || locked) return;
        const units = integer(amount.input, 1, options.max_units); if (units === null) { tell('Enter a bounded positive integer.'); return; }
        clear(); const selection = quoteEpoch, current = mark(); busy = true;
        try {
          const result = await request(`/agreements/${encodeURIComponent(value.id)}/quote`, {gross_units: units});
          if (!valid(current) || selection !== quoteEpoch) return;
          quote = result; allocation(preview, result.allocation);
          const consent = check('Record this exact allocation once in TEST_UNIT simulation. No payment or payout will occur.');
          preview.append(consent.host, button('Record simulated settlement', () => {
            if (!quote || !consent.input.checked || selection !== quoteEpoch) return;
            consent.input.checked = false; const reviewed = quote; quote = null;
            change(`/agreements/${encodeURIComponent(value.id)}/settle`, {event_reference: reference(), gross_units: reviewed.allocation.gross_units,
              quote_hash: reviewed.quote_hash, revision: value.revision, authorized: true, notice: NOTICE});
          })); tell('Review the allocation and provide a fresh simulation authorization.');
        } catch (error) { if (valid(current)) failure(error); }
        finally { if (valid(current)) busy = false; }
      }), preview);
    }
    content.append(section);
  }
  function settlementCard(value, options) {
    const section = node('section'); section.className = 'card'; section.append(node('h3', `Simulation ${value.id}`));
    line(section, `${value.status} · revision ${value.revision} · cumulative refund ${value.refunded_units} TEST_UNIT.`); allocation(section, value.remaining);
    if (value.remaining.gross_units > 0) {
      const amount = field(`Refund TEST_UNIT for ${value.id}`, 'number', String(value.remaining.gross_units)); amount.input.min = '1'; amount.input.max = String(value.remaining.gross_units);
      const consent = check('Record this exact incremental simulated refund once under the original agreement terms.');
      amount.input.addEventListener('input', () => { consent.input.checked = false; });
      section.append(amount.host, consent.host, button('Record simulated refund', () => {
        const units = integer(amount.input, 1, value.remaining.gross_units); if (!consent.input.checked || units === null) return;
        consent.input.checked = false;
        change(`/agreement-settlements/${encodeURIComponent(value.id)}/refund`, {event_reference: reference(), units, revision: value.revision, authorized: true, notice: NOTICE});
      }));
      if (value.event_count === options.max_events_per_settlement - 1) line(section, 'The final event must refund the full remaining balance.');
    }
    content.append(section);
  }
  async function refresh() {
    epoch++; const current = mark(); busy = true; content.replaceChildren(); tell('Reading current agreements and simulation history.');
    try {
      const [options, versions, summary, claimResult] = await Promise.all([
        request('/agreements/options'), request('/agreements'), request('/agreements/summary'),
        api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/provider-claims`, {silent: true})]);
      if (!valid(current)) return;
      if (!summary.simulation || summary.actual_money || summary.commercial_enabled || summary.payment_enabled || summary.provider_payout_enabled || !summary.balanced) throw Error('unsupported_simulation');
      locked = false;
      line(content, 'TEST_UNIT simulation only. Real commerce, payments and provider payouts are disabled.');
      line(content, '70% provider / 30% platform applies after processing and tax deductions. Partial refunds use original component proportions and cumulative integer balances.');
      const claims = Array.isArray(claimResult?.claims) ? claimResult.claims : [];
      createForm(options, versions, claims);
      content.append(node('h3', 'Agreement versions')); if (!versions.versions.length) line(content, 'No agreement versions have been recorded.');
      for (const value of versions.versions) versionCard(value, options);
      content.append(node('h3', 'Simulated settlements')); if (!summary.settlements.length) line(content, 'No simulated settlement has been recorded.');
      for (const value of summary.settlements) settlementCard(value, options);
      tell('Current records loaded. Each change needs its own unchecked confirmation.');
    } catch (error) { if (valid(current)) { locked = true; failure(error); } }
    finally { if (valid(current)) busy = false; }
  }
  async function open(value) {
    leave(); const selected = typeof value === 'string' ? value : value?.id;
    if (!/^ws_[0-9a-f]{32}$/.test(selected || '') || !identity()) return;
    workspace = selected; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceAgreementDialog';
    dialog.setAttribute('aria-labelledby', 'workspaceAgreementTitle'); dialog.style.width = 'min(94vw,900px)'; dialog.style.maxHeight = '86vh'; dialog.style.overflow = 'auto';
    dialog.style.boxSizing = 'border-box'; dialog.style.maxWidth = '94vw';
    dialog.style.background = 'var(--panel, Canvas)'; dialog.style.color = 'var(--text, CanvasText)';
    dialog.style.border = '1px solid var(--line)'; dialog.style.borderRadius = '18px'; dialog.style.padding = '24px';
    const header = formRow(node('h2', 'Provider agreements and simulation'), button('Refresh recorded history', refresh), button('Close', leave));
    header.firstChild.id = 'workspaceAgreementTitle'; header.style.position = 'sticky'; header.style.top = '0'; header.style.zIndex = '2'; header.style.background = 'var(--panel, Canvas)'; header.style.paddingBottom = '12px';
    status = node('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); content = node('div'); content.style.overflowWrap = 'anywhere';
    dialog.append(header, status, content); dialog.addEventListener('cancel', leave); document.body.append(dialog); dialog.showModal(); await refresh();
  }
  window.WorkspaceAgreementAdmin = {open, leave, onSession};
  window.addEventListener('pagehide', leave);
  setInterval(onSession, 500);
})();
