import {wantsEdgeOutput,resolveEdgeOutput} from '../core/output-delivery.js';
// Staff-private specialist panels; customer organization membership never grants staff access.
const BASE = '/admin/api/workflow-workspaces';
export const PANELS = [
  ['flow', '워크플로 구성·실행', '최대 10개 단계의 입력 연결을 검토하고, 동의한 실행 한 번만 요청합니다.'],
  ['lineage', '워크플로 실행 증거', '서명된 실행의 노드·분기·출처를 확인하고 허용된 원본만 보관합니다.'],
  ['evidence', '보관된 증거', '현재 증거 범위와 만료 상태를 확인하고 특정 원본의 사용을 철회합니다.'],
  ['release', '저장본 릴리스·배포', '성공한 저장본 테스트에서 릴리스를 만들고 개별 배포·다운로드·철회를 관리합니다.'],
  ['typed-release', '다단계 릴리스·배포', '정확한 워크플로 버전의 성공 테스트를 기준으로 배포 권한과 SDK 패키지를 관리합니다.'],
  ['machine-updates', '검증된 수신처 알림', '근거 메타데이터의 개별 구독·발송·철회와 비공개 수신 활성화를 관리합니다.'],
  ['remote-a2a', '원격 A2A 작업', '작업 제출·상태 확인·취소·스트림 재연결·추가 입력을 개별 동의로 요청합니다.'],
  ['protocol-conformance', '규격 적합성·테스트 원장', '보관된 샌드박스 근거와 공개 서명을 검사합니다. 실제 거래는 실행하지 않습니다.'],
  ['reliability', '신뢰성 평가 근거', '목적별 평가 계약·암호화 원본·실제 관측 연결·비공개 보고서를 관리합니다.'],
  ['reliability-controls', '평가·라우팅 제어', '평가 예약·워커·신뢰 근거와 오프라인 라우팅 정책을 개별 승인합니다.'],
  ['reliability-research', '짝지은 신뢰성 연구', '검토한 코퍼스·연구 명세·짝지은 분석과 메타데이터 섀도를 관리합니다.'],
  ['research-controls', '검토된 계획·단일 제공자', '새 계획 검토와 제한된 단일 제공자 실행·운영 근거·회로 제어를 관리합니다.'],
  ['growth', '앱 구성·SDK·지원 결과', '검토한 계약 기반 앱 구성을 저장하고 SDK 정책과 개별 지원 관측을 관리합니다.'],
  ['advancement', '운영 시뮬레이션·초안 지원', '시뮬레이션 원장·검토한 초안 변경·미검증 운영 준비 근거를 관리합니다.'],
  ['product', '계약 기반 제품 비교', '정확한 제품 입력을 검토·저장한 뒤 별도 동의로 한 번 테스트합니다.'],
  ['agreement', '제공자 합의·시뮬레이션', '현재 소유권에 연결된 약정 버전과 정수 배분·환불을 TEST_UNIT으로 검토합니다.'],
  ['identity', '고객 접근·제공자 소유권', '고객별 접근과 HTTPS 소유권 확인·철회·별도 워크스페이스 이전을 관리합니다.'],
  ['quality', '직원 품질 검토', '실행 전 예약, 별도 검토자 배정, 결과 확인과 평가·조정을 기록합니다.'],
];
let active = null, lifetime = null, opening = 0;
export function reset() { opening++; lifetime?.abort(); lifetime = null; active?.leave(); active = null; }

export async function render(body, ctx) {
  reset();
  const {ui, api} = ctx;
  const owner = api.session.token();
  let staffUser = {};
  const current = () => ctx.isCurrent() && owner === api.session.token();
  lifetime = new AbortController();
  const guard = lifetime;
  for (const event of ['hashchange', 'admin-session-expired', 'pagehide']) addEventListener(event, reset, {signal: guard.signal});
  const select = ui.el('select', {'aria-label': '직원 워크스페이스'});
  const status = ui.el('p', {role: 'status', class: 'adm-status'});
  const cards = ui.el('div', {class: 'adm-grid adm-specialist-cards'});
  const notice = ui.el('p', {class: 'adm-muted', text: '현재 직원 계정에 멤버십이 있는 워크스페이스만 표시합니다. 고객 조직 조회 권한으로 비공개 입력·출력을 열 수는 없습니다. 이 화면의 내용은 브라우저 캐시에 저장하지 않습니다.'});
  body.replaceChildren(ui.el('section', {class: 'adm-card'}, ui.el('h2', {text: '워크스페이스 전문 관리'}), notice,
    ui.el('div', {class: 'adm-filters'}, select, ui.el('a', {class: 'adm-btn', href: '#/customers/staff', text: '직원 멤버십·초안 관리'})), status), cards);
  try {
    const [listing, options] = await Promise.all([api.read(BASE, {grade: 'sensitive', force: true}), api.read(BASE + '/options', {grade: 'sensitive', force: true})]);
    const data = listing.data; staffUser = options.data.user || {};
    if (!current()) return;
    select.replaceChildren(ui.el('option', {value: '', text: '직원 워크스페이스 선택'}), ...(data.workspaces || []).map(row => ui.el('option', {value: row.id, text: row.name || row.id})));
    const requested = ctx.params.get('workspace');
    if ((data.workspaces || []).some(row => row.id === requested)) select.value = requested;
    status.textContent = data.workspaces?.length ? '워크스페이스를 선택한 뒤 전문 패널을 여세요.' : '이 계정에 허용된 직원 워크스페이스가 없습니다. 직원 멤버십·초안 관리에서 멤버십을 확인하세요.';
    const category = ui.el('select',{'aria-label':'업무 종류'},[['all','모든 전문 업무'],['execution','실행·근거'],['release','배포·알림'],['reliability','평가·신뢰성'],['provider','제공자·품질·운영 지원']].map(([value,text])=>ui.el('option',{value,text})));
    const family=key=>['flow','lineage','evidence','remote-a2a','protocol-conformance'].includes(key)?'execution':['release','typed-release','machine-updates'].includes(key)?'release':key.includes('reliability')||key==='research-controls'?'reliability':'provider';
    const requestedPanel=ctx.params.get('panel');if(requestedPanel)category.value=family(requestedPanel);
    select.after(category);select.closest('.adm-filters').append(ui.el('a',{class:'adm-btn primary',href:'#/workflows/w03'+(select.value?'?workspace='+encodeURIComponent(select.value):''),text:'워크플로 만들기'}));
    const show = () => {
      active?.leave(); active=null;
      cards.replaceChildren(...PANELS.filter(([key])=>(!requestedPanel||key===requestedPanel)&&(category.value==='all'||family(key)===category.value)).map(([key,label,description])=>ui.el('section',{class:'adm-card'},ui.el('h3',{text:label}),ui.el('p',{text:description}),ui.el('button',{class:'adm-btn primary',type:'button',disabled:!select.value,dataset:{panel:key},onclick:event=>openPanel(key,select.value,event.currentTarget)},label+' 열기'))));
      if(!select.value)status.textContent=data.workspaces?.length?'먼저 작업공간을 선택하세요. 허용된 대상의 정보만 조회합니다.':'접근 가능한 직원 작업공간이 없습니다. 직원 멤버십·초안 관리에서 멤버십을 확인하세요.';
    };
    select.addEventListener('change',()=>{show();if(requestedPanel&&select.value)cards.querySelector('button')?.click();});category.onchange=show;
    if(!select.value&&data.workspaces?.length===1)select.value=data.workspaces[0].id;
    show();
    if(requestedPanel&&select.value){const trigger=cards.querySelector('button');if(trigger)await openPanel(requestedPanel,select.value,trigger);}

  } catch (error) { if (current()) status.textContent = error.message; }

  async function openPanel(key, ws, trigger) {
    if (!current() || !/^ws_[a-f0-9]{32}$/.test(ws)) return;
    const turn = ++opening;
    const panelCurrent = () => current() && turn === opening;
    trigger.disabled = true;
    try {
      active?.leave();
      const selection = ['release', 'typed-release'].includes(key);
      const module = await import(selection ? './release-selector.js' : './panel-' + key + '.js');
      if (!panelCurrent() || select.value !== ws) return;
      let dialog, reason, writing = false, requests = 0;
      const identity = () => panelCurrent() && select.value === ws ? owner : '';
      const decorate = node => {
        dialog = node; node.classList.add('adm-specialist-dialog');
        node.prepend(ui.el('p',{class:'adm-breadcrumb',text:'선택한 직원 작업공간 · '+(select.selectedOptions[0]?.textContent || '')}));
        for(const area of node.querySelectorAll('textarea')){
          const label=area.closest('label');
          if(label&&/JSON|json|그래프|graph|definition|정의/.test(label.textContent)){
            const advanced=ui.el('details',{class:'adm-raw-details'},ui.el('summary',{text:'고급 입력 · '+label.textContent.slice(0,70)}));label.before(advanced);advanced.append(label);
          }
        }
        if(key==='flow'){const preview=node.querySelector('.adm-typed-preview'),status=node.querySelector('[role=status]');if(preview&&status)status.after(preview);}
        reason = ui.el('textarea', {rows: '2', maxlength: '300', 'aria-label': '전문 패널 변경 사유', placeholder: '변경 작업 전에 사유를 4~300자로 입력하세요. 비밀번호·개인정보는 입력하지 마세요.'});
        const mutations = new Set(["합의 버전 기록", "합의 버전 철회", "배분 미리보기", "시뮬레이션 정산 기록", "시뮬레이션 환불 기록", "고객 접근 저장", "HTTPS 확인 준비", "만료된 확인 기록 정리", "이전 수락·새 확인 준비", "엔드포인트 소유권 확인", "새 확인 준비", "소유권 확인 철회", "엔드포인트 이전 제안","워크플로 구성 검토", "검토한 워크플로 저장", "SDK 정책 적용", "지원 관측 기록", "지원 관측 철회", "시뮬레이션 승인", "시뮬레이션 결과 기록", "불확실한 결과 확인 기록", "시뮬레이션 결과 1회 취소", "정확한 변경안 준비", "검토한 변경안 적용", "생성된 변경안 적용", "검토할 안내 생성", "미검증 선언만 기록", "재시도 없이 만료 시뮬레이션 정리", "실행 시뮬레이션 정책 저장", "샌드박스 이벤트 준비", "샌드박스 이벤트 1회 전송", "샌드박스 이벤트 철회", "제품 비교 입력 검토", "비공개 구성 저장", "실제 테스트 1회 준비", "비공개 계약 테스트 1회 실행","불변 평가 버전 저장", "평가 계약 철회", "코호트 보관 승인", "보관 동의 철회", "암호화된 원본 보관", "비공개 원본 열람", "원본 영구 삭제", "만료 원본 삭제", "실행 관측 연결 기록", "평가 예약 중지", "평가 예약 활성화", "평가 워커 활성화", "평가 워커 비활성화", "평가 코퍼스 버전 승인", "평가 계획 저장", "기한이 된 평가 예약", "평가 작업 취소", "라우팅 미리보기 정책 저장", "라우팅 결정 기록", "기록된 라우팅 결정 재현", "라우팅 미리보기 중지", "짝지은 연구 명세 승인", "연구 평가 계획 저장", "연구 명세 철회", "메타데이터 섀도 검토", "계획 검토 준비", "검토한 새 초안 저장", "공개 목적의 모델 제안 요청", "파일럿 정책 적용", "선택한 에이전트 1회 실행", "단일 작업 준비", "현재 운영 근거 적격 확인", "운영 근거 적격 철회", "명시적 회로 제어 정책 저장", "보관된 관측 1건 반영", "별도 승인된 탐색 연결", "완료된 연결 탐색 조회", "작업 1회 제출", "상태 1회 확인", "취소 1회 요청", "기존 작업 스트림 재연결", "추가 입력 1회 전송", "오프라인 서명 검사", "합성 규격 검토 기록", "저장본 릴리스 생성", "다단계 릴리스 생성", "저장본 배포 권한 발급", "다단계 배포 권한 발급", "선택 릴리스 철회", "선택 다단계 릴리스 철회", "배포 권한 철회", "이 배포 권한 철회", "제한된 보존 정리 실행", "선택 테스트 확인 메모 기록", "복원 후 현재 소유자 검토", "현재 소유자 검토 확정", "개별 구독 승인", "알림 준비", "제한된 자동 알림 승인", "구독 철회", "준비된 알림 1회 발송", "비공개 수신 활성화", "비공개 수신 철회", '새 버전 저장', '전체 실행 내용 검토', '선택 워크플로 중지', '검토한 워크플로 실행', '기존 노드 원본 보관', '증거 사용 철회', '예약 후 실행 연결', '배정된 결과 열기', '실행 전 예약 등록', '별도 조정 기록', '배정된 검토 기록']);
        node.addEventListener('click', event => {
          if (mutations.has(event.target.closest('button')?.textContent.trim()) && reason.value.trim().length < 4) {
            event.preventDefault(); event.stopImmediatePropagation(); reason.focus(); ui.toast('변경 사유를 4자 이상 입력하세요.', 'bad');
          }
        }, true);
        node.prepend(ui.el('section', {class: 'adm-card adm-specialist-reason'}, ui.el('label', {text: '변경 사유 (감사 기록)'}, reason)));
        if (key === 'advancement') {
          const clearPurpose = event => {
            if (event.target === reason || event.target.type === 'checkbox') return;
            for (const check of node.querySelectorAll('input[data-purpose-consent]:checked')) check.checked = false;
          };
          node.addEventListener('input', clearPurpose); node.addEventListener('change', clearPurpose);
        }
        if (['reliability', 'reliability-controls', 'reliability-research', 'research-controls'].includes(key)) {
          const clearConsent = event => {
            if (event.target === reason || event.target.type === 'checkbox') return;
            for (const check of node.querySelectorAll('input[type=checkbox]:checked')) { check.checked = false; check.dispatchEvent(new Event('change', {bubbles: true})); }
          };
          node.addEventListener('input', clearConsent); node.addEventListener('change', clearConsent);
        }
        node.addEventListener('close', () => { if (current() && trigger.isConnected) trigger.focus(); }, {once: true});
      };
      const transport = async (path, options = {}) => {
        const write = options.method === 'POST';
        if (!identity() || guard.signal.aborted) throw new api.ApiError(409, '화면 또는 세션이 변경되었습니다.');
        const allowed = new URL(path, location.origin);
        if (allowed.origin !== location.origin || ![BASE + '/' + ws + '/', '/admin/api/v2/workspace-panels/' + ws + '/'].some(prefix => allowed.pathname.startsWith(prefix))) throw new api.ApiError(400, '잘못된 워크스페이스 경로입니다.');
        if (write && writing) throw new api.ApiError(409, '이전 변경 결과를 기다리세요.');
        const explanation = reason?.value.trim() || '';
        if (write && explanation.length < 4) { reason?.focus(); ui.toast('변경 사유를 4자 이상 입력하세요.', 'bad'); throw new api.ApiError(400, '변경 사유가 필요합니다.'); }
        if (write) writing = true;
        requests++; dialog?.setAttribute('aria-busy', 'true');
        const headers = {'X-Dashboard': '1', Authorization: 'Bearer ' + owner};
        if (write) { headers['Content-Type'] = 'application/json'; headers['X-Admin-Reason'] = encodeURIComponent(explanation); }
        if(wantsEdgeOutput(path,write?'POST':'GET'))headers['X-Edge-Output-Transport']='v1';
        try {
          const signals = [guard.signal, AbortSignal.timeout(write && (path.endsWith('/runs') || path.includes('/remote-a2a/tasks') || path.endsWith('/app-factory/model-proposals') || path.endsWith('/advancement/support/assistant')) ? 90000 : 20000)];
          if (options.signal) signals.push(options.signal);
          let response = await fetch(path, {method: write ? 'POST' : 'GET', headers, cache: 'no-store', credentials: 'same-origin',
            body: write ? JSON.stringify(options.json) : undefined, signal: AbortSignal.any(signals)});
      response=await resolveEdgeOutput(response,recovery=>fetch(recovery,{headers:{'X-Dashboard':'1',Authorization:'Bearer '+owner},cache:'no-store',credentials:'same-origin'}),()=>{if(!identity())throw new api.ApiError(409,'세션이 변경되어 이전 응답을 폐기했습니다.');});
          if (!identity()) throw new api.ApiError(409, '이전 세션 응답을 폐기했습니다.');
          if (response.status === 401) { api.session.clear(); dispatchEvent(new Event('admin-session-expired')); }
          if ([401, 403, 404].includes(response.status)) active?.leave();
          const result = response.ok && options.responseType === 'blob' ? await response.blob() : await response.json();
          if (response.headers.get('X-Admin-Audit-State') === 'pending') ui.toast('요청 결과와 별도로 감사 기록 완료 여부를 확인해야 합니다.', 'bad');
          if (!response.ok) throw new api.ApiError(response.status, result.detail || '요청 결과를 확인할 수 없습니다.');
          return result;
        } catch (error) {
          if (write && identity()) ui.toast('자동 재시도하지 않았습니다. 현재 기록을 조회한 후 다음 작업을 결정하세요.', 'bad');
          throw error;
        } finally { if (write) writing = false; requests--; dialog?.setAttribute('aria-busy', String(requests > 0)); }
      };
      const dependencies = {api: transport, scopeIdentity: identity, currentUser: staffUser, isCurrent: panelCurrent, decorate, initialFlow:ctx.params.get('flow'), navigatePanel: next => openPanel(next, ws, trigger)};
      active = selection ? module.createSelector(dependencies, key) : module.createPanel(dependencies);
      await active.open(ws);
    } catch (error) { if (current()) ui.toast(error.message || '전문 패널을 열 수 없습니다.', 'bad'); }
    finally { if (current() && trigger.isConnected) trigger.disabled = false; }
  }
}
