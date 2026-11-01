// Generic deterministic mappings are tested explicitly; a preview grants no execution permission.
export async function openIOTransforms(ctx) {
  const {ui, api} = ctx;
  const el = ui.el;
  const dialog = el('dialog', {class: 'adm-dialog', 'aria-label': '범용 입출력 변환'});
  let closed = false, busy = false, uncertain = false, schemas = null, commandSent = false;
  const token = api.session.token();
  const status = el('p', {role: 'status', 'aria-live': 'polite'});
  function leave() {closed = true; dialog.close(); dialog.remove(); removeEventListener('hashchange', leave); document.getElementById('adm-logout')?.removeEventListener('click', leave);}
  const close = el('button', {type: 'button', class: 'adm-btn', text: '닫기', onclick: leave});
  addEventListener('hashchange', leave);document.getElementById('adm-logout')?.addEventListener('click', leave);
  dialog.addEventListener('cancel', event => {event.preventDefault(); close.click();});
  const field = (label, type = 'text', value = '') => {
    const input = type === 'textarea' ? el('textarea', {rows: '8', value}) : el('input', {type, value});
    input.value = value;
    dialog.append(el('label', {}, label, input)); return input;
  };
  dialog.append(el('h2', {text: '범용 입력·출력 변환'}), close,
    el('p', {text: '서로 다른 필드명·중첩·배열·자료형·조건을 명시적인 규칙으로 연결합니다. 변환은 에이전트의 기능 동등성이나 장애 독립성을 승인하지 않습니다.'}));
  const resource = field('에이전트 ID', 'number');
  const tool = field('등록된 읽기 전용 도구');
  const contract = el('select', {}, ['docs.search.v1', 'news.search.v1'].map(value => el('option', {value, text: value})));
  dialog.append(el('label', {}, '공통 결과 계약', contract));
  const input = field('입력 변환식 (JSON)', 'textarea', JSON.stringify({op: 'object', fields: {}}, null, 2));
  const output = field('출력 변환식 (JSON)', 'textarea', JSON.stringify({op: 'object', fields: {}}, null, 2));
  const checks = field('제공자 성공 상태 조건 (JSON)', 'textarea', '[]');
  const cases = field('실제 검증 입력 1~3개 (JSON)', 'textarea', JSON.stringify([{query: 'public documentation', language: 'en', limit: 2}], null, 2));
  const nativeExample = field('출력 변환 미리보기용 실제 응답 구조 (JSON)', 'textarea', '{}');
  const schemaView = el('pre');
  dialog.append(el('details', {}, el('summary', {text: '현재 원본·목표 스키마'}), schemaView),
    el('p', {text: '지원 연산: get(JSON Pointer), object, map, coalesce, choose, strict integer/number/boolean/string, trim, lower, upper, concat, take, utc, parse_json. 성공 상태 allowed와 요청 대조 equals_input 조건을 사용할 수 있습니다. URL·시각은 원본 응답에서 가져오며 외부 호출·코드 실행·현재 시각 생성은 허용하지 않습니다.'}));
  const authorize = el('input', {type: 'checkbox'});
  dialog.append(el('label', {}, authorize, '등록된 도구의 현재 계약을 확인했고, 공개 테스트 입력을 실제 제공자에게 최대 3회 보내 변환을 검증하는 데 동의합니다.'));
  const controls = el('div');
  const profiles = el('div');
  function recipe(direction) {
    if (!schemas) throw new Error('먼저 현재 스키마를 불러오세요.');
    return {version: 'json-io-transform-v1', input_schema: direction === 'input' ? schemas.canonical.input_schema : schemas.native.outputSchema,
      output_schema: direction === 'input' ? schemas.native.inputSchema : schemas.canonical.output_schema,
      expression: JSON.parse(direction === 'input' ? input.value : output.value)};
  }
  function setBusy(on) { busy = on; controls.querySelectorAll('button').forEach(button => {button.disabled = on;}); }
  async function perform(action, mutate = false) {
    if (busy || uncertain && mutate) return;
    if (api.session.token() !== token) {leave();return;}
    commandSent = false;setBusy(true); status.textContent = '확인 중…';
    try {await action();}
    catch (error) {if (!closed) {status.textContent = error.message; if (mutate && commandSent && (!error.status || error.status >= 500)) {uncertain = true; status.textContent += ' 실제 실행/저장 결과를 확인한 후 다시 진행하세요. 자동 재시도하지 않습니다.';}}}
    finally {if (!closed) setBusy(false);}
  }
  const button = (text, action) => el('button', {type: 'button', class: 'adm-btn', text, onclick: action});
  async function list() {
    const result = await api.read('/admin/api/workflow-io-profiles', {force: true, grade: 'detail'});
    if (closed) return;
    profiles.replaceChildren(el('h3', {text: '검증된 프로필 · 최대 100개'}),
      ...(result.data?.profiles || []).map(profile => el('div', {class: 'adm-card'},
        el('p', {text: `${profile.id} · ${profile.revoked ? '철회됨' : profile.expires * 1000 <= Date.now() ? '만료됨' : '검증 기록 있음'}`}),
        button('철회', () => perform(async () => {
          const approved = await ui.confirmChange({title: '입출력 프로필 철회', summary: '이 프로필의 새 실행을 중지합니다.', effect: '이미 전송된 요청은 취소하거나 재전송하지 않습니다.', confirmLabel: '철회', danger: true});
          if (!approved || closed) return;
          commandSent = true;await api.write('/admin/api/workflow-io-profiles/' + profile.id, {}, {method: 'DELETE', reason: approved.reason});
          await list();status.textContent = '프로필을 철회했습니다.';
        }, true)))));
  }
  controls.append(button('1. 현재 스키마 불러오기', () => perform(async () => {
    schemas = null;
    const params = new URLSearchParams({resource_id: resource.value, tool: tool.value, contract_id: contract.value});
    const result = await api.read('/admin/api/workflow-io-profiles/schemas?' + params, {force: true, grade: 'detail'});
    if (closed) return;
    schemas = {...result.data};schemaView.textContent = JSON.stringify(schemas, null, 2);
    schemas.identity = [resource.value, tool.value, contract.value].join('|');
    status.textContent = '필드·배열 매핑과 상태 조건을 작성하고 미리보기로 확인하세요. 계약 승인은 별도 작업입니다.';
  })), button('2. 입력 변환 미리보기', () => perform(async () => {
    const result = await api.write('/admin/api/workflow-io-profiles/preview', {recipe: recipe('input'), input: JSON.parse(cases.value)[0]});
    if (!closed) status.textContent = '제공자 호출 0회 · 입력 변환: ' + JSON.stringify(result.output);
  })), button('출력 변환 미리보기', () => perform(async () => {
    const result = await api.write('/admin/api/workflow-io-profiles/preview', {recipe: recipe('output'), input: JSON.parse(nativeExample.value)});
    if (!closed) status.textContent = '제공자 호출 0회 · 출력 변환: ' + JSON.stringify(result.output);
  })), button('3. 실제 실행 검증·프로필 저장', () => perform(async () => {
    if (!authorize.checked) throw new Error('실제 공개 입력 전달 동의를 확인하세요.');
    if (!schemas || schemas.identity !== [resource.value, tool.value, contract.value].join('|')) throw new Error('변경한 연결의 스키마를 다시 불러오세요.');
    const payload = {profile: {resource_id: Number(resource.value), tool: tool.value, contract_id: contract.value,
      input_transform: recipe('input'), output_transform: recipe('output'), status_checks: JSON.parse(checks.value)},
      cases: JSON.parse(cases.value), authority: true, notice: 'verified-io-transform-v1'};
    authorize.checked = false;
    commandSent = true;
    const result = await api.write('/admin/api/workflow-io-profiles/verify', payload);
    if (!closed) {await list();status.textContent = `${result.id} · 실제 검증 ${result.cases}건 통과. 에이전트 노드의 검증된 입출력 프로필과 폴백 대체 프로필에 연결하세요. 활성화는 별도입니다.`;}
  }, true)), button('프로필 목록 새로고침', () => perform(list)));
  dialog.append(controls, status, profiles);document.body.append(dialog);dialog.showModal();
  await perform(list);
}
