import {wantsEdgeOutput,resolveEdgeOutput} from '../core/output-delivery.js';
import {pearlFlow} from '../core/pearl-flow.js';
// Individual staff membership is independent of customer organization visibility.
import {tree, createController} from './staff-workspace-source.js';
const BASE = '/admin/api/v2/staff-workspaces';
let mounted = null;
export function reset() { mounted?.(); mounted = null; }
export async function render(body, ctx) {
  reset();
  const {api, ui} = ctx, owner = api.session.token(), guard = new AbortController();
  let controller = null, writing = false, requests = 0;const graphObservers=[];
  const current = () => !guard.signal.aborted && ctx.isCurrent() && owner === api.session.token();
  const surface = ui.el('div', {class: 'adm-staff-surface'});
  const rootReason = ui.el('textarea', {rows: '2', maxlength: '300', 'aria-label': '직원 작업공간 변경 사유'});
  const reasonSection = input => ui.el('section', {class: 'adm-card'}, ui.field('변경 사유 (감사 기록)', input, {wide:true}));
  body.replaceChildren(ui.el('p', {class: 'adm-muted', text: '직원 멤버십·초안·저장본을 관리합니다. 저장과 다운로드는 에이전트를 호출하지 않으며, 실행에는 별도 동의가 필요합니다.'}), reasonSection(rootReason), surface);
  function build(value, svg = false) {
    if (typeof value === 'string') return document.createTextNode(value);
    const [tag, attributes, children] = value;
    const node = svg || tag === 'svg' ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
    for (const [key, val] of Object.entries(attributes)) {
      if(key==='style') {
        // The trusted generated template uses CSS declarations; style attributes are blocked by CSP.
        for(const declaration of String(val || '').split(';')) {
          const colon=declaration.indexOf(':');
          if(colon>0)node.style.setProperty(declaration.slice(0,colon).trim(),declaration.slice(colon+1).trim());
        }
      } else node.setAttribute((svg || tag === 'svg') && key === 'viewbox' ? 'viewBox' : key, val ?? '');
    }
    if (node.classList) for (const [old, next] of [['btn','adm-btn'],['card','adm-card'],['row','adm-filters'],['muted','adm-muted']]) if (node.classList.contains(old)) node.classList.replace(old, next);
    node.append(...children.map(child => build(child, svg || tag === 'svg')));
    return node;
  }
  surface.append(...tree.map(value => build(value)));
  surface.querySelector('#workspacePanel').classList.remove('hidden');
  // Specialist modules are already native peers; this controller owns core CRUD only.
  for (const id of ['workspaceIdentity','workspaceAdvancement','workspaceEvidence','workspaceReliability','workspaceReliabilityControls','workspaceGrowth','workspaceMachineUpdates','workspaceTypedEvidence','workspaceResearch','workspaceResearchControls','workspaceRemoteA2A','workspaceProtocolConformance','workspaceQuality','workspaceProductMount','workspaceFlowMount','workspaceReleaseMount']) {
    const node = surface.querySelector('#' + id); if (node) node.hidden = true;
  }
  const reasonFor = () => surface.querySelector('dialog[open] [data-staff-reason]') || rootReason;
  const decorate = dialog => {
    dialog.classList.add('adm-specialist-dialog');
    let input = dialog.querySelector('[data-staff-reason]');
    if (!input) { input = ui.el('textarea', {rows: '2', maxlength: '300', 'aria-label': '이번 작업 변경 사유', dataset: {staffReason: '1'}}); dialog.prepend(reasonSection(input)); }
    input.value = rootReason.value;
    if(dialog.id==='workspaceDraftDialog'){
      const source=dialog.querySelector('#workspaceDraftDefinition');
      if(source){
        let preview=dialog.querySelector('[data-pearl-preview]');
        if(!preview){preview=ui.el('div',{dataset:{pearlPreview:'1'}});source.after(preview);source.addEventListener('input',()=>decorate(dialog));}
        const paint=()=>{
          if(!current()||!dialog.open)return;
          const mark=source.value+String(source.readOnly);
          if(preview.graphMark===mark)return;preview.graphMark=mark;
          try{preview.replaceChildren(pearlFlow(ui,JSON.parse(source.value),{editable:!source.readOnly,onChange:value=>{if(!current()||source.readOnly)return;source.value=JSON.stringify(value,null,2);preview.graphMark=source.value+String(source.readOnly);source.dispatchEvent(new Event('input',{bubbles:true}));}}));}
          catch{preview.replaceChildren(ui.empty('유효한 초안 JSON을 입력하면 흐름을 표시합니다.'));}
        };
        if(!preview.graphObserver){preview.graphObserver=new MutationObserver(paint);preview.graphObserver.observe(source,{attributes:true,attributeFilter:['readonly']});graphObservers.push(preview.graphObserver);}
        paint();queueMicrotask(paint);
      }
    }
  };
  const ids = new Set(['workspaceCreateSave','workspaceMemberSave','workspaceDraftSave','workspaceArchive','workspaceSnapshotSave','workspaceSnapshotRevoke','workspaceRunPrepare','workspaceRunExecute']);
  surface.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button && (ids.has(button.id) || button.textContent.trim() === '초안 보관') && reasonFor().value.trim().length < 4) {
      event.preventDefault(); event.stopImmediatePropagation(); reasonFor().focus(); ui.toast('변경 사유를 4~300자로 입력하세요.', 'bad');
    }
  }, true);
  const transport = async (path, options = {}) => {
    const url = new URL(path, location.origin), write = options.method === 'POST';
    if (!current()) throw new api.ApiError(409, '화면 또는 세션이 변경됐습니다.');
    if (url.origin !== location.origin || !(url.pathname === BASE || url.pathname.startsWith(BASE + '/'))) throw new api.ApiError(400, '잘못된 직원 작업공간 경로입니다.');
    const reason = reasonFor().value.trim();
    if (write && (reason.length < 4 || reason.length > 300 || writing)) throw new api.ApiError(400, '변경 사유와 이전 요청 상태를 확인하세요.');
    if (write) writing = true;
    const headers = {'X-Dashboard':'1', Authorization:'Bearer ' + owner};
    if (write) Object.assign(headers, {'Content-Type':'application/json', 'X-Admin-Reason':encodeURIComponent(reason)});
    if(wantsEdgeOutput(path,write?'POST':'GET'))headers['X-Edge-Output-Transport']='v1';
    requests++; const dialog = surface.querySelector('dialog[open]');
    surface.setAttribute('aria-busy', 'true'); dialog?.setAttribute('aria-busy', 'true');
    try {
      let response = await fetch(path, {method:write ? 'POST' : 'GET', headers, cache:'no-store', credentials:'same-origin',
        signal:AbortSignal.any([guard.signal, AbortSignal.timeout(path.endsWith('/runs') && write ? 90000 : 20000), ...(options.signal ? [options.signal] : [])]),
        body:write ? options.rawWorkspaceDraft ?? JSON.stringify(options.json) : undefined});
      response=await resolveEdgeOutput(response,recovery=>fetch(recovery,{headers:{'X-Dashboard':'1',Authorization:'Bearer '+owner},cache:'no-store',credentials:'same-origin'}),()=>{if(!current())throw new api.ApiError(409,'세션이 변경되어 이전 응답을 폐기했습니다.');});
      if (!current()) throw new api.ApiError(409, '이전 응답을 폐기했습니다.');
      if (response.status === 401) { api.session.clear(); dispatchEvent(new Event('admin-session-expired')); }
      const result = response.ok && options.responseType === 'blob' ? await response.blob() : await response.json();
      if (response.headers.get('X-Admin-Audit-State') === 'pending') ui.toast('변경 결과와 별도로 감사 완료 여부를 확인하세요.', 'bad');
      if (!response.ok) throw new api.ApiError(response.status, result.detail || '요청을 확인하지 못했습니다.');
      return result;
    } finally { if (write) writing = false; requests--; surface.setAttribute('aria-busy', String(requests > 0)); dialog?.setAttribute('aria-busy', String(requests > 0)); }
  };
  mounted = () => {for(const observer of graphObservers)observer.disconnect(); guard.abort(); controller?.leave(); for (const dialog of surface.querySelectorAll('dialog')) { if (dialog.open) dialog.close(); } };
  for (const event of ['hashchange','pagehide','admin-session-expired']) addEventListener(event, reset, {signal:guard.signal});
  try {
    const options = await transport(BASE + '/options'); if (!current()) return;
    const scopedDocument = new Proxy(document, {get(target, key) { if (key === 'getElementById') return id => surface.querySelector('#' + id); const value = Reflect.get(target, key, target); return typeof value === 'function' ? value.bind(target) : value; }});
    const scopedWindow = {addEventListener() {}};
    controller = createController({document:scopedDocument, window:scopedWindow, token:owner, currentUser:options.user, state:{tab:'workspaces'}, api:transport, decorate});
    if(ctx.params.get('workspace')&&ctx.params.get('draft'))await controller.openReference(ctx.params.get('workspace'),ctx.params.get('draft'));else await controller.open();
  } catch (error) { if (current()) body.replaceChildren(ui.empty(error.message)); }
}
