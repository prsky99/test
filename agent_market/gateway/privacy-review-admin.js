/* Individual administrator review; a receipt never proves a completed action. */
(() => {
  'use strict';
  const statuses = ['received', 'pending_verification', 'processing', 'completed', 'declined'];
  let dialog, body, message, epoch = 0, session = '', selected = '', busy = false;
  let returnFocus = null;
  const node = (tag, text) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; return item; };
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const stamp = () => ({epoch, session, selected});
  const valid = mark => Boolean(dialog?.open && mark.epoch === epoch && mark.session === session && mark.selected === selected && session === identity());
  const button = (text, action) => { const item = node('button', text); item.type = 'button'; item.className = 'btn'; item.addEventListener('click', action); return item; };
  function leave() {
    epoch++; selected = session = ''; busy = false;
    if (dialog) { dialog.close(); dialog.remove(); }
    dialog = body = message = null;
    if (returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  }
  function onSession() { if (session && session !== identity()) leave(); }
  const date = value => typeof value === 'number' && Number.isFinite(value) && value > 0 ? new Date(value * 1000).toLocaleString() : 'Not recorded';
  function field(parent, label, item) {
    const wrap = node('label', label); wrap.style.display = 'block'; wrap.style.margin = '14px 0';
    item.setAttribute('aria-label', label); item.style.display = 'block'; item.style.width = '100%';
    wrap.append(item); parent.append(wrap); return item;
  }
  function show(row) {
    body.replaceChildren();
    const facts = node('dl'); facts.style.overflowWrap = 'anywhere';
    const reference = typeof row.proof_hash === 'string' ? row.proof_hash : '';
    const factsList = [
      ['Request reference', row.request_id], ['Request type', row.request_type], ['Current status', row.status],
      ['Received', date(row.created_at)], ['Recorded deadline', date(row.statutory_deadline)],
      ['Completed at', date(row.completed_at)], ['Email', row.email || 'Not supplied'],
      ['Masked visitor reference', row.visitor_token_masked || 'Not supplied'],
      ['GPC signal recorded', row.gpc_detected ? 'Yes' : 'No'],
      [reference.length === 64 ? 'Reviewed evidence reference (SHA-256)' : 'Receipt reference (not completion evidence)', reference || 'Not recorded'],
      ['Request details', row.details || 'No additional details']
    ];
    for (const [label, value] of factsList) {
      facts.append(node('dt', label)); const detail = node('dd', value);
      detail.style.whiteSpace = 'pre-wrap'; detail.style.marginBottom = '10px'; facts.append(detail);
    }
    body.append(facts, node('p', 'Reading this request does not change its status. A receipt reference records intake only. Complete an action only after the actual response or preference handling has been reviewed; the evidence reference does not perform that action.'));
    const form = node('form');
    const status = field(form, 'Review status', node('select')); status.id = 'privacyReviewStatus';
    for (const value of statuses) { const option = new Option(value, value); option.disabled = row.status === 'completed' && value !== 'completed'; status.append(option); }
    status.value = row.status;
    const notes = field(form, 'Review notes', node('textarea')); notes.id = 'privacyReviewNotes'; notes.rows = 5; notes.maxLength = 2000; notes.value = row.notes || '';
    const proof = field(form, 'Reviewed completion evidence SHA-256', node('input')); proof.id = 'privacyReviewProof'; proof.type = 'text'; proof.maxLength = 64; proof.autocomplete = 'off'; proof.spellcheck = false;
    proof.value = /^[0-9a-f]{64}$/.test(reference) ? reference : '';
    form.append(node('p', 'For completed, enter a review note of 10–2,000 characters and the 64-character lowercase SHA-256 of the reviewed completion evidence. Keep the evidence in its approved private record; do not paste personal data or secrets here.'));
    const validation = node('p'); validation.id = 'privacyReviewValidation'; validation.setAttribute('role', 'status');
    const submit = button('Save reviewed status', () => {}); submit.type = 'submit'; submit.id = 'privacyReviewSave';
    const initial = {status: row.status, notes: notes.value.trim(), proof: proof.value};
    function update() {
      const note = notes.value.trim(), hash = proof.value.trim(), complete = status.value === 'completed';
      const changed = status.value !== initial.status || note !== initial.notes || hash !== initial.proof;
      const validProof = !hash || /^[0-9a-f]{64}$/.test(hash);
      const approved = statuses.includes(status.value) && note.length <= 2000 && validProof && (!complete || note.length >= 10 && /^[0-9a-f]{64}$/.test(hash));
      submit.disabled = busy || !approved || !changed;
      validation.textContent = complete && !approved ? 'Completion requires a review note of 10–2,000 characters and a 64-character lowercase evidence SHA-256. An intake receipt is insufficient.' : !validProof ? 'Use a 64-character lowercase SHA-256 evidence reference.' : '';
    }
    form.addEventListener('input', update); form.addEventListener('change', update);
    form.addEventListener('submit', async event => {
      event.preventDefault(); update(); if (submit.disabled) return;
      const captured = stamp(), payload = {status: status.value, notes: notes.value.trim()};
      if (proof.value.trim()) payload.proof_hash = proof.value.trim();
      busy = true; submit.disabled = true; status.disabled = notes.disabled = proof.disabled = true;
      message.textContent = 'Recording this reviewed status. No request is retried automatically.';
      try {
        await api(`/admin/api/needs/privacy/${encodeURIComponent(selected)}`, {method: 'PATCH', json: payload, silent: true});
        if (!valid(captured)) return;
        busy = false;
        await Promise.all([loadNeedsSummary(), loadPrivacyRequests()]);
        if (valid(captured)) await readCurrent('Reviewed status recorded. The list and current request have been reloaded.');
      } catch (_) {
        if (valid(captured)) {
          busy = false; message.textContent = 'The response could not be confirmed. Read the current request before another review; no update was retried.';
          // Leave the form disabled until an explicit current-state read.
        }
      }
    });
    form.append(validation, submit); body.append(form); update();
  }
  async function readCurrent(successMessage) {
    if (busy) return;
    busy = true; const captured = stamp(); body.replaceChildren(); message.textContent = 'Reading the current privacy request.';
    try {
      const data = await api(`/admin/api/needs/privacy?q=${encodeURIComponent(selected)}&limit=50`, {silent: true});
      if (!valid(captured)) return;
      const row = Array.isArray(data?.items) ? data.items.find(item => item.request_id === selected) : null;
      if (!row || !statuses.includes(row.status)) throw Error('unavailable');
      busy = false; show(row); message.textContent = successMessage || 'Current request loaded. Viewing this record has not changed its status.';
    } catch (_) {
      if (valid(captured)) { busy = false; body.replaceChildren(); message.textContent = 'The current request or session is unavailable. No status change is authorized.'; }
    }
  }
  async function open(id, trigger) {
    leave(); if (typeof id !== 'string' || !/^prv_[A-Za-z0-9_-]{24}$/.test(id) || !identity()) return;
    selected = id; session = identity(); returnFocus = trigger || document.activeElement;
    dialog = node('dialog'); dialog.id = 'privacyReviewDialog';
    Object.assign(dialog.style, {width: 'min(860px,92vw)', maxHeight: '86vh', overflow: 'auto', margin: 'auto', padding: '24px', borderRadius: '18px',
      background: 'var(--card,#fff)', color: 'var(--text,#172235)', border: '1px solid var(--line,#dce3ee)'});
    const title = node('h2', 'Privacy request review'); title.id = 'privacyReviewTitle'; dialog.setAttribute('aria-labelledby', title.id);
    message = node('p'); message.setAttribute('role', 'status'); message.id = 'privacyReviewMessage';
    body = node('div'); body.id = 'privacyReviewBody';
    const actions = node('div'); actions.style.display = 'flex'; actions.style.gap = '10px';
    actions.append(button('Close privacy review', leave), button('Read current request', () => readCurrent()));
    dialog.append(title, actions, message, body); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); leave(); });
    dialog.showModal(); await readCurrent();
  }
  function attach(container, rows) {
    onSession(); if (!container || !Array.isArray(rows)) return;
    const header = container.querySelector('thead tr'), bodyRows = container.querySelectorAll('tbody tr');
    if (!header || header.querySelector('[data-privacy-review-header]')) return;
    const head = node('th', 'Review'); head.dataset.privacyReviewHeader = '1'; header.append(head);
    for (let i = 0; i < bodyRows.length; i++) {
      const id = rows[i]?.request_id; if (typeof id !== 'string') continue;
      const cell = node('td'), review = button('검토', () => open(id, review));
      review.classList.add('sm'); review.dataset.privacyReviewId = id; review.setAttribute('aria-label', `Review privacy request ${id}`); cell.append(review); bodyRows[i].append(cell);
    }
  }
  window.addEventListener('pagehide', leave);
  window.PrivacyReviewAdmin = {attach, open, leave, onSession};
})();
