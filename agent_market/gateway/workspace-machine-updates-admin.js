/* Separate private evidence notices require current verification and fresh consent. */
(() => {
  'use strict';
  const PROFILE = 'workspace-machine-evidence-updates-v1';
  let dialog = null, content = null, status = null, workspace = '', session = '', epoch = 0, busy = false, uncertain = false;
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
  const button = (text, action) => { const value = node('button', text); value.type = 'button'; value.className = 'btn'; value.addEventListener('click', action); return value; };
  const stamp = () => ({epoch, workspace, session});
  const valid = value => Boolean(dialog?.open && value.epoch === epoch && value.workspace === workspace && value.session === session && session === identity());
  const tell = text => { if (status) status.textContent = text; };
  const line = (parent, text) => parent.append(node('p', text));
  function leave() { epoch++; busy = uncertain = false; workspace = session = ''; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = status = null; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, value) {
    const result = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/machine-updates${path}`,
      value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (result?.ok !== true || result.profile !== PROFILE) throw Error('unsupported_machine_updates');
    return result.result;
  }
  function consent(parent, text, command, action) {
    const label = node('label'), check = node('input'); check.type = 'checkbox'; check.checked = false;
    label.append(check, ' ', node('span', text)); parent.append(label);
    const submit = button(command, async () => {
      if (busy || uncertain || !check.checked) return;
      const captured = stamp(); check.checked = false; busy = true;
      submit.disabled = true; tell('Rechecking current owner, evidence and verified destination.');
      try {
        await action();
        if (!valid(captured)) return;
        busy = false; await refresh();
      } catch (error) {
        if (!valid(captured)) return;
        uncertain = true;
        tell([401, 403, 404].includes(error?.status) ? 'Current authority or verification changed. Read current state before another command.' : 'The command could not be confirmed. Read history; an unknown delivery is never automatically resent.');
      } finally { if (valid(captured)) busy = false; }
    });
    submit.style.margin = '10px 0'; parent.append(submit);
    return {check, submit};
  }
  function field(parent, text, kind = 'text') {
    const label = node('label', text + ' '), input = node('input'); input.type = kind; input.maxLength = 80;
    label.style.display = 'block'; label.style.margin = '10px 0'; label.append(input); parent.append(label); return input;
  }
  async function refresh() {
    if (busy) return;
    epoch++; const captured = stamp(); busy = true; content.replaceChildren(); tell('Reading current machine update state.');
    try {
      const [state, receiver] = await Promise.all([request('/status'), request('/receivers/status').catch(error => { if (error?.status === 404) return null; throw error; })]);
      if (!valid(captured)) return;
      uncertain = false;
      line(content, 'Each subscription is separate from visits, task watches and marketing permission. Advertising is disabled. Automatic evidence updates require a separate bounded purpose grant and an explicitly configured private consumer.');
      line(content, 'A signed receipt confirms delivery only. It never confirms that an agent task completed. Withdrawal stops future dispatch; a notice already in flight cannot be recalled.');
      line(content, 'History describes the metadata prepared for each notice. It is not a current quality certification.');
      line(content, state.destination_verifier_configured && state.sender_configured && state.provider_claims_configured ? 'Trusted adapters are configured. Actual external target acceptance remains unverified.' : 'Delivery is unavailable: current provider control, a destination verifier and a configured sender are required. No external target has been accepted.');
      line(content, 'A subscription retains its authorized agent version and contract scope. Qualification loss may produce an unassessed notice; the same authorized contract may regain qualification. A new contract or agent version requires a fresh subscription.');
      if (state.can_manage) {
        const card = node('section'); card.className = 'card'; card.style.padding = '16px';
        card.append(node('h3', 'Authorize an evidence notice subscription'));
        const resource = field(card, 'Catalog resource reference', 'number'); resource.min = '1';
        const destination = field(card, 'Configured destination reference'); destination.placeholder = 'Opaque configured reference';
        const audience = field(card, 'Configured audience reference');
        const label = node('label', 'Delivery protocol '), protocol = node('select');
        for (const value of state.protocols) protocol.append(new Option(value === 'webhook' ? 'Verified webhook' : 'Verified A2A inbox', value));
        label.append(protocol); card.append(label);
        const resetConsent = event => {
          if (event.target?.type === 'checkbox') return;
          card.querySelectorAll('input[type="checkbox"]').forEach(check => { check.checked = false; });
        };
        card.addEventListener('input', resetConsent); card.addEventListener('change', resetConsent);
        consent(card, 'I authorize only evidence metadata for this exact agent version and independently verified destination.', 'Authorize subscription', async () => {
          const rid = Number(resource.value);
          if (!Number.isSafeInteger(rid) || rid < 1 || !/^[a-z][a-z0-9_]{0,79}$/.test(destination.value) || !/^[a-z][a-z0-9_]{0,79}$/.test(audience.value)) throw Error('invalid_reference');
          return request('/subscriptions', {resource_id: rid, destination_ref: destination.value, audience: audience.value,
            protocol: protocol.value, authorized: true, notice: state.subscribe_notice});
        });
        content.append(card);
      }
      if (!state.subscriptions.length) line(content, 'No machine evidence notice subscriptions have been authorized.');
      for (const item of state.subscriptions) {
        const card = node('section'); card.className = 'card'; Object.assign(card.style, {padding: '16px', margin: '12px 0'});
        card.append(node('h3', item.id)); line(card, `State: ${item.state}.`);
        if (item.destination_ref) line(card, `Configured reference: ${item.destination_ref} · audience: ${item.audience} · ${item.protocol}.`);
        if (item.authorized_agent_version) line(card, `Authorized agent version: ${item.authorized_agent_version}. Contract scope: ${item.authorized_contract?.contract_ref || 'neutral notices only'}.`);
        if (state.can_manage && item.state === 'active' && !item.automatic_grant) {
          consent(card, 'Prepare one current evidence metadata notice. This does not send it.', 'Prepare notice', () => request('/events/prepare',
            {subscription_id: item.id, authorized: true, notice: state.prepare_notice}));
        }
        if (item.automatic_grant) line(card, `Automatic metadata grant: up to ${item.automatic_grant.max_events} notices; expires ${new Date(item.automatic_grant.expires * 1000).toLocaleString()}. Withdrawal stops future dispatch.`);
        if (state.can_manage && item.state === 'active' && !item.automatic_grant && state.automatic_dispatch) {
          consent(card, 'Authorize only changed evidence metadata for this exact subscription for one hour and at most 10 notices. This is not advertising or task execution permission.', 'Authorize bounded automatic updates', () => request('/subscriptions/automatic-grant',
            {subscription_id: item.id, ttl_seconds: 3600, max_events: 10, authorized: true, notice: state.automatic_grant_notice}));
        }
        if (state.can_manage && ['active', 'authorization_changed'].includes(item.state)) {
          consent(card, 'Withdraw this subscription independently. No future dispatch is authorized.', 'Withdraw subscription', () => request('/subscriptions/withdraw',
            {subscription_id: item.id, authorized: true, notice: state.withdraw_notice}));
        }
        content.append(card);
      }
      for (const event of state.events) {
        const card = node('section'); card.className = 'card'; Object.assign(card.style, {padding: '16px', margin: '12px 0'});
        card.append(node('h3', event.id)); line(card, `Delivery state: ${event.state}. Task completion is not asserted.`);
        if (event.agent_version) line(card, `Agent version: ${event.agent_version} · reason: ${event.reason} · quality: ${event.quality_status}.`);
        if (event.state === 'unknown') line(card, 'Delivery is uncertain. This event cannot be retried.');
        if (state.can_manage && event.state === 'prepared') {
          consent(card, 'Send this one prepared metadata notice to the exact verified destination now. Do not repeat an uncertain delivery.', 'Dispatch once', () => request('/events/dispatch',
            {event_id: event.id, authorized: true, notice: state.dispatch_notice}));
        }
        content.append(card);
      }
      const inbox = node('section'); inbox.className = 'card'; Object.assign(inbox.style, {padding: '16px', margin: '12px 0', borderRadius: '14px'});
      inbox.append(node('h3', 'Durable private receiver'));
      const configured = receiver?.receiver_enabled === true && receiver.configured_destinations > 0;
      line(inbox, configured ? 'A trusted private receiver binding is configured. Every activation requires current owner authorization.' : 'Receiver activation is unavailable. Trusted server bindings are required; this form does not configure an address, key or public endpoint.');
      line(inbox, 'A receipt confirms durable acceptance of evidence metadata only. Replay claims remain effective after restart. External ingress and actual target acceptance remain separate.');
      if (state.can_manage) {
        const destination = field(inbox, 'Receiver configured destination reference'); destination.placeholder = 'Opaque configured reference';
        const audience = field(inbox, 'Receiver configured audience reference');
        const label = node('label', 'Receiver protocol '), protocol = node('select');
        protocol.setAttribute('aria-label', 'Receiver protocol');
        protocol.append(new Option('Verified webhook', 'webhook'), new Option('Verified A2A inbox', 'a2a_inbox')); label.append(protocol); inbox.append(label);
        const ttl = field(inbox, 'Receiver activation lifetime in seconds', 'number'); ttl.min = '1'; ttl.max = '86400'; ttl.value = '3600';
        for (const input of [destination, audience, protocol, ttl]) input.disabled = !configured;
        const authorization = consent(inbox, 'Activate only the exact configured receiver reference, audience and protocol for this bounded lifetime.', 'Activate private receiver', () => {
          const seconds = Number(ttl.value);
          if (!/^[a-z][a-z0-9_]{0,79}$/.test(destination.value) || !/^[a-z][a-z0-9_]{0,79}$/.test(audience.value)
              || !Number.isSafeInteger(seconds) || seconds < 1 || seconds > 86400) throw Error('invalid_receiver_reference');
          return request('/receivers/activate', {destination_ref: destination.value, audience: audience.value, protocol: protocol.value,
            ttl_seconds: seconds, authorized: true, notice: receiver.activate_notice});
        });
        authorization.check.disabled = !configured; authorization.submit.disabled = !configured;
        const resetConsent = event => { if (event.target?.type !== 'checkbox') authorization.check.checked = false; };
        inbox.addEventListener('input', resetConsent); inbox.addEventListener('change', resetConsent);
      }
      for (const authority of receiver?.authorities || []) {
        const entry = node('div'); line(entry, `${authority.id} · ${authority.destination_ref} · ${authority.audience} · ${authority.protocol} · ${authority.state}.`);
        if (state.can_manage && ['active', 'authorization_changed', 'configuration_changed'].includes(authority.state)) {
          consent(entry, 'Revoke this exact receiver activation. Retained receipt history and replay claims remain.', 'Revoke private receiver', () =>
            request('/receivers/revoke', {receiver_id: authority.id, authorized: true, notice: receiver.revoke_notice}));
        }
        inbox.append(entry);
      }
      line(inbox, `Retained receipt records: ${Array.isArray(receiver?.receipts) ? receiver.receipts.length : 0}. A receipt does not establish task completion.`);
      content.append(inbox);
      tell('Current private machine update state loaded. Every command requires fresh consent.');
    } catch (error) { if (valid(captured)) tell('Current machine update state is unavailable. No delivery is authorized by this view.'); }
    finally { if (valid(captured)) busy = false; }
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = node('dialog'); dialog.id = 'workspaceMachineUpdatesDialog';
    Object.assign(dialog.style, {width: 'min(980px,94vw)', maxWidth: '94vw', maxHeight: '86vh', overflow: 'auto',
      borderRadius: '18px', padding: '22px', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const title = node('h2', 'Verified machine evidence updates'); title.id = 'workspaceMachineUpdatesTitle'; dialog.setAttribute('aria-labelledby', title.id);
    status = node('p'); status.setAttribute('role', 'status'); content = node('div'); content.style.overflowWrap = 'anywhere';
    dialog.append(title, button('Close machine updates', leave), button('Read current state', refresh), status, content);
    document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal(); await refresh();
  }
  window.WorkspaceMachineUpdatesAdmin = {open, leave, onSession};
})();
