/* Bounded paired-corpus research and metadata-only shadow. No activation. */
(() => {
  'use strict';
  let dialog = null, content = null, message = null, workspace = '', session = '', generation = 0, busy = false;
  let options = null, state = null, evaluation = null, selectedManifest = '';
  const identity = () => typeof token === 'string' && typeof currentUser !== 'undefined' && currentUser ? `${token}|${currentUser.user_id}|${currentUser.role}` : '';
  const make = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  const tell = text => { if (message) message.textContent = text; };
  const add = (parent, text) => parent.append(make('p', text));
  const capture = () => ({workspace, session, generation});
  const valid = c => Boolean(dialog?.open && c.workspace === workspace && c.session === session && c.generation === generation && identity() === session && document.getElementById('workspaceSelect')?.value === workspace);
  const button = (text, action) => { const node = make('button', text); node.type = 'button'; node.className = 'btn'; node.addEventListener('click', () => run(action)); return node; };
  function field(parent, name, value = '') { const label = make('label', `${name} `), input = make('input'); input.type = 'text'; input.value = value; label.append(input); parent.append(label); return input; }
  function consent(parent, text) { const label = make('label'), input = make('input'); input.type = 'checkbox'; input.checked = false; label.append(input, ' ', make('span', text)); parent.append(label); return input; }
  function card(title) { const node = make('section'); node.className = 'card'; Object.assign(node.style, {padding: '16px', margin: '14px 0', borderRadius: '14px'}); node.append(make('h3', title)); content.append(node); return node; }
  function leave() { generation++; busy = false; workspace = session = ''; if (dialog) { dialog.close(); dialog.remove(); } dialog = content = message = options = state = evaluation = null; selectedManifest = ''; }
  function onSession() { if (session && (session !== identity() || document.getElementById('workspaceSelect')?.value !== workspace)) leave(); }
  async function request(path, value, root = '/research') {
    const reply = await api(`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/reliability${root}${path}`, value === undefined ? {silent: true} : {method: 'POST', json: value, silent: true});
    if (reply?.ok !== true || typeof reply.result !== 'object') throw Error('unconfirmed');
    return reply.result;
  }
  async function run(action) { if (busy) return; const c = capture(); busy = true; try { await action(c); } catch (error) { if (valid(c)) tell([401, 403, 404].includes(error?.status) ? 'Current session or workspace access changed. Close this view.' : 'The research result could not be confirmed. Read current state before another command.'); } finally { if (valid(c)) busy = false; } }
  async function refresh(c) {
    const values = await Promise.all([request('/options'), request('/status'), request('/evaluation/status', undefined, '')]);
    if (!valid(c)) return; [options, state, evaluation] = values; render(); tell('Current research state loaded. No provider or business call was made.');
  }
  const manifestKey = value => value && /^rrm_[a-f0-9]{32}$/.test(value.id) && /^rcp_[a-f0-9]{32}$/.test(value.corpus_id) && /^[a-f0-9]{64}$/.test(value.corpus_hash) && Number.isSafeInteger(value.revision) && value.revision > 0 ? JSON.stringify([value.id, value.corpus_id, value.corpus_hash, value.revision]) : '';
  const available = value => Boolean(manifestKey(value) && !value.withdrawn && !value.restore_quarantined && Number.isFinite(value.expires) && value.expires*1000 > Date.now());
  const manifestState = value => value.withdrawn ? 'withdrawn' : value.restore_quarantined ? 'restore quarantined' : value.expires*1000 <= Date.now() ? 'expired' : 'approved corpus';
  function render() {
    content.replaceChildren();
    const summary = card('Research boundaries');
    add(summary, 'Deterministic approved-corpus goals are separate from independent factual quality. Research does not activate the worker, routing or remote cancellation.');
    add(summary, 'Repeated cases use the existing evaluation plan, current permissions, host budgets and unknown-outcome protection. Fault injection is limited to isolated fixtures.');
    if (options.can_write) {
      const setup = card('Approve paired corpus');
      const query = field(setup, 'Approved documentation search query', 'Approved public documentation'); query.maxLength = 200;
      const goal = field(setup, 'Approved normalized item SHA-256'); goal.maxLength = 64;
      add(setup, 'Provide the hash from the reviewed corpus snapshot using the exact approved item-goal profile. This form creates documentation cases with two original and two whitespace-variant trials.');
      const approve = consent(setup, 'I approve this synthetic or licensed corpus without personal data and reviewed whitespace-equivalent task variants.');
      const adaptive = consent(setup, 'Prioritize coverage within the existing host budget. This does not raise the budget or create another scheduler.');
      setup.append(button('Approve paired research manifest', async c => {
        if (!approve.checked) { tell('Select the paired corpus and semantic review authorization.'); return; }
        if (!/^[0-9a-f]{64}$/.test(goal.value)) { tell('Provide the exact approved item SHA-256.'); return; }
        const id = `rrm_${Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('')}`;
        const now = Date.now()/1000;
        const body = {manifest_id: id, version: 'owner-paired-v1', contract_id: 'docs.search.v1',
          cases: [{case_id: 'docs-1', input: {query: query.value, language: 'en', limit: 2}, expected_items: [goal.value]}],
          k: 2, mutators: ['outer-whitespace-v1'], seed: 17, reference_time: now, timezone: 'UTC', locale: 'en-US',
          dataset_version: 'owner-reviewed-v1', oracle_version: 'exact-approved-item-goal-v1',
          analysis: {version: 'owner-paired-analysis-v1', minimum_pairs: 2, grouping: 'resource-version-host-window-case-trials', unknown_policy: 'retain_in_admitted_denominator', confidence: 'conservative-wilson95-and-cluster-count'},
          expires: now+3600, adaptive_priority: adaptive.checked, authorized: true, notice: options.notice,
          data_attestation: 'synthetic_or_licensed_no_personal_data', semantic_attestation: 'reviewed_search_whitespace_preserves_task'};
        approve.checked = adaptive.checked = false;
        const result = await request('/manifests', body); if (!valid(c)) return; selectedManifest = manifestKey(result); await refresh(c); tell('Immutable research corpus approved. Configure its evaluation plan separately.');
      }));
      const plan = card('Approve existing evaluation plan');
      const manifestLabel = make('label', 'Approved research manifest '), manifestSelect = make('select');
      manifestSelect.id = 'researchManifestSelect';
      const placeholder = make('option', 'Select an approved, unexpired manifest'); placeholder.value = ''; manifestSelect.append(placeholder);
      for (const manifest of state.manifests) {
        const key = manifestKey(manifest); if (!key) continue;
        const option = make('option', `${manifest.id} · revision ${manifest.revision} · ${manifestState(manifest)}`); option.value = key; option.disabled = !available(manifest); manifestSelect.append(option);
      }
      if (!state.manifests.some(item => available(item) && manifestKey(item) === selectedManifest)) selectedManifest = '';
      manifestSelect.value = selectedManifest; manifestLabel.append(manifestSelect); plan.append(manifestLabel);
      const selectedDetails = make('p'); selectedDetails.id = 'researchManifestSelection'; plan.append(selectedDetails);
      const describeSelection = () => {
        const manifest = state.manifests.find(item => available(item) && manifestKey(item) === selectedManifest);
        selectedDetails.textContent = manifest ? `Selected ${manifest.id}; corpus ${manifest.corpus_id}; SHA-256 ${manifest.corpus_hash}; revision ${manifest.revision}; expires ${new Date(manifest.expires*1000).toISOString()}.` : 'Select a current manifest. Selection grants no evaluation or worker authority.';
      };
      describeSelection();
      const rid = field(plan, 'Evaluation resource reference', '1');
      const approved = consent(plan, 'Authorize this research corpus and resource with four evaluation reservations per host every ten minutes, jitter and a one-hour expiry.');
      manifestSelect.addEventListener('change', () => { selectedManifest = manifestSelect.value; approved.checked = false; describeSelection(); });
      rid.addEventListener('input', () => { approved.checked = false; });
      plan.append(button('Save research evaluation plan', async c => {
        const manifest = state.manifests.find(item => available(item) && manifestKey(item) === selectedManifest);
        if (!manifest || !approved.checked) { approved.checked = false; tell('Approve a paired corpus and select its exact evaluation plan authorization.'); return; }
        const resource = Number(rid.value); if (!Number.isSafeInteger(resource) || resource < 1 || resource >= 2147483648) { tell('Provide one valid resource reference.'); return; }
        approved.checked = false;
        await request('/evaluation/plans', {revision: evaluation.plan?.revision || 0, corpus_id: manifest.corpus_id,
          resource_ids: [resource], interval_seconds: 600, jitter_seconds: 10, per_host_budget: 4,
          expires: Date.now()/1000+3600, authorized: true, notice: 'approved-read-evaluation-corpus-v1'}, '');
        if (valid(c)) { await refresh(c); tell('Research plan approved. Evaluation control and worker activation remain separate.'); }
      }));
    }
    const history = card('Paired manifests');
    if (!state.manifests.length) add(history, 'No approved research manifests.');
    for (const manifest of state.manifests) {
      const row = make('div'); add(row, `${manifest.version} · ${manifest.planned_episodes} planned episodes · ${manifestState(manifest)} · independent quality unassessed`);
      if (options.can_write && available(manifest)) {
        const analysis = button('Read paired analysis', async c => {
          const result = await request(`/manifests/${encodeURIComponent(manifest.id)}/analyze`); if (!valid(c)) return;
          output.replaceChildren(); add(output, `Scheduled ${result.scheduled_episodes}; expected ${result.expected_episodes}; unscheduled ${result.unscheduled_episodes}.`);
          add(output, `Paired trials ${result.paired.admitted_pairs}; both goal-pass ${result.paired.both_goal_pass}; both failed ${result.paired.both_failed}; MR violations ${result.paired.mr_violation}; unknown ${result.paired.unknown}; unassessable ${result.paired.unassessable}; missing ${result.paired.missing}.`);
          for (const cell of result.cells) add(output, `${cell.mutator} · all-${cell.k}-pass ${cell.all_k_pass}/${cell.admitted_groups}; unknown ${cell.unknown_episodes}; missing episodes ${cell.missing_episodes}; host/window clusters ${cell.independent_host_window_clusters}.`);
          add(output, 'Intervention promotion remains pending paired evidence. Counterfactual analysis does not prove live savings or independent quality.');
        });
        analysis.disabled = evaluation.control.enabled !== true || evaluation.plan?.corpus_id !== manifest.corpus_id;
        row.append(analysis);
        if (analysis.disabled) add(row, 'Approve the matching evaluation plan and enable evaluation reservations in Reliability controls before analysis. Worker activation remains separate.');
        const withdrawn = consent(row, 'Withdraw this exact manifest and block further research use and new evaluation dispatch.');
        row.append(button('Withdraw research manifest', async c => {
          if (!withdrawn.checked) { tell('Select the exact research withdrawal authorization.'); return; }
          withdrawn.checked = false; await request(`/manifests/${encodeURIComponent(manifest.id)}/withdraw`, {revision: manifest.revision, authorized: true, notice: options.notice});
          if (valid(c)) await refresh(c);
        }));
        if (options.lineage_configured) {
          const flow = field(row, 'Retained typed flow reference'), runId = field(row, 'Retained typed run reference');
          const observed = consent(row, 'Review current purpose-authorized typed metadata in shadow only. No call or interruption is authorized.');
          row.append(button('Review metadata shadow', async c => {
            if (!observed.checked) { tell('Select the metadata-only shadow authorization.'); return; }
            observed.checked = false;
            const result = await request(`/manifests/${encodeURIComponent(manifest.id)}/shadow`, {flow_id: flow.value, run_id: runId.value, stagnation_actions: 3, authorized: true, notice: options.notice});
            if (!valid(c)) return; output.replaceChildren(); add(output, `Observed events ${result.raw_event_count}; closed actions ${result.closed_action_count}; would-stop ${result.would_stop ? 'flagged' : 'not flagged'}; actual interventions ${result.actual_interventions}.`);
            add(output, 'Remote cancellation and actual savings are unconfirmed. No hidden reasoning or raw output was requested.');
          }));
        }
      }
      history.append(row);
    }
    const output = make('div'); output.setAttribute('role', 'region'); output.setAttribute('aria-label', 'Research analysis result'); history.append(output);
  }
  async function open(ws) {
    leave(); if (typeof ws !== 'string' || !/^ws_[0-9a-f]{32}$/.test(ws) || !identity()) return;
    workspace = ws; session = identity(); dialog = make('dialog'); dialog.id = 'workspaceReliabilityResearchDialog';
    Object.assign(dialog.style, {width: 'min(1000px,94vw)', maxHeight: '86vh', borderRadius: '18px', padding: '22px', overflow: 'auto', color: 'var(--text,#172235)', background: 'var(--card,#fff)', border: '1px solid var(--border,#dce3ee)'});
    const title = make('h2', 'Paired reliability research'); title.id = 'workspaceReliabilityResearchTitle'; dialog.setAttribute('aria-labelledby', title.id);
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key, value] of Object.entries({viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'aria-hidden': 'true'})) icon.setAttribute(key, value);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M9 3h6m-5 0v7l-6 9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2l-6-9V3M8 15h8'); icon.append(path); title.prepend(icon, ' ');
    message = make('p', 'Revalidating current research scope.'); message.setAttribute('role', 'status'); content = make('div'); content.style.overflowWrap = 'anywhere';
    const close = make('button', 'Close research'); close.type = 'button'; close.addEventListener('click', leave);
    dialog.append(title, close, button('Read current research', refresh), message, content); document.body.append(dialog); dialog.addEventListener('cancel', leave); dialog.showModal();
    await run(refresh);
  }
  window.WorkspaceReliabilityResearchAdmin = {open, leave, onSession};
})();
