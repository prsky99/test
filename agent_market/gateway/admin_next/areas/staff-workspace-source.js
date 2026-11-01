// Generated from the staff workspace controller and trusted static markup; do not edit.
export const tree=["  ",["section",{"id":"workspacePanel","data-panel":"workspaces","class":"hidden"},["\n    ",["div",{"class":"card"},["\n      ",["div",{"class":"row","style":"justify-content:space-between;gap:12px;flex-wrap:wrap"},["\n        ",["div",{},[["h2",{"style":"display:flex;align-items:center;gap:8px;margin:0"},[["svg",{"class":"lucide lucide-building-2","aria-hidden":"true","focusable":"false","width":"22","height":"22","viewbox":"0 0 24 24","fill":"none","stroke":"currentColor","stroke-width":"2","stroke-linecap":"round","stroke-linejoin":"round"},[["path",{"d":"M6 22V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v19M6 12H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1h-3M10 6h4M10 10h4M10 14h4M10 18h4"},[]]]],"조직 작업공간"]],["p",{"class":"muted"},["조직 구성원에게만 공개되는 초안과 변경할 수 없는 저장본을 관리합니다. 지원되는 읽기 전용 MCP 저장본은 별도 승인 후 한 번 실행할 수 있으며 배포·공개 권한은 제공하지 않습니다."]]]],"\n        ",["div",{"class":"row"},[["button",{"class":"btn","id":"workspaceRefresh","type":"button"},["목록 새로고침"]],["button",{"class":"btn primary","id":"workspaceCreate","type":"button","hidden":null},["작업공간 만들기"]]]],"\n      "]],"\n      ",["p",{"id":"workspaceStatus","role":"status","aria-live":"polite","class":"muted"},["개별 관리자 계정으로 로그인해 주세요."]],"\n      ",["label",{"for":"workspaceSelect"},["내 작업공간"]],["select",{"id":"workspaceSelect","style":"min-width:220px;max-width:100%","disabled":null},[["option",{"value":""},["작업공간 선택"]]]],"\n      ",["div",{"id":"workspaceContent","hidden":null},["\n        ",["p",{"id":"workspaceSummary","class":"muted"},[]],"\n        ",["div",{"id":"workspaceProductMount","style":"margin:10px 0"},[]],"\n        ",["div",{"id":"workspaceFlowMount","style":"margin:10px 0"},[]],"\n        ",["div",{"class":"row","style":"gap:8px;flex-wrap:wrap"},[["button",{"class":"btn primary","id":"workspaceDraftCreate","type":"button","disabled":null},["비공개 초안 만들기"]],["button",{"class":"btn","id":"workspaceMembers","type":"button","disabled":null},["구성원 관리"]],["button",{"class":"btn","id":"workspaceIdentity","type":"button","disabled":null},["고객 접근·제공자 인증"]],["button",{"class":"btn","id":"workspaceAdvancement","type":"button","disabled":null},["지원·모의 원장·준비 점검"]],["button",{"class":"btn","id":"workspaceEvidence","type":"button","disabled":null},["Current evidence"]],["button",{"class":"btn","id":"workspaceReliability","type":"button","disabled":null},["Reliability evidence"]],["button",{"class":"btn","id":"workspaceReliabilityControls","type":"button","disabled":null},["Evaluation and routing"]],["button",{"class":"btn","id":"workspaceGrowth","type":"button","disabled":null},["App factory and SDK"]],["button",{"class":"btn","id":"workspaceMachineUpdates","type":"button","disabled":null},["Verified machine updates"]],["button",{"class":"btn","id":"workspaceTypedEvidence","type":"button","disabled":null},["Typed execution evidence"]],["button",{"class":"btn","id":"workspaceResearch","type":"button","disabled":null},["Reliability research"]],["button",{"class":"btn","id":"workspaceResearchControls","type":"button","disabled":null},["Reviewed plans and routing pilot"]],["button",{"class":"btn","id":"workspaceRemoteA2A","type":"button","disabled":null},["Remote A2A tasks"]]," ",["button",{"class":"btn","id":"workspaceProtocolConformance","type":"button","disabled":null},["Protocol conformance"]],["button",{"class":"btn","id":"workspaceQuality","type":"button","disabled":null},["품질 검토·사전 할당"]],["button",{"class":"btn","id":"workspaceArchive","type":"button","disabled":null},["작업공간 보관"]]]],"\n        ",["div",{"id":"workspaceDraftList","style":"display:grid;gap:10px;margin-top:16px"},[]],"\n      "]],"\n    "]],"\n  "]],"\n  ",["dialog",{"id":"workspaceCreateDialog","aria-labelledby":"workspaceCreateTitle","style":"width:min(560px,94vw);max-height:85vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--text);padding:24px"},["\n    ",["div",{"class":"row","style":"justify-content:space-between"},[["h2",{"id":"workspaceCreateTitle"},["작업공간 만들기"]],["button",{"class":"btn","id":"workspaceCreateClose","type":"button"},["닫기"]]]],"\n    ",["p",{"class":"muted"},["기존 관리자 계정을 소유자로 지정합니다. 최고관리자도 구성원이 아니면 비공개 내용에 접근할 수 없습니다."]],"\n    ",["label",{"for":"workspaceName"},["이름"]],["input",{"id":"workspaceName","maxlength":"120","style":"width:100%"},[]],"\n    ",["label",{"for":"workspaceOwner"},["소유자 관리자 ID"]],["input",{"id":"workspaceOwner","type":"number","min":"1","step":"1","style":"width:100%"},[]],"\n    ",["p",{"id":"workspaceCreateStatus","role":"status","aria-live":"polite"},[]],["button",{"id":"workspaceCreateSave","class":"btn primary","type":"button"},["작업공간 생성"]],"\n  "]],"\n  ",["dialog",{"id":"workspaceMemberDialog","aria-labelledby":"workspaceMemberTitle","style":"width:min(760px,94vw);max-height:85vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--text);padding:24px"},["\n    ",["div",{"class":"row","style":"justify-content:space-between"},[["h2",{"id":"workspaceMemberTitle"},["구성원 관리"]],["button",{"class":"btn","id":"workspaceMemberClose","type":"button"},["닫기"]]]],"\n    ",["p",{"class":"muted"},["기존 관리자 계정의 조직 역할을 지정합니다. 운영자 계정은 조직 역할과 관계없이 읽기만 가능합니다."]],["div",{"id":"workspaceMemberList"},[]],"\n    ",["label",{"for":"workspaceMemberUser"},["관리자 ID"]],["input",{"id":"workspaceMemberUser","type":"number","min":"1","step":"1"},[]],"\n    ",["label",{"for":"workspaceMemberRole"},["조직 역할"]],["select",{"id":"workspaceMemberRole"},[["option",{"value":"viewer"},["조회자"]],["option",{"value":"editor"},["편집자"]],["option",{"value":"owner"},["소유자"]]]],"\n    ",["label",{},[["input",{"id":"workspaceMemberActive","type":"checkbox","checked":null},[]]," 활성 구성원"]],"\n    ",["p",{"id":"workspaceMemberStatus","role":"status","aria-live":"polite"},[]],["button",{"id":"workspaceMemberSave","class":"btn primary","type":"button"},["구성원 저장"]],"\n  "]],"\n  ",["dialog",{"id":"workspaceDraftDialog","aria-labelledby":"workspaceDraftTitle","style":"width:min(820px,94vw);max-height:85vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--text);padding:24px"},["\n    ",["div",{"class":"row","style":"justify-content:space-between"},[["h2",{"id":"workspaceDraftTitle"},["비공개 초안"]],["button",{"class":"btn","id":"workspaceDraftClose","type":"button"},["닫기"]]]],"\n    ",["p",{"class":"muted"},["이 JSON은 비공개 설계 자료입니다. 저장해도 에이전트를 호출하거나 실행·배포·공개하지 않습니다."]],"\n    ",["label",{"for":"workspaceDraftName"},["이름"]],["input",{"id":"workspaceDraftName","maxlength":"120","style":"width:100%"},[]],"\n    ",["label",{"for":"workspaceDraftDescription"},["설명"]],["textarea",{"id":"workspaceDraftDescription","maxlength":"1000","rows":"3","style":"width:100%"},[]],"\n    ",["label",{"for":"workspaceDraftDefinition"},["초안 JSON (nodes, edges)"]],["textarea",{"id":"workspaceDraftDefinition","rows":"14","spellcheck":"false","style":"width:100%;font-family:monospace"},[]],"\n    ",["p",{"id":"workspaceDraftStatus","role":"status","aria-live":"polite"},[]],["button",{"id":"workspaceDraftSave","class":"btn primary","type":"button"},["초안 저장"]],"\n  "]],"\n  ",["dialog",{"id":"workspaceSnapshotDialog","aria-labelledby":"workspaceSnapshotTitle","style":"width:min(880px,94vw);max-height:85vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--text);padding:24px"},["\n    ",["div",{"class":"row","style":"justify-content:space-between;position:sticky;top:0;background:var(--bg);z-index:1;padding-bottom:8px"},[["h2",{"id":"workspaceSnapshotTitle"},["비공개 저장본"]],["button",{"class":"btn","id":"workspaceSnapshotClose","type":"button"},["닫기"]]]],"\n    ",["p",{"class":"muted"},["저장 시점의 초안을 그대로 보존합니다. JSON 자료이며 실행 가능한 웹앱이나 공개 권한이 아닙니다."]],"\n    ",["button",{"id":"workspaceSnapshotSave","class":"btn primary","type":"button","disabled":null},["현재 초안의 저장본 만들기"]],"\n    ",["p",{"id":"workspaceSnapshotStatus","role":"status","aria-live":"polite"},[]],["div",{"id":"workspaceSnapshotList","style":"display:grid;gap:8px"},[]],"\n    ",["pre",{"id":"workspaceSnapshotPreview","style":"white-space:pre-wrap;overflow-wrap:anywhere;max-height:38vh;overflow:auto","hidden":null},[]],"\n    ",["div",{"class":"row","style":"gap:8px"},[["button",{"id":"workspaceSnapshotDownload","class":"btn","type":"button","disabled":null},["JSON 다운로드"]],["button",{"id":"workspaceSnapshotRevoke","class":"btn","type":"button","disabled":null},["저장본 철회"]]]],"\n    ",["div",{"id":"workspaceReleaseMount","style":"margin-top:12px"},[]],"\n    ",["section",{"id":"workspaceRunSection","hidden":null,"style":"margin-top:20px;padding-top:16px;border-top:1px solid var(--line)"},["\n      ",["h3",{"style":"display:flex;align-items:center;gap:8px"},[["svg",{"class":"lucide lucide-play","aria-hidden":"true","focusable":"false","width":"18","height":"18","viewbox":"0 0 24 24","fill":"none","stroke":"currentColor","stroke-width":"2","stroke-linecap":"round","stroke-linejoin":"round"},[["path",{"d":"m6 3 14 9-14 9V3Z"},[]]]],"별도 승인한 비공개 실행"]],"\n      ",["p",{"class":"muted"},["수동 시작 노드와 읽기 전용 MCP 도구 하나만 지원합니다. 준비 단계에서는 에이전트를 호출하지 않습니다. 비공개는 조직별 접근 제한을 의미하며, 실행 시 검토한 입력은 선택한 외부 에이전트로 전송됩니다."]],"\n      ",["div",{"class":"row","style":"gap:8px;flex-wrap:wrap"},[["button",{"id":"workspaceRunPrepare","type":"button","class":"btn","disabled":null},["비공개 실행 준비"]],["button",{"id":"workspaceRunHistoryRefresh","type":"button","class":"btn","disabled":null},["실행 이력 확인"]],["button",{"id":"workspaceRunRefresh","type":"button","class":"btn","disabled":null},["실행 상태 확인"]]]],"\n      ",["p",{"id":"workspaceRunStatus","role":"status","aria-live":"polite","class":"muted"},[]],"\n      ",["pre",{"id":"workspaceRunPreview","hidden":null,"style":"white-space:pre-wrap;overflow-wrap:anywhere;max-height:28vh;overflow:auto"},[]],"\n      ",["label",{"style":"display:block;margin:12px 0"},[["input",{"id":"workspaceRunAuthority","type":"checkbox","disabled":null},[]]," 검토한 입력을 선택한 외부 에이전트에 전송하고 이 저장본의 비공개 실행을 한 번 수행하는 데 동의합니다."]],"\n      ",["button",{"id":"workspaceRunExecute","type":"button","class":"btn primary","disabled":null},["Run privately"]],"\n      ",["p",{"id":"workspaceRunOutputLabel","class":"muted","hidden":null},["에이전트 출력 (검증되지 않은 내용)"]],["pre",{"id":"workspaceRunOutput","hidden":null,"style":"white-space:pre-wrap;overflow-wrap:anywhere;max-height:32vh;overflow:auto"},[]],"\n      ",["div",{"id":"workspaceRunHistory","style":"display:grid;gap:8px;margin-top:12px"},[]],"\n    "]],"\n  "]]];
export function createController({document,window,token,currentUser,state,api,decorate}) {
/* Private, non-executable workspace drafts use individual administrator sessions. */
(() => {
  'use strict';
  const BASE = '/admin/api/v2/staff-workspaces';
  const PROFILE = 'workspace-private-snapshots-v1';
  const RUN_PROFILE = 'workspace-private-mcp-run-v1', RUN_NOTICE = 'workspace-private-run-v1';
  const $w = id => document.getElementById(id);
  const roles = {owner:'소유자',editor:'편집자',viewer:'조회자'};
  const dialogs = ['workspaceCreateDialog','workspaceMemberDialog','workspaceDraftDialog','workspaceSnapshotDialog'];
  let epoch=0, session='', options=null, workspace=null, draft=null, snapshot=null, memberRevision=0, memberId=null, busy=false, downloadUrl='';
  let modalEpoch=0, selectedSnapshotEpoch=0;
  let runEpoch=0, runOptions=null, runPlan=null, runBusy=false, runUncertain=false, currentRun=null, runExpiryTimer=null;
  const runControllers=new Set();

  function identity(user) {return user && typeof token==='string' ? `${token}|${user.user_id}|${user.role}` : '';}
  function text(id,value) {$w(id).textContent=value;}
  function releaseUrl() {if(downloadUrl){URL.revokeObjectURL(downloadUrl);downloadUrl='';}}
  function closeDialogs() {
    window.WorkspaceReleaseAdmin?.select(null);
    clearPrivateRun();
    modalEpoch++; selectedSnapshotEpoch++; releaseUrl();
    for(const id of dialogs){const el=$w(id);if(el.open)el.close();}
    for(const id of ['workspaceName','workspaceOwner','workspaceMemberUser','workspaceDraftName','workspaceDraftDescription','workspaceDraftDefinition'])$w(id).value='';
    for(const id of ['workspaceCreateStatus','workspaceMemberStatus','workspaceDraftStatus','workspaceSnapshotStatus','workspaceSnapshotPreview'])text(id,'');
    $w('workspaceMemberList').replaceChildren();$w('workspaceSnapshotList').replaceChildren();$w('workspaceSnapshotPreview').hidden=true;
    draft=null;snapshot=null;memberRevision=0;memberId=null;busy=false;updateControls();
  }
  function clear(message='개별 관리자 계정으로 로그인해 주세요.') {
    window.WorkspaceIdentityAdmin?.leave();window.AdvancementAdmin?.leave();window.WorkspaceAgreementAdmin?.leave();window.WorkspaceEvidenceAdmin?.leave();window.WorkspaceReliabilityAdmin?.leave();window.WorkspaceReliabilityControlsAdmin?.leave();window.WorkspaceGrowthAdmin?.leave();window.WorkspaceMachineUpdatesAdmin?.leave();window.WorkspaceTypedEvidenceAdmin?.leave();window.WorkspaceReliabilityResearchAdmin?.leave();window.WorkspaceResearchControlsAdmin?.leave();window.WorkspaceRemoteA2AAdmin?.leave();window.WorkspaceProtocolConformanceAdmin?.leave();window.WorkspaceTypedReleaseAdmin?.leave();window.WorkflowQualityReviewAdmin?.leave();window.WorkspaceProductAdmin?.clear();window.WorkspaceFlowAdmin?.select(null,false);
    epoch++;closeDialogs();options=null;workspace=null;session='';
    $w('workspaceSelect').replaceChildren(new Option('작업공간 선택',''));$w('workspaceSelect').disabled=true;
    $w('workspaceContent').hidden=true;$w('workspaceDraftList').replaceChildren();text('workspaceSummary','');
    $w('workspaceCreate').hidden=true;text('workspaceStatus',message);updateControls();
  }
  function leave(){clear('작업공간 목록을 새로 불러오세요.');}
  function onSession(user){if(identity(user)!==session)clear(user?'작업공간 목록을 새로 불러오세요.':undefined);}
  function stamp(extra={}) {return {epoch,modalEpoch,session:identity(currentUser),workspaceId:workspace?.id,...extra};}
  function valid(mark,modal=false) {
    return mark.epoch===epoch && mark.session===identity(currentUser) && mark.session===session && state.tab==='workspaces' && (!mark.workspaceId || mark.workspaceId===workspace?.id) && (!modal || mark.modalEpoch===modalEpoch);
  }
  function available(){return options?.profile===PROFILE && identity(currentUser)===session && state.tab==='workspaces';}
  function canEdit(){return available() && workspace?.active && workspace.can_edit===true && currentUser?.role!=='operator';}
  function canManage(){return canEdit() && workspace.can_manage===true;}
  function updateControls(){
    for(const id of ['workspaceName','workspaceOwner','workspaceMemberUser','workspaceMemberRole','workspaceMemberActive'])$w(id).disabled=busy;
    $w('workspaceCreateSave').disabled=busy || !available() || options?.can_provision!==true;
    $w('workspaceDraftCreate').disabled=busy || !canEdit();$w('workspaceMembers').disabled=busy || !canManage();$w('workspaceArchive').disabled=busy || !canManage();
    if($w('workspaceIdentity'))$w('workspaceIdentity').disabled=busy || !canManage();
    if($w('workspaceAdvancement'))$w('workspaceAdvancement').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceEvidence'))$w('workspaceEvidence').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceReliability'))$w('workspaceReliability').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceReliabilityControls'))$w('workspaceReliabilityControls').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceGrowth'))$w('workspaceGrowth').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceMachineUpdates'))$w('workspaceMachineUpdates').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceTypedEvidence'))$w('workspaceTypedEvidence').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceResearch'))$w('workspaceResearch').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceResearchControls'))$w('workspaceResearchControls').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceRemoteA2A'))$w('workspaceRemoteA2A').disabled=busy || !available() || !workspace?.active;
    if($w('workspaceProtocolConformance'))$w('workspaceProtocolConformance').disabled=busy || !available() || !workspace?.active;

    if($w('workspaceQuality'))$w('workspaceQuality').disabled=busy || !available() || !workspace?.active;
    $w('workspaceMemberSave').disabled=busy || !canManage();$w('workspaceDraftSave').disabled=busy || !canEdit() || (draft && !draft.active);
    for(const id of ['workspaceDraftName','workspaceDraftDescription','workspaceDraftDefinition'])$w(id).readOnly=busy || !canEdit() || (draft && !draft.active);
    $w('workspaceSnapshotSave').disabled=busy || !canEdit() || !draft?.active;
    $w('workspaceSnapshotDownload').disabled=busy || !available() || !snapshot?.active;
    $w('workspaceSnapshotRevoke').disabled=busy || !canManage() || !snapshot?.active;
    updateRunControls();
  }
  function checkEnvelope(value){if(!value || value.profile!==PROFILE || value.ok!==true)throw new Error('workspace_profile');return value;}
  async function request(path,opts={}){return checkEnvelope(await api(BASE+path,{...opts,silent:true}));}
  function problem(error,id='workspaceStatus'){
    if(error.status===404 || error.status===401 || error.status===403 || !token || !currentUser){clear('권한 또는 세션이 변경되었습니다. 목록을 새로 불러오세요.');return;}
    text(id,error.status===409?'버전이 변경되었거나 저장 결과를 확인할 수 없습니다. 자동 재시도하지 않고 목록을 새로 불러오세요.':'요청을 완료하지 못했습니다. 입력과 현재 권한을 확인한 뒤 목록을 새로 불러오세요.');
  }
  function show(id){closeDialogs();decorate($w(id));$w(id).showModal();updateControls();}
  function button(label,action,disabled=false){const el=document.createElement('button');el.type='button';el.className='adm-btn';el.textContent=label;el.disabled=disabled;el.addEventListener('click',action);return el;}
  function card(){const el=document.createElement('div');el.className='adm-card';el.style.padding='12px';return el;}
  function paragraph(value){const el=document.createElement('p');el.textContent=value;return el;}
  function finiteTree(value,depth=0,budget={n:0}){
    if(++budget.n>2000 || depth>12)throw new Error('bounded_json');
    if(typeof value==='number' && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))))throw new Error('finite_json');
    if(value && typeof value==='object')for(const child of Object.values(value))finiteTree(child,depth+1,budget);
  }

  async function open(){
    clear('작업공간 목록을 불러오는 중입니다.');session=identity(currentUser);if(!session)return false;
    const mark=stamp();
    try{
      const result=await request('/options');if(!valid(mark))return false;options=result;
      const list=await request('');if(!valid(mark))return false;
      const select=$w('workspaceSelect');select.replaceChildren(new Option('작업공간 선택',''));
      for(const item of list.workspaces){const option=new Option(`${item.name} · ${roles[item.role] || '구성원'}${item.active?'':' · 보관됨'}`,item.id);select.add(option);}
      select.disabled=!list.workspaces.length;$w('workspaceCreate').hidden=result.can_provision!==true;
      text('workspaceStatus',list.workspaces.length?'구성원으로 등록된 작업공간만 표시합니다.':'등록된 작업공간이 없습니다. 소유자에게 구성원 등록을 요청하거나 작업공간을 만드세요.');updateControls();
      return true;
    }catch(error){if(valid(mark)){if(error.status===404 || error.message==='workspace_profile')clear('현재 서버에서는 조직 작업공간을 사용할 수 없습니다.');else problem(error);}}
    return false;
  }
  async function selectWorkspace(){
    window.WorkspaceAgreementAdmin?.leave();window.WorkspaceEvidenceAdmin?.leave();window.WorkspaceReliabilityAdmin?.leave();window.WorkspaceReliabilityControlsAdmin?.leave();window.WorkspaceGrowthAdmin?.leave();window.WorkspaceMachineUpdatesAdmin?.leave();window.WorkspaceTypedEvidenceAdmin?.leave();window.WorkspaceReliabilityResearchAdmin?.leave();window.WorkspaceResearchControlsAdmin?.leave();window.WorkspaceRemoteA2AAdmin?.leave();window.WorkspaceProtocolConformanceAdmin?.leave();window.WorkspaceTypedReleaseAdmin?.leave();
    window.WorkspaceProductAdmin?.clear();
    window.WorkspaceFlowAdmin?.select(null,false);
    epoch++;closeDialogs();workspace=null;$w('workspaceDraftList').replaceChildren();$w('workspaceContent').hidden=true;updateControls();
    const id=$w('workspaceSelect').value;if(!id)return;
    const mark=stamp();
    try{
      const result=await request('/'+encodeURIComponent(id));if(!valid(mark) || $w('workspaceSelect').value!==id)return;workspace=result.workspace;
      $w('workspaceContent').hidden=false;text('workspaceSummary',`${workspace.name} · ${roles[workspace.role] || '구성원'} · 버전 ${workspace.revision}${workspace.active?'':' · 보관됨'}`);text('workspaceStatus','비공개 설계 자료를 관리합니다. 저장만으로 에이전트를 호출하지 않습니다.');updateControls();
      window.WorkspaceProductAdmin?.select({workspace_id:workspace.id,can_edit:canEdit()});window.WorkspaceFlowAdmin?.select(workspace.id,canEdit());await loadDrafts();
    }catch(error){if(valid(mark))problem(error);}
  }
  async function loadDrafts(){
    const mark=stamp();if(!workspace)return;
    try{const result=await request('/'+workspace.id+'/drafts');if(!valid(mark))return;
      const host=$w('workspaceDraftList');host.replaceChildren();
      for(const item of result.drafts){const row=card();row.append(paragraph(`${item.name} · 버전 ${item.revision}${item.active?'':' · 보관됨'}`));if(item.description)row.append(paragraph(item.description));
        const actions=document.createElement('div');actions.className='adm-filters';actions.style.gap='8px';
        actions.append(button(canEdit()&&item.active?'초안 편집':'초안 보기',()=>editDraft(item.id)),button('저장본 보기',()=>openSnapshots(item.id)));
        if(canManage()&&item.active)actions.append(button('초안 보관',()=>archiveDraft(item)));
        row.append(actions);host.append(row);
      }
      if(!result.drafts.length)host.append(paragraph('저장된 비공개 초안이 없습니다.'));
    }catch(error){if(valid(mark))problem(error);}
  }
  async function provision(){
    if(busy || !available() || !options.can_provision)return;
    const name=$w('workspaceName').value,owner=Number($w('workspaceOwner').value);if(!name.trim() || !Number.isSafeInteger(owner)||owner<1){text('workspaceCreateStatus','이름과 기존 관리자 ID를 확인해 주세요.');return;}
    const mark=stamp();busy=true;updateControls();
    try{await request('',{method:'POST',json:{name,owner_id:owner}});if(!valid(mark,true))return;closeDialogs();await open();text('workspaceStatus','작업공간을 만들었습니다. 소유자 또는 등록된 구성원만 목록에서 볼 수 있습니다.');}
    catch(error){if(valid(mark,true))problem(error,'workspaceCreateStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  async function openMembers(){
    if(!canManage())return;show('workspaceMemberDialog');const mark=stamp();
    try{const result=await request('/'+workspace.id+'/members');if(!valid(mark,true))return;
      for(const member of result.members){const row=paragraph(`${member.user_id} · ${roles[member.role] || '구성원'} · ${member.active?'활성':'비활성'} · 버전 ${member.revision}`);row.append(' ',button('수정',()=>{memberId=member.user_id;memberRevision=member.revision;$w('workspaceMemberUser').value=member.user_id;$w('workspaceMemberRole').value=member.role;$w('workspaceMemberActive').checked=member.active;text('workspaceMemberStatus','선택한 구성원의 현재 버전을 저장합니다.');}));$w('workspaceMemberList').append(row);}
    }catch(error){if(valid(mark,true))problem(error,'workspaceMemberStatus');}
  }
  async function saveMember(){
    if(busy || !canManage())return;const id=Number($w('workspaceMemberUser').value);if(!Number.isSafeInteger(id)||id<1){text('workspaceMemberStatus','기존 관리자 ID를 확인해 주세요.');return;}
    const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/members',{method:'POST',json:{user_id:id,role:$w('workspaceMemberRole').value,active:$w('workspaceMemberActive').checked,revision:id===memberId?memberRevision:0}});if(!valid(mark,true))return;closeDialogs();await selectWorkspace();text('workspaceStatus','구성원을 저장했습니다. 현재 권한을 다시 확인했습니다.');}
    catch(error){if(valid(mark,true))problem(error,'workspaceMemberStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  function fillDraft(value){draft=value;$w('workspaceDraftName').value=value.name;$w('workspaceDraftDescription').value=value.description;$w('workspaceDraftDefinition').value=JSON.stringify(value.definition,null,2);updateControls();}
  async function editDraft(id){
    show('workspaceDraftDialog');busy=true;updateControls();const mark=stamp();
    try{const result=await request('/'+workspace.id+'/drafts/'+id);if(!valid(mark,true))return;fillDraft(result.draft);}
    catch(error){if(valid(mark,true))problem(error,'workspaceDraftStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  function newDraft(){if(!canEdit())return;show('workspaceDraftDialog');$w('workspaceDraftDefinition').value='{"nodes":[],"edges":[]}';updateControls();}
  async function saveDraft(){
    if(busy || !canEdit() || draft&&!draft.active)return;
    const definition=$w('workspaceDraftDefinition').value,name=$w('workspaceDraftName').value,description=$w('workspaceDraftDescription').value;
    let raw;
    try{const parsed=JSON.parse(definition);if(!parsed || Array.isArray(parsed)||typeof parsed!=='object')throw new Error('object');finiteTree(parsed);
      const fields=`"name":${JSON.stringify(name)},"description":${JSON.stringify(description)},"definition":${definition}`;
      raw='{'+fields+(draft?`,"id":${JSON.stringify(draft.id)},"revision":${JSON.stringify(draft.revision)}`:'')+'}';if(new TextEncoder().encode(raw).length>65536)throw new Error('size');
    }catch(error){text('workspaceDraftStatus','유한한 값으로 구성된 제한 크기의 JSON 객체를 입력해 주세요.');return;}
    const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/drafts',{method:'POST',rawWorkspaceDraft:raw});if(!valid(mark,true))return;closeDialogs();await loadDrafts();text('workspaceStatus','비공개 초안을 저장했습니다. 실행이나 공개는 수행하지 않았습니다.');}
    catch(error){if(valid(mark,true))problem(error,'workspaceDraftStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  async function archiveWorkspace(){
    if(busy||!canManage()||!confirm('작업공간을 보관하고 비공개 접근을 중지하시겠습니까?'))return;const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/archive',{method:'POST',json:{active:false,revision:workspace.revision}});if(valid(mark))await open();}catch(error){if(valid(mark))problem(error);}finally{if(valid(mark)){busy=false;updateControls();}}
  }
  async function archiveDraft(value){
    if(busy||!canManage()||!confirm('초안과 저장본 내용에 대한 접근을 중지하고 보관하시겠습니까?'))return;const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/drafts/'+value.id+'/archive',{method:'POST',json:{revision:value.revision}});if(valid(mark))await loadDrafts();}catch(error){if(valid(mark))problem(error);}finally{if(valid(mark)){busy=false;updateControls();}}
  }
  async function openSnapshots(id){
    show('workspaceSnapshotDialog');const mark=stamp();
    try{const result=await request('/'+workspace.id+'/drafts/'+id);if(!valid(mark,true))return;draft=result.draft;updateControls();await loadSnapshots();}
    catch(error){if(valid(mark,true))problem(error,'workspaceSnapshotStatus');}
  }
  async function loadSnapshots(){
    const mark=stamp();if(!draft)return;const id=draft.id;
    try{const result=await request('/'+workspace.id+'/drafts/'+id+'/snapshots');if(!valid(mark,true)||draft?.id!==id)return;
      const host=$w('workspaceSnapshotList');host.replaceChildren();for(const value of result.snapshots){const row=card();row.append(paragraph(`저장본 ${value.ordinal} · 초안 버전 ${value.draft_revision} · ${value.active?'활성':'철회됨'}`),button('저장본 열기',()=>viewSnapshot(value.id),!value.active));host.append(row);}if(!result.snapshots.length)host.append(paragraph('저장된 저장본이 없습니다.'));
    }catch(error){if(valid(mark,true))problem(error,'workspaceSnapshotStatus');}
  }
  async function saveSnapshot(){
    if(busy||!canEdit()||!draft?.active)return;const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/drafts/'+draft.id+'/snapshots',{method:'POST',json:{draft_revision:draft.revision}});if(!valid(mark,true))return;await loadSnapshots();text('workspaceSnapshotStatus','현재 초안의 비공개 저장본을 만들었습니다.');}
    catch(error){if(valid(mark,true))problem(error,'workspaceSnapshotStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  async function viewSnapshot(id){
    window.WorkspaceReleaseAdmin?.select(null);
    clearPrivateRun();selectedSnapshotEpoch++;const selected=selectedSnapshotEpoch;snapshot=null;releaseUrl();text('workspaceSnapshotPreview','');$w('workspaceSnapshotPreview').hidden=true;updateControls();const mark=stamp();
    try{const result=await request('/'+workspace.id+'/drafts/'+draft.id+'/snapshots/'+id);if(!valid(mark,true)||selected!==selectedSnapshotEpoch)return;snapshot=result.snapshot;
      text('workspaceSnapshotPreview',JSON.stringify(snapshot.snapshot,null,2));$w('workspaceSnapshotPreview').hidden=false;text('workspaceSnapshotStatus',`저장본 ${snapshot.ordinal} · 초안 버전 ${snapshot.draft_revision} · JSON 저장본 · 별도 실행 승인 필요`);updateControls();
      window.WorkspaceReleaseAdmin?.select({workspace_id:workspace.id,draft_id:draft.id,snapshot_id:snapshot.id,snapshot_revision:snapshot.revision,can_manage:canManage() && snapshot.active});await loadRunOptions();
    }catch(error){if(valid(mark,true)&&selected===selectedSnapshotEpoch)problem(error,'workspaceSnapshotStatus');}
  }
  async function downloadSnapshot(){
    if(busy||!snapshot?.active||!available())return;const mark=stamp(), selected=selectedSnapshotEpoch, id=snapshot.id;busy=true;updateControls();
    try{const blob=await api(BASE+'/'+workspace.id+'/drafts/'+draft.id+'/snapshots/'+id+'/artifact',{silent:true,responseType:'blob'});
      if(!valid(mark,true)||selected!==selectedSnapshotEpoch||snapshot?.id!==id)return;
      if(!blob.type.toLowerCase().startsWith('application/json') || blob.size>131072)throw new Error('artifact_format');
      const attachment=JSON.parse(await blob.text());
      if(!valid(mark,true)||selected!==selectedSnapshotEpoch||snapshot?.id!==id)return;
      if(attachment.profile!==PROFILE || attachment.id!==id || attachment.workspace_id!==workspace.id || attachment.draft_id!==draft.id || attachment.saved_snapshot!==true || attachment.executable!==false || attachment.deployable!==false || attachment.published!==false)throw new Error('artifact_scope');
      releaseUrl();downloadUrl=URL.createObjectURL(blob);const url=downloadUrl,link=document.createElement('a');link.href=url;link.download='private-snapshot-'+id+'.json';document.body.append(link);link.click();link.remove();setTimeout(()=>{URL.revokeObjectURL(url);if(downloadUrl===url)downloadUrl='';},0);
      text('workspaceSnapshotStatus','비공개 JSON 저장본을 다운로드했습니다.');
    }catch(error){if(valid(mark,true))problem(error,'workspaceSnapshotStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }
  async function revokeSnapshot(){
    if(busy||!canManage()||!snapshot?.active||!confirm('선택한 저장본을 철회하시겠습니까?'))return;const mark=stamp();busy=true;updateControls();
    try{await request('/'+workspace.id+'/drafts/'+draft.id+'/snapshots/'+snapshot.id+'/revoke',{method:'POST',json:{revision:snapshot.revision}});if(!valid(mark,true))return;clearPrivateRun();window.WorkspaceReleaseAdmin?.select(null);selectedSnapshotEpoch++;snapshot=null;releaseUrl();text('workspaceSnapshotPreview','');$w('workspaceSnapshotPreview').hidden=true;await loadSnapshots();text('workspaceSnapshotStatus','저장본을 철회했습니다.');}
    catch(error){if(valid(mark,true))problem(error,'workspaceSnapshotStatus');}
    finally{if(valid(mark,true)){busy=false;updateControls();}}
  }

  function clearPrivateRun(){
    runEpoch++;clearTimeout(runExpiryTimer);runExpiryTimer=null;
    for(const controller of runControllers)controller.abort();runControllers.clear();
    runOptions=null;runPlan=null;runBusy=false;runUncertain=false;currentRun=null;
    $w('workspaceRunSection').hidden=true;$w('workspaceRunAuthority').checked=false;
    for(const id of ['workspaceRunStatus','workspaceRunPreview','workspaceRunOutput'])text(id,'');
    $w('workspaceRunPreview').hidden=true;$w('workspaceRunOutput').hidden=true;$w('workspaceRunOutputLabel').hidden=true;$w('workspaceRunHistory').replaceChildren();updateRunControls();
  }
  function runMark(){return stamp({runEpoch,selected:selectedSnapshotEpoch,snapshotId:snapshot?.id,draftId:draft?.id});}
  function runValid(mark){return valid(mark,true) && mark.runEpoch===runEpoch && mark.selected===selectedSnapshotEpoch && mark.snapshotId===snapshot?.id && mark.draftId===draft?.id && $w('workspaceSnapshotDialog').open;}
  function executionPath(){return '/'+workspace.id+'/drafts/'+draft.id+'/snapshots/'+snapshot.id+'/execution';}
  function runReady(){return available() && snapshot?.active && draft?.active && runOptions?.profile===RUN_PROFILE;}
  function updateRunControls(){
    const active=runReady(),prepared=active && runPlan && Number.isFinite(runPlan.expires) && runPlan.expires*1000>Date.now();
    $w('workspaceRunPrepare').disabled=busy || runBusy || runUncertain || !active || runOptions.can_run!==true || runOptions.supported!==true || !canEdit();
    $w('workspaceRunAuthority').disabled=runBusy || !prepared || runUncertain;
    $w('workspaceRunExecute').disabled=busy || runBusy || runUncertain || !prepared || !$w('workspaceRunAuthority').checked || !canEdit();
    $w('workspaceRunHistoryRefresh').disabled=runBusy || !active;
    $w('workspaceRunRefresh').disabled=runBusy || !active || !currentRun;
  }
  async function executionRequest(path,opts={}){
    const controller=new AbortController();runControllers.add(controller);const timer=setTimeout(()=>controller.abort(),15000);
    try{const result=await api(BASE+path,{...opts,silent:true,signal:controller.signal});if(!result || result.ok!==true || result.profile!==RUN_PROFILE)throw new Error('execution_profile');return result;}
    finally{clearTimeout(timer);runControllers.delete(controller);}
  }
  function executionProblem(error){
    if(error.status===401 || error.status===403 || error.status===404 || !token || !currentUser){problem(error);return;}
    text('workspaceRunStatus','요청을 완료하지 못했습니다. 자동 재시도하지 않습니다. 이력과 현재 권한을 확인해 주세요.');
  }
  async function loadRunOptions(){
    if(!snapshot?.active)return;const mark=runMark();$w('workspaceRunSection').hidden=false;text('workspaceRunStatus','지원 여부와 현재 실행 권한을 확인하는 중입니다.');
    try{const result=await executionRequest(executionPath()+'/options');if(!runValid(mark))return;runOptions=result;
      text('workspaceRunStatus',!result.supported?'이 저장본은 현재의 비공개 읽기 전용 MCP 실행 범위를 지원하지 않습니다.':result.can_run?'입력과 에이전트를 검토한 뒤 별도로 한 번 실행할 수 있습니다.':'이 계정은 실행 이력을 조회할 수 있습니다. 새 실행 권한은 없습니다.');updateRunControls();
    }catch(error){if(!runValid(mark))return;if(error.status===404 || error.message==='execution_profile'){runOptions=null;text('workspaceRunStatus','현재 서버에서는 비공개 실행을 사용할 수 없습니다. 기존 JSON 저장본 기능은 계속 사용할 수 있습니다.');updateRunControls();}else executionProblem(error);}
  }
  async function preparePrivateRun(){
    if($w('workspaceRunPrepare').disabled)return;const mark=runMark();runBusy=true;runPlan=null;currentRun=null;$w('workspaceRunAuthority').checked=false;text('workspaceRunPreview','');$w('workspaceRunPreview').hidden=true;text('workspaceRunOutput','');$w('workspaceRunOutput').hidden=true;$w('workspaceRunOutputLabel').hidden=true;updateRunControls();
    try{const result=await executionRequest(executionPath()+'/prepare',{method:'POST',json:{snapshot_revision:snapshot.revision}});if(!runValid(mark))return;
      const preview=result.preview;
      if(!/^wpt_[0-9a-f]{32}$/.test(result.ticket_id) || result.notice!==RUN_NOTICE || !Number.isFinite(result.expires) || result.expires*1000<=Date.now() || !preview || preview.workspace_id!==workspace.id || preview.draft_id!==draft.id || preview.snapshot_id!==snapshot.id || preview.snapshot_revision!==snapshot.revision || !Number.isSafeInteger(preview.resource_id) || preview.resource_id<1 || preview.max_calls!==1 || preview.seconds!==12 || typeof preview.tool!=='string' || !preview.input || typeof preview.input!=='object' || Array.isArray(preview.input))throw new Error('execution_preview');
      runPlan={ticket_id:result.ticket_id,expires:result.expires};
      text('workspaceRunPreview',`저장본 ${snapshot.ordinal} · 저장본 버전 ${preview.snapshot_revision}\n외부 MCP 에이전트 참조: ${preview.resource_id}\n도구: ${preview.tool}\n최대 호출: 1회 · 제한: ${preview.seconds}초\n승인 유효 시각: ${new Date(result.expires*1000).toLocaleString()}\n전송할 정확한 입력:\n${JSON.stringify(preview.input,null,2)}`);$w('workspaceRunPreview').hidden=false;
      text('workspaceRunStatus','실행 준비 완료. 준비 단계에서는 에이전트를 호출하지 않았습니다. 입력 전송과 한 번의 실행에 동의해 주세요.');
      clearTimeout(runExpiryTimer);runExpiryTimer=setTimeout(()=>{if(runValid(mark)){runPlan=null;$w('workspaceRunAuthority').checked=false;text('workspaceRunStatus','실행 준비가 만료되었습니다. 새로 검토해 주세요.');updateRunControls();}},Math.min(result.expires*1000-Date.now(),2147483647));
    }catch(error){if(runValid(mark)){runPlan=null;executionProblem(error);}}
    finally{if(runValid(mark)){runBusy=false;updateRunControls();}}
  }
  function outputText(output){
    if(typeof output==='string')return output;
    if(output && Array.isArray(output.content)){const parts=output.content.filter(item=>item && item.type==='text' && typeof item.text==='string').map(item=>item.text);if(parts.length)return parts.join('\n');}
    return JSON.stringify(output,null,2);
  }
  function renderPrivateRun(value){
    if(!value || !/^wpr_[0-9a-f]{32}$/.test(value.id))throw new Error('execution_run');currentRun=value.id;
    const labels={prepared:'접수됨',dispatched:'에이전트 응답 대기',succeeded:'완료',failed:'실패',unknown:'외부 실행 결과 확인 필요',denied:'실행 거부됨'};
    text('workspaceRunStatus',`비공개 실행: ${labels[value.status] || '상태 확인 필요'}${value.status==='unknown'?' · 새 실행을 시작하지 않고 이력을 확인해 주세요.':''}`);
    if(['prepared','dispatched','unknown'].includes(value.status) || !Object.hasOwn(labels,value.status))runUncertain=true;
    text('workspaceRunOutput','');$w('workspaceRunOutput').hidden=true;$w('workspaceRunOutputLabel').hidden=true;
    if(value.output!==null && value.output!==undefined){const valueText=outputText(value.output);if(typeof valueText==='string'){text('workspaceRunOutput',valueText.slice(0,20000));$w('workspaceRunOutput').hidden=false;$w('workspaceRunOutputLabel').hidden=false;text('workspaceRunOutputLabel',valueText.length>20000?'에이전트 출력 일부 (검증되지 않은 내용)':'에이전트 출력 (검증되지 않은 내용)');}}
    updateRunControls();
  }
  async function executePrivateRun(){
    if($w('workspaceRunExecute').disabled || !runPlan || runPlan.expires*1000<=Date.now()){updateRunControls();return;}
    const mark=runMark(),body={ticket_id:runPlan.ticket_id,authorized:true,notice:RUN_NOTICE};runPlan=null;clearTimeout(runExpiryTimer);runExpiryTimer=null;runBusy=true;$w('workspaceRunAuthority').checked=false;$w('workspaceRunPreview').hidden=true;text('workspaceRunStatus','한 번의 비공개 실행을 요청하는 중입니다. 자동 재전송하지 않습니다.');updateRunControls();
    try{const result=await executionRequest(executionPath()+'/runs',{method:'POST',json:body});if(!runValid(mark))return;renderPrivateRun(result.run);}
    catch(error){if(runValid(mark)){runUncertain=true;text('workspaceRunStatus','실행 접수 또는 외부 결과를 확정할 수 없습니다. 새 실행을 시작하지 않고 실행 이력을 확인해 주세요.');if(error.status===401 || error.status===403 || error.status===404 || !token || !currentUser)executionProblem(error);}}
    finally{if(runValid(mark)){runBusy=false;updateRunControls();}}
  }
  async function loadPrivateHistory(){
    if($w('workspaceRunHistoryRefresh').disabled)return;const mark=runMark();runBusy=true;updateRunControls();
    try{const result=await executionRequest(executionPath()+'/runs');if(!runValid(mark))return;$w('workspaceRunHistory').replaceChildren();
      for(const value of result.runs){const row=card();const time=Number.isFinite(value.created)?new Date(value.created*1000).toLocaleString():'';row.append(paragraph(`비공개 실행 · ${time}`),button('실행 결과 보기',()=>readPrivateRun(value.id)));$w('workspaceRunHistory').append(row);}if(!result.runs.length)$w('workspaceRunHistory').append(paragraph('기록된 비공개 실행이 없습니다.'));
    }catch(error){if(runValid(mark))executionProblem(error);}
    finally{if(runValid(mark)){runBusy=false;updateRunControls();}}
  }
  async function readPrivateRun(id){
    if(runBusy || !runReady() || !/^wpr_[0-9a-f]{32}$/.test(id))return;const mark=runMark();runBusy=true;updateRunControls();
    try{const result=await executionRequest(executionPath()+'/runs/'+id);if(runValid(mark))renderPrivateRun(result.run);}
    catch(error){if(runValid(mark))executionProblem(error);}
    finally{if(runValid(mark)){runBusy=false;updateRunControls();}}
  }

  $w('workspaceRefresh').addEventListener('click',open);$w('workspaceSelect').addEventListener('change',selectWorkspace);
  $w('workspaceIdentity')?.addEventListener('click',()=>{if(canManage())window.WorkspaceIdentityAdmin?.open(workspace.id);});
  $w('workspaceAdvancement')?.addEventListener('click',()=>{if(available() && workspace?.active)window.AdvancementAdmin?.open(workspace.id);});
  $w('workspaceEvidence')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceEvidenceAdmin?.open(workspace.id);});
  $w('workspaceReliability')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceReliabilityAdmin?.open(workspace.id);});
  $w('workspaceReliabilityControls')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceReliabilityControlsAdmin?.open(workspace.id);});
  $w('workspaceGrowth')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceGrowthAdmin?.open(workspace.id);});
  $w('workspaceMachineUpdates')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceMachineUpdatesAdmin?.open(workspace.id);});
  $w('workspaceTypedEvidence')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceTypedEvidenceAdmin?.open(workspace.id);});
  $w('workspaceResearch')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceReliabilityResearchAdmin?.open(workspace.id);});
  $w('workspaceResearchControls')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceResearchControlsAdmin?.open(workspace.id);});
  $w('workspaceRemoteA2A')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceRemoteA2AAdmin?.open(workspace.id);});
  $w('workspaceProtocolConformance')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkspaceProtocolConformanceAdmin?.open(workspace.id);});

  $w('workspaceQuality')?.addEventListener('click',()=>{if(available() && workspace?.active)window.WorkflowQualityReviewAdmin?.open(workspace.id);});
  $w('workspaceCreate').addEventListener('click',()=>{if(!available()||!options.can_provision)return;show('workspaceCreateDialog');$w('workspaceOwner').value=options.user.user_id;});
  $w('workspaceCreateSave').addEventListener('click',provision);$w('workspaceMembers').addEventListener('click',openMembers);$w('workspaceMemberSave').addEventListener('click',saveMember);
  $w('workspaceMemberUser').addEventListener('input',()=>{if(Number($w('workspaceMemberUser').value)!==memberId){memberRevision=0;memberId=null;}});
  $w('workspaceDraftCreate').addEventListener('click',newDraft);$w('workspaceDraftSave').addEventListener('click',saveDraft);$w('workspaceArchive').addEventListener('click',archiveWorkspace);
  $w('workspaceRunPrepare').addEventListener('click',preparePrivateRun);$w('workspaceRunAuthority').addEventListener('change',updateRunControls);$w('workspaceRunExecute').addEventListener('click',executePrivateRun);$w('workspaceRunHistoryRefresh').addEventListener('click',loadPrivateHistory);$w('workspaceRunRefresh').addEventListener('click',()=>readPrivateRun(currentRun));
  $w('workspaceSnapshotSave').addEventListener('click',saveSnapshot);$w('workspaceSnapshotDownload').addEventListener('click',downloadSnapshot);$w('workspaceSnapshotRevoke').addEventListener('click',revokeSnapshot);
  for(const [dialog,close] of [['workspaceCreateDialog','workspaceCreateClose'],['workspaceMemberDialog','workspaceMemberClose'],['workspaceDraftDialog','workspaceDraftClose'],['workspaceSnapshotDialog','workspaceSnapshotClose']]){
    $w(close).addEventListener('click',closeDialogs);$w(dialog).addEventListener('cancel',event=>{event.preventDefault();closeDialogs();});
  }
  window.addEventListener('pagehide',()=>clear());
  window.WorkspaceAdmin={openReference:async(ws,id)=>{await open();const select=$w('workspaceSelect');if(![...select.options].some(o=>o.value===ws))throw Error('현재 멤버십으로 접근할 수 없습니다.');select.value=ws;await selectWorkspace();if(workspace?.id===ws)await editDraft(id);},open,leave,clear,onSession};
  clear();
})();

return window.WorkspaceAdmin;
}
