// Resolve a currently accessible immutable version before opening its release controls.
export function createSelector(deps, kind) {
  const {api, scopeIdentity, isCurrent} = deps;
  let dialog = null, child = null, sequence = 0;
  const el = (tag, text) => { const n = document.createElement(tag); if (text) n.textContent = text; return n; };
  function leave() { sequence++; child?.leave(); child = null; dialog?.close(); dialog?.remove(); dialog = null; }
  async function open(ws) {
    leave(); const mark = sequence, owner = scopeIdentity();
    const valid = () => mark === sequence && isCurrent() && owner && owner === scopeIdentity();
    const base = '/admin/api/workflow-workspaces/' + ws;
    dialog = el('dialog'); dialog.className = 'adm-specialist-dialog';
    const title = el('h2', kind === 'release' ? '저장본 릴리스 선택' : '다단계 워크플로 릴리스 선택');
    title.id = 'releaseSelectorTitle'; dialog.setAttribute('aria-labelledby', title.id);
    const status = el('p', '접근 가능한 대상을 조회하고 있습니다.'); status.setAttribute('role', 'status');
    const select = el('select'); select.setAttribute('aria-label', '릴리스 대상');
    const versions = el('select'); versions.setAttribute('aria-label', '활성 저장본'); versions.hidden = kind !== 'release';
    const next = el('button', '선택한 버전의 배포 관리'); next.type = 'button'; next.className = 'adm-btn primary'; next.disabled = true;
    const close = el('button', '닫기'); close.type = 'button'; close.className = 'adm-btn'; close.onclick = leave;
    dialog.append(title, el('p', '현재 활성 버전과 보관된 성공 테스트를 확인합니다. 이 선택만으로 배포 권한이 발급되거나 에이전트가 실행되지 않습니다.'), select, versions, next, close, status);
    dialog.addEventListener('cancel', e => {e.preventDefault(); leave();});
    document.body.append(dialog); dialog.showModal();
    let rows = [], revision = 0;
    const changed = async () => {
      const read = ++revision; next.disabled = true; versions.replaceChildren();
      if (!select.value) return;
      try {
        if (kind === 'release') {
          const result = await api(base + '/drafts/' + select.value + '/snapshots');
          if (!valid() || read !== revision) return;
          for (const row of result.snapshots.filter(row => row.active)) versions.add(new Option('저장본 ' + row.ordinal + ' · 버전 ' + row.draft_revision, row.id));
          next.disabled = !versions.value;
        } else next.disabled = !rows.find(row => row.id === select.value)?.version_id;
        status.textContent = next.disabled ? '배포할 활성 버전이 없습니다.' : '배포 관리에서 현재 소유자 권한을 다시 확인합니다.';
      } catch (error) { if (valid() && read === revision) status.textContent = error.message; }
    };
    select.onchange = changed;
    next.onclick = async () => {
      if (next.disabled || !valid()) return;
      next.disabled = true;
      try {
        const module = await import('./panel-' + kind + '.js');
        if (!valid()) return;
        const selected = select.value, version = versions.value;
        child = module.createPanel(deps); dialog.close(); dialog.remove(); dialog = null;
        if (kind === 'release') await child.open({workspace_id: ws, draft_id: selected, snapshot_id: version, can_manage: true});
        else await child.open(ws, selected, rows.find(row => row.id === selected).version_id);
      } catch (error) { if (valid() && dialog) { status.textContent = error.message; next.disabled = false; } }
    };
    try {
      const result = await api(base + (kind === 'release' ? '/drafts' : '/typed-flows'));
      if (!valid()) return;
      rows = (kind === 'release' ? result.drafts : result.flows).filter(row => row.active !== false && row.active !== 0);
      select.replaceChildren(new Option('대상 선택', ''), ...rows.map(row => new Option(row.name || row.title || row.id, row.id)));
      status.textContent = rows.length ? '배포할 대상을 선택하세요.' : '현재 접근 가능한 대상이 없습니다. 먼저 워크플로를 저장하고 성공 테스트를 보관하세요.';
    } catch (error) { if (valid()) status.textContent = error.message; }
  }
  return {open, leave};
}
