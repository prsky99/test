"""Build isolated renewal panel factories from the established specialist controllers.

The protocol/action logic has one source. This adapter replaces legacy shell
bindings and presentation only. Use --write after changing a source controller.
"""
import argparse
from pathlib import Path
from scripts.admin_specialist_release_copy import WORDS as RELEASE_WORDS
from scripts.admin_specialist_protocol_copy import WORDS as PROTOCOL_WORDS
from scripts.admin_specialist_reliability_copy import WORDS as RELIABILITY_WORDS
from scripts.admin_specialist_growth_copy import WORDS as GROWTH_WORDS
from scripts.admin_specialist_identity_copy import WORDS as IDENTITY_WORDS

ROOT = Path(__file__).resolve().parents[1]
PANELS = {'flow': 'workspace-flow-admin.js', 'lineage': 'workspace-typed-evidence-admin.js',
          'evidence': 'workspace-evidence-admin.js', 'quality': 'workflow-quality-admin.js',
          'release': 'workspace-release-admin.js', 'typed-release': 'workspace-typed-release-admin.js',
          'machine-updates': 'workspace-machine-updates-admin.js',
          'remote-a2a': 'workspace-remote-a2a-admin.js', 'protocol-conformance': 'workspace-protocol-conformance-admin.js',
          'reliability': 'workspace-reliability-admin.js', 'reliability-controls': 'workspace-reliability-controls-admin.js',
          'reliability-research': 'workspace-reliability-research-admin.js', 'research-controls': 'workspace-research-controls-admin.js',
          'growth': 'workspace-growth-admin.js', 'advancement': 'advancement-admin.js', 'product': 'workspace-product-admin.js',
          'agreement': 'workspace-agreement-admin.js', 'identity': 'workspace-identity-admin.js'}
WORDS = {
 'Private typed workflows':'워크플로 구성·실행', 'Close':'닫기', 'Workflow name':'워크플로 이름',
 'Typed graph definition':'워크플로 정의', 'Recorded agent and contract':'검증된 에이전트·계약',
 'Save new immutable version':'새 버전 저장', 'Review entire workflow':'전체 실행 내용 검토',
 'Disable selected workflow':'선택 워크플로 중지', 'Run reviewed workflow':'검토한 워크플로 실행',
 'New workflow':'새 워크플로', 'Add contract step':'에이전트 단계 추가', 'Open workflow':'워크플로 열기',
 'Inspect run':'실행 결과 보기', 'Refresh recorded state':'현재 기록 새로고침',
 'Read current lineage state':'현재 실행 증거 조회', 'Private typed execution evidence':'워크플로 실행 증거',
 'Close typed evidence':'닫기', 'Typed flow ':'워크플로 ', 'Signed execution ':'서명된 실행 ',
 'Choose a private typed flow':'워크플로 선택', 'Choose a signed execution':'실행 선택',
 'Current node consent and case references ':'노드별 동의·평가 참조 ',
 'Retain existing node sources':'기존 노드 원본 보관', 'Retained evidence':'보관된 증거',
 'Close evidence':'닫기', 'Evidence scope ':'증거 범위 ', 'Resource reference ':'에이전트 참조 ',
 'Read current evidence':'현재 증거 조회', 'Withdraw source':'증거 사용 철회',
 'Catalog administrative metadata':'카탈로그 관리 메타데이터', 'This workspace private executions':'이 워크스페이스의 비공개 실행',
 'Pre-run reservation and staff review':'실행 전 예약·직원 품질 검토', 'Refresh assignments':'검토 배정 새로고침',
 'Reserve a new case before execution':'실행 전 평가 예약', 'Read assignment state':'배정 상태 보기',
 'New retained private run ID':'새로 보관한 비공개 실행 ID', 'Bind retained run created after reservation':'예약 후 실행 연결',
 'Inspect assigned output':'배정된 결과 열기', 'Select private draft':'비공개 초안 선택',
 'Select active saved snapshot':'활성 스냅샷 선택', 'Frozen dataset SHA-256':'고정 데이터셋 SHA-256',
 'Frozen case SHA-256':'고정 평가 항목 SHA-256', 'Separate source bundle SHA-256':'별도 원본 묶음 SHA-256',
 'Opaque source reference':'원본 참조', 'Select two to four separate review accounts':'별도 검토자 2~4명 선택',
 'Reserve pre-run case':'실행 전 예약 등록', 'Back to assignments':'배정 목록으로',
 'Not assessed':'미평가', 'Source observation UTC (YYYY-MM-DDTHH:MM:SSZ)':'원본 확인 시각 UTC (YYYY-MM-DDTHH:MM:SSZ)',
 'Assessment notes or adjudication reason':'평가 메모·조정 사유', 'Record separate adjudication':'별도 조정 기록',
 'Record assigned review':'배정된 검토 기록',
 'I allow the exact literals and selected prior outputs to be shared with every listed agent for this one reviewed run.':'이번 검토된 실행에 한해 입력값과 선택한 이전 출력을 표시된 모든 에이전트에 공유하는 데 동의합니다.',
 ' Authorize encrypted retention of this existing run’s necessary node sources for the selected current evaluation purposes.':' 현재 평가 목적에 필요한 기존 실행의 노드 원본을 암호화해 보관하는 데 동의합니다.',
 'Withdraw this exact source from this workspace scope. This is permanent and does not delete or rewrite the original record.':'이 원본을 현재 워크스페이스 증거에서 영구 제외합니다. 원본 기록 자체를 삭제하거나 수정하지 않습니다.',
 'Open assigned private output and record this disclosure.':'배정된 비공개 결과를 열고 열람을 기록합니다.',
 'I reviewed the separately referenced source material.':'별도로 참조된 원본 자료를 확인했습니다.',
 'I declare no conflict with this execution or assessment.':'이 실행·평가에 이해 충돌이 없음을 확인합니다.',
 'Record this explicit staff judgment. This does not certify expert qualification or provider truth.':'직원의 판단을 기록합니다. 전문가 자격이나 제공자 정보의 진실성을 인증하지 않습니다.',
 'Reserve these exact hashes and separated account roles before creating the measured run. This is not independent holdout chronology proof.':'평가 실행 전에 이 해시와 분리된 계정 역할을 예약합니다. 독립적인 비공개 평가 시점의 증명은 아닙니다.',
}

WORDS.update({'Loading current workspace authority.': '현재 워크스페이스 권한을 확인하고 있습니다.',
 'No private typed workflow is saved. A current verified agent and contract approval are required.': '저장된 '
                                                                                                     '비공개 '
                                                                                                     '워크플로가 '
                                                                                                     '없습니다. '
                                                                                                     '현재 검증된 '
                                                                                                     '에이전트와 '
                                                                                                     '승인된 '
                                                                                                     '계약이 '
                                                                                                     '필요합니다.',
 'Provide a valid bounded typed graph.': '허용된 크기와 형식의 워크플로 정의를 입력하세요.',
 'Read-only stateless MCP agents with current recorded checks only. This editor grants no fallback, schedule, publication or result delivery. SDK 2 deployment requires a successful retained graph test and a separate owner review.': '현재 '
                                                                                                                                                                                                                                        '검증 '
                                                                                                                                                                                                                                        '기록이 '
                                                                                                                                                                                                                                        '있는 '
                                                                                                                                                                                                                                        '읽기 '
                                                                                                                                                                                                                                        '전용 '
                                                                                                                                                                                                                                        'MCP '
                                                                                                                                                                                                                                        '에이전트만 '
                                                                                                                                                                                                                                        '사용합니다. '
                                                                                                                                                                                                                                        '이 '
                                                                                                                                                                                                                                        '편집기는 '
                                                                                                                                                                                                                                        '폴백·예약·공개·결과 '
                                                                                                                                                                                                                                        '전달 '
                                                                                                                                                                                                                                        '권한을 '
                                                                                                                                                                                                                                        '부여하지 '
                                                                                                                                                                                                                                        '않습니다. '
                                                                                                                                                                                                                                        'SDK '
                                                                                                                                                                                                                                        '2 '
                                                                                                                                                                                                                                        '배포에는 '
                                                                                                                                                                                                                                        '성공한 '
                                                                                                                                                                                                                                        '실행 '
                                                                                                                                                                                                                                        '증거와 '
                                                                                                                                                                                                                                        '소유자의 '
                                                                                                                                                                                                                                        '별도 '
                                                                                                                                                                                                                                        '검토가 '
                                                                                                                                                                                                                                        '필요합니다.',
 'Running the reviewed private workflow.': '검토한 비공개 워크플로를 실행하고 있습니다.',
 'The change could not be confirmed. Refresh recorded state and inspect history before another action. Nothing is retried automatically.': '변경 '
                                                                                                                                           '결과를 '
                                                                                                                                           '확인하지 '
                                                                                                                                           '못했습니다. '
                                                                                                                                           '현재 '
                                                                                                                                           '기록을 '
                                                                                                                                           '새로고침하고 '
                                                                                                                                           '이력을 '
                                                                                                                                           '확인하세요. '
                                                                                                                                           '자동 '
                                                                                                                                           '재시도하지 '
                                                                                                                                           '않습니다.',
 'Up to ten read-only MCP steps. Private execution does not publish or deploy a workflow.': '읽기 전용 MCP 단계를 '
                                                                                            '최대 10개 연결합니다. '
                                                                                            '비공개 실행은 워크플로를 '
                                                                                            '공개하거나 배포하지 '
                                                                                            '않습니다.',
 'Saved immutable version selected. Review all destinations before authorizing a run.': '저장된 버전을 선택했습니다. 실행을 '
                                                                                        '승인하기 전에 모든 수신 에이전트를 '
                                                                                        '확인하세요.',
 'Private version saved. No provider was contacted.': '비공개 버전을 저장했습니다. 외부 에이전트는 호출하지 않았습니다.',
 'Review every agent, literal input, selected output field and condition. Consent applies to this one run only.': '모든 '
                                                                                                                  '에이전트, '
                                                                                                                  '입력값, '
                                                                                                                  '선택된 '
                                                                                                                  '출력 '
                                                                                                                  '필드와 '
                                                                                                                  '조건을 '
                                                                                                                  '확인하세요. '
                                                                                                                  '동의는 '
                                                                                                                  '이번 '
                                                                                                                  '실행 '
                                                                                                                  '한 '
                                                                                                                  '번에만 '
                                                                                                                  '적용됩니다.',
 'Workflow disabled. Pending and running work must pass current authority checks; external requests already sent cannot be recalled.': '워크플로를 '
                                                                                                                                       '중지했습니다. '
                                                                                                                                       '대기·진행 '
                                                                                                                                       '작업은 '
                                                                                                                                       '현재 '
                                                                                                                                       '권한을 '
                                                                                                                                       '다시 '
                                                                                                                                       '확인합니다. '
                                                                                                                                       '이미 '
                                                                                                                                       '전송된 '
                                                                                                                                       '외부 '
                                                                                                                                       '요청은 '
                                                                                                                                       '취소할 '
                                                                                                                                       '수 '
                                                                                                                                       '없습니다.',
 'Define reviewed typed nodes using the supported contracts. Saving never contacts an agent.': '지원 계약으로 노드를 '
                                                                                               '구성하세요. 저장만으로 '
                                                                                               '에이전트를 호출하지 '
                                                                                               '않습니다.',
 'Contract step added locally. Review its literal input and any explicit prior-output bindings before saving.': '단계를 '
                                                                                                                '편집기에 '
                                                                                                                '추가했습니다. '
                                                                                                                '저장 '
                                                                                                                '전에 '
                                                                                                                '입력값과 '
                                                                                                                '이전 '
                                                                                                                '출력 '
                                                                                                                '연결을 '
                                                                                                                '검토하세요.',
 'Select a recorded agent and keep a valid graph with fewer than ten steps.': '검증된 에이전트를 선택하고 추가 전 단계 수를 10개 '
                                                                              '미만으로 유지하세요.',
 'Authenticated source encryption is not configured. Retention remains unavailable.': '원본 암호화가 설정되지 않아 보관 '
                                                                                      '기능을 사용할 수 없습니다.',
 'Authority or signed execution evidence is unavailable.': '현재 권한 또는 서명된 실행 증거를 확인할 수 없습니다.',
 'Choose an execution and select the purpose-specific retention authorization.': '실행을 선택하고 해당 목적의 보관 동의를 '
                                                                                 '확인하세요.',
 'Current private executions could not be read.': '현재 비공개 실행을 조회하지 못했습니다.',
 'Current retained sources are available. Independent quality remains separate.': '현재 유효한 보관 원본이 있습니다. 독립적인 '
                                                                                  '품질 평가는 별도입니다.',
 'Existing sources retained under current permission. No provider calls were made.': '현재 동의 범위에서 기존 원본을 '
                                                                                     '보관했습니다. 외부 호출은 없었습니다.',
 'Private typed lineage ready. No provider calls were made.': '비공개 실행 증거를 조회했습니다. 외부 호출은 없었습니다.',
 'Provide the exact bounded node references.': '허용된 노드 참조를 정확히 입력하세요.',
 'Reading current typed lineage authority.': '현재 실행 증거 조회 권한을 확인하고 있습니다.',
 'Review existing signed executions. Retention uses each node’s current cohort permission and makes no provider calls. Quality and business outcomes remain independently unassessed.': '기존 '
                                                                                                                                                                                        '서명된 '
                                                                                                                                                                                        '실행을 '
                                                                                                                                                                                        '검토합니다. '
                                                                                                                                                                                        '원본 '
                                                                                                                                                                                        '보관에는 '
                                                                                                                                                                                        '각 '
                                                                                                                                                                                        '노드의 '
                                                                                                                                                                                        '현재 '
                                                                                                                                                                                        '평가 '
                                                                                                                                                                                        '동의를 '
                                                                                                                                                                                        '사용하며 '
                                                                                                                                                                                        '외부 '
                                                                                                                                                                                        '호출은 '
                                                                                                                                                                                        '하지 '
                                                                                                                                                                                        '않습니다. '
                                                                                                                                                                                        '품질과 '
                                                                                                                                                                                        '사업 '
                                                                                                                                                                                        '성과는 '
                                                                                                                                                                                        '별도 '
                                                                                                                                                                                        '평가가 '
                                                                                                                                                                                        '필요합니다.',
 'Session or scoped access changed. Close and reopen this view.': '세션 또는 접근 권한이 변경됐습니다. 화면을 닫고 다시 여세요.',
 'Source fidelity is unassessable until current permitted sources are retained.': '현재 동의된 원본을 보관하기 전에는 원본 '
                                                                                  '충실도를 평가할 수 없습니다.',
 'The capture could not be confirmed. Read current state before submitting again.': '보관 결과를 확인하지 못했습니다. 다시 '
                                                                                    '요청하기 전에 현재 상태를 조회하세요.',
 'The current staff session or private workspace is unavailable.': '현재 직원 세션 또는 비공개 워크스페이스를 확인할 수 없습니다.',
 'Current retained evidence loaded. No provider calls were made.': '현재 보관된 증거를 조회했습니다. 외부 호출은 없었습니다.',
 'Current session or scoped evidence access changed. Close and reopen this view.': '현재 세션 또는 증거 접근 권한이 '
                                                                                   '변경됐습니다. 화면을 다시 여세요.',
 'Enter one valid catalog resource reference.': '유효한 에이전트 참조 하나를 입력하세요.',
 'Insufficient evidence: no eligible retained observations are available.': '증거 부족: 유효한 보관 관측 기록이 없습니다.',
 'Insufficient evidence: the metadata sample threshold is not met.': '증거 부족: 메타데이터 표본 수가 기준에 미달합니다.',
 'Quality is unassessed. Retained metadata does not establish source fidelity, independent review, operating quality or an execution permission.': '품질은 '
                                                                                                                                                   '미평가 '
                                                                                                                                                   '상태입니다. '
                                                                                                                                                   '보관된 '
                                                                                                                                                   '메타데이터만으로 '
                                                                                                                                                   '원본 '
                                                                                                                                                   '충실도·독립 '
                                                                                                                                                   '검토·운영 '
                                                                                                                                                   '품질·실행 '
                                                                                                                                                   '권한을 '
                                                                                                                                                   '인정하지 '
                                                                                                                                                   '않습니다.',
 'Read current retained evidence for the selected scope.': '선택한 범위의 현재 보관 증거를 조회하세요.',
 'Reading available evidence scopes.': '접근 가능한 증거 범위를 확인하고 있습니다.',
 'Revalidating current authority, version, retention and expiry.': '현재 권한·버전·보관·만료 상태를 다시 확인하고 있습니다.',
 'The evidence result could not be confirmed. Read current state before any new request.': '증거 조회 결과를 확인하지 '
                                                                                           '못했습니다. 다음 요청 전에 '
                                                                                           '현재 상태를 확인하세요.',
 'This bounded view is truncated. Counts describe the retained sources inspected here, not all history.': '표시 '
                                                                                                          '한도에 '
                                                                                                          '도달했습니다. '
                                                                                                          '수치는 '
                                                                                                          '이 '
                                                                                                          '화면에서 '
                                                                                                          '확인한 '
                                                                                                          '보관 '
                                                                                                          '원본 '
                                                                                                          '기준이며 '
                                                                                                          '전체 '
                                                                                                          '이력이 '
                                                                                                          '아닙니다.',
 'Withdrawal could not be confirmed. Read current evidence before trying another command.': '철회 결과를 확인하지 '
                                                                                            '못했습니다. 다른 조치 전에 '
                                                                                            '현재 증거를 조회하세요.',
 'Application pre-run reservation and staff judgments. Expert qualifications, source review, unseen status and actual independence need separate evidence. No model or provider is called here.': '실행 '
                                                                                                                                                                                                  '전 '
                                                                                                                                                                                                  '예약과 '
                                                                                                                                                                                                  '직원 '
                                                                                                                                                                                                  '판단을 '
                                                                                                                                                                                                  '기록합니다. '
                                                                                                                                                                                                  '전문가 '
                                                                                                                                                                                                  '자격·원본 '
                                                                                                                                                                                                  '검토·비공개 '
                                                                                                                                                                                                  '평가 '
                                                                                                                                                                                                  '여부·독립성에는 '
                                                                                                                                                                                                  '별도 '
                                                                                                                                                                                                  '증거가 '
                                                                                                                                                                                                  '필요합니다. '
                                                                                                                                                                                                  '이 '
                                                                                                                                                                                                  '화면에서는 '
                                                                                                                                                                                                  '모델이나 '
                                                                                                                                                                                                  '외부 '
                                                                                                                                                                                                  '에이전트를 '
                                                                                                                                                                                                  '호출하지 '
                                                                                                                                                                                                  '않습니다.',
 'Current review scope is unavailable. Reopen after checking the session and membership.': '현재 검토 범위를 확인할 수 '
                                                                                           '없습니다. 세션과 멤버십을 '
                                                                                           '확인한 후 다시 여세요.',
 'No reserved cases. A historical run cannot be backdated into a new reservation.': '예약된 평가가 없습니다. 과거 실행을 새 '
                                                                                    '예약보다 나중에 수행한 것으로 처리할 수 '
                                                                                    '없습니다.',
 'Provide an explicit finite UTC source observation time.': '원본 확인 시각을 유효한 UTC 형식으로 입력하세요.',
 'Recording one explicitly reviewed request.': '명시적으로 검토한 요청을 기록하고 있습니다.',
 'Scoped quality review': '권한 범위 내 품질 검토',
 'The result is not confirmed. Read current assignment state; no request is retried automatically.': '결과를 '
                                                                                                     '확인하지 '
                                                                                                     '못했습니다. '
                                                                                                     '현재 배정 '
                                                                                                     '상태를 '
                                                                                                     '조회하세요. '
                                                                                                     '자동 '
                                                                                                     '재시도하지 '
                                                                                                     '않습니다.'})


def build(kind, filename):
    source = (ROOT / 'agent_market/gateway' / filename).read_text()
    source = source.replace("(()=>{'use strict';", '(() => {')
    source = source.replace('(() => {', 'export function createPanel({api, scopeIdentity, currentUser, isCurrent, decorate, navigatePanel}) {', 1)
    source = source.rsplit('})();', 1)[0] + '}\n'
    source = source.replace("  'use strict';\n", '')
    # These are static, reviewed shell substitutions, never runtime code rewriting.
    import re
    source = re.sub(r"typeof token\s*===\s*'string'\s*&&\s*(?:typeof currentUser\s*!==\s*'undefined'\s*&&\s*)?currentUser\s*\?\s*`\$\{token\}\|\$\{currentUser.user_id\}\|\$\{currentUser.role\}`\s*:\s*''", 'scopeIdentity()', source)
    source = source.replace("state.tab==='workspaces'", 'isCurrent()')
    source = source.replace("&&document.getElementById('workspaceSelect')?.value===scope?.ws", '')
    source = source.replace("&&document.getElementById('workspaceSelect')?.value===workspace", '')
    source = source.replace("document.getElementById('workspaceSelect')?.value !== workspace", '!isCurrent()')
    source = source.replace(" && document.getElementById('workspaceSelect')?.value === workspace", ' && isCurrent()')
    source = source.replace("if (!identity() || document.getElementById('workspaceSelect')?.value !== id) return;", "if (!identity() || !/^ws_[a-f0-9]{32}$/.test(id)) return;")
    source = source.replace("const selected=document.getElementById('workspaceSelect');", "const selected=null;")
    source = source.replace("'/admin/api/workflow-workspaces/'", "'/admin/api/v2/workspace-panels/'")
    # Calls to drafts/snapshots still go through the original read-only endpoints.
    source = source.replace('}/reliability/typed', '}/reliability/typed').replace('}/evidence', '}/evidence')
    for name in ('reliability/typed', 'evidence', 'quality', 'machine-updates', 'remote-a2a', 'protocol-conformance', 'reliability', 'advancement', 'provider-claims'):
        source = source.replace('`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/'+name,
                                '`/admin/api/v2/workspace-panels/${encodeURIComponent(workspace)}/'+name)
        source = source.replace('`/admin/api/workflow-workspaces/${encodeURIComponent(ws)}/'+name,
                                '`/admin/api/v2/workspace-panels/${encodeURIComponent(ws)}/'+name)
    source = source.replace("className='btn'", "className='adm-btn'").replace("className = 'btn'", "className = 'adm-btn'")
    source = source.replace("className='card'", "className='adm-card'").replace("className = 'card'", "className = 'adm-card'")
    source = source.replace("className = 'row'", "className = 'adm-filters'").replace("className='row'", "className='adm-filters'")
    source = source.replace("className='workspace-dialog'", "className='adm-specialist-dialog'")
    source = source.replace('dialog.showModal();', 'decorate(dialog);dialog.showModal();')
    if kind == 'flow':
        source = source.replace('decorate, navigatePanel}) {', 'decorate, navigatePanel, initialFlow}) {', 1)
        source = source.replace("if(!result.flows.length)list.append(el('p','No private typed workflow is saved. A current verified agent and contract approval are required.'));","if(!result.flows.length)list.append(el('p','No private typed workflow is saved. A current verified agent and contract approval are required.'));if(initialFlow&&!selected){const chosen=result.flows.find(f=>f.id===initialFlow);if(chosen){busy=false;await choose(chosen);busy=true;}}")
        source = source.replace('let canEdit=false;', "const preview=el('div');preview.className='adm-typed-preview';function renderPreview(run=null){try{preview.replaceChildren(typedPreview(JSON.parse(graph.value),run));}catch{preview.replaceChildren(el('p','유효한 워크플로 정의를 입력하면 단계 흐름이 표시됩니다.'));}}let canEdit=false;")
        source = source.replace('const reset=()=>{clearReview();', 'const reset=()=>{renderPreview();clearReview();')
        source = source.replace('function showResult(value){output.replaceChildren();','function showResult(value){renderPreview(value);output.replaceChildren();')
        source = source.replace('graph.value=JSON.stringify(selected.definition,null,2);', 'graph.value=JSON.stringify(selected.definition,null,2);renderPreview();')
        source = source.replace('add,graphLabel,save,', 'add,preview,graphLabel,save,')
        source = source.replace('||!window.WorkspaceTypedReleaseAdmin', '')
        source = re.sub(r"    const exportTyped=button\('Manage typed SDK 2 deployment'.*?;\n", "    const exportTyped=button('다단계 배포 관리',()=>{leave();navigatePanel('typed-release');});\n", source)
        start = source.index('  function select(ws,canEdit)')
        source = source[:start] + "  return {open: ws => {workspace=ws;return open();}, leave};\n}\n"
    elif kind == 'release':
        source = source.replace("const mount=document.getElementById('workspaceReleaseMount');if(!mount)return;", "const mount=document.createElement('div');")
        source = source.replace("currentUser?token+'|'+currentUser.user_id+'|'+currentUser.role:''", 'scopeIdentity()')
        source = source.replace('||!token', '||!scopeIdentity()')
        source = source.replace("api(path()+'/release-v2'", "api(path().replace('/admin/api/workflow-workspaces','/admin/api/v2/workspace-panels')+'/release-v2'")
        source = source.replace("api(path()+'/release-v2/deployments/'", "api(path().replace('/admin/api/workflow-workspaces','/admin/api/v2/workspace-panels')+'/release-v2/deployments/'")
        source = source.replace("api(BASE+'/'+scope.workspace_id+'/lifecycle/", "api('/admin/api/v2/workspace-panels/'+scope.workspace_id+'/lifecycle/")
        # Only release paths use the alias; execution history remains a private GET.
        source = source.replace("api(path()+'/execution/runs'", "api(path().replace('/admin/api/v2/workspace-panels','/admin/api/workflow-workspaces')+'/execution/runs'")
        start = source.index("window.addEventListener('pagehide'")
        source = source[:start] + "return {open: async value=>{select(value);user=identity();decorate(dialog);dialog.showModal();await load();}, leave:()=>{clear();dialog.remove();scope=null;}};\n}\n"
    elif kind == 'remote-a2a':
        source = source.replace('encodeURIComponent(mark.workspace)', 'encodeURIComponent(workspace)')
        source = source.replace('`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}/remote-a2a', '`/admin/api/v2/workspace-panels/${encodeURIComponent(workspace)}/remote-a2a')
        start = source.index("  document.getElementById('workspaceSelect')?.addEventListener")
        source = source[:start] + '  return {open, leave, onSession};\n}\n'
    elif kind in ('research-controls', 'growth'):
        source = source.replace('`/admin/api/workflow-workspaces/${encodeURIComponent(workspace)}${path}', '`/admin/api/v2/workspace-panels/${encodeURIComponent(workspace)}${path}')
        start = source.index('  window.' + ('WorkspaceGrowthAdmin' if kind == 'growth' else 'WorkspaceResearchControlsAdmin'))
        source = source[:start] + '  return {open, leave, onSession};\n}\n'
    elif kind == 'advancement':
        source = source.replace("input.type='checkbox';input.checked=false;", "input.type='checkbox';input.checked=false;input.dataset.purposeConsent='true';")
        source = source.replace("enabled.input.checked=false;", "enabled.input.checked=false;delete enabled.input.dataset.purposeConsent;")
        source = source.replace("button('Provider agreements',()=>{const selected=ws;leave();window.WorkspaceAgreementAdmin?.open(selected);})", "button('Provider agreements',()=>{leave();navigatePanel('agreement');})")
        start = source.index('  window.AdvancementAdmin')
        source = source[:start] + '  return {open, leave, onSession};\n}\n'
    elif kind == 'product':
        source = source.replace("const mount=document.getElementById('workspaceProductMount');if(!mount)return;", "const mount=document.createElement('div');let expiryTimer=null;")
        source = source.replace("currentUser?token+'|'+currentUser.user_id+'|'+currentUser.role:''", 'scopeIdentity()')
        source = source.replace('||!token', '||!scopeIdentity()')
        source = source.replace("function clear(){invalidate();", "function clear(){clearInterval(expiryTimer);expiryTimer=null;invalidate();")
        source = source.replace("function base(){return BASE+'/'+scope.workspace_id;}", "function base(){return '/admin/api/v2/workspace-panels/'+scope.workspace_id;}")
        source = source.replace("api(base()+'/drafts/'", "api(base().replace('/admin/api/v2/workspace-panels','/admin/api/workflow-workspaces')+'/drafts/'")
        start = source.index("open.addEventListener('click'")
        source = source[:start] + "return {open:async ws=>{select({workspace_id:ws,can_edit:true});user=identity();decorate(dialog);dialog.showModal();expiryTimer=setInterval(()=>{if(dialog.open)controls();},1000);await load();},leave:()=>{clear();dialog.remove();scope=null;}};\n}\n"
    elif kind == 'identity':
        start = source.index("  window.addEventListener('pagehide'")
        source = source[:start] + '  return {open, leave, onSession:()=>{if(session&&session!==current())leave();}};\n}\n'
    elif kind == 'agreement':
        source = source.replace("const selected = document.getElementById('workspaceSelect');", "const selected = null;")
        start = source.index('  window.WorkspaceAgreementAdmin')
        source = source[:start] + '  return {open, leave, onSession};\n}\n'
    elif kind == 'typed-release':
        start = source.index("  window.addEventListener('pagehide'")
        source = source[:start] + '  return {open, leave};\n}\n'
    else:
        start = source.index('  window.' + {'lineage':'WorkspaceTypedEvidenceAdmin','evidence':'WorkspaceEvidenceAdmin','quality':'WorkflowQualityReviewAdmin','machine-updates':'WorkspaceMachineUpdatesAdmin','protocol-conformance':'WorkspaceProtocolConformanceAdmin','reliability':'WorkspaceReliabilityAdmin','reliability-controls':'WorkspaceReliabilityControlsAdmin','reliability-research':'WorkspaceReliabilityResearchAdmin'}[kind])
        source = source[:start] + '  return {open, leave, onSession};\n}\n'
    for english, korean in (WORDS | RELEASE_WORDS | PROTOCOL_WORDS | RELIABILITY_WORDS | (GROWTH_WORDS if kind in ('growth', 'advancement', 'product') else {}) | (IDENTITY_WORDS if kind in ('agreement', 'identity') else {})).items():
        source = source.replace("'" + english + "'", "'" + korean + "'")
    # Normalize old visual tokens to the shared pearl surface without altering CSP.
    for old, new in [('var(--bg)', 'var(--adm-bg)'), ('var(--text)', 'var(--adm-text)'),
                     ('var(--line)', 'var(--adm-line)'), ('var(--panel)', 'var(--adm-panel)'),
                     ('var(--text,#172235)', 'var(--adm-text)'), ('var(--card,#fff)', 'var(--adm-panel)'),
                     ('var(--border,#dce3ee)', 'var(--adm-line)')]:
        source = source.replace(old, new)
    if kind in ('growth', 'advancement', 'product', 'agreement', 'identity'):
        for old, new in [('var(--bg,Canvas)', 'var(--adm-bg)'), ('var(--panel,Canvas)', 'var(--adm-panel)'), ('var(--text,CanvasText)', 'var(--adm-text)'), ('var(--panel, Canvas)', 'var(--adm-panel)'), ('var(--text, CanvasText)', 'var(--adm-text)')]:
            source = source.replace(old, new)
    if kind == 'remote-a2a':
        source = source.replace('var(--border, #cbd5e1)', 'var(--adm-line)').replace('var(--text, #172235)', 'var(--adm-text)').replace('var(--surface, Canvas)', 'var(--adm-panel)')
    return '// Generated by scripts/build_admin_specialist_panels.py; edit the source controller or build adapter.\n' + ("import {typedPreview} from '../core/typed-preview.js';\n" if kind == 'flow' else '') + source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    changed = []
    for kind, filename in PANELS.items():
        target = ROOT / 'agent_market/gateway/admin_next/areas' / ('panel-' + kind + '.js')
        source = build(kind, filename)
        if not target.exists() or target.read_text() != source:
            changed.append(kind)
            if args.write:
                target.write_text(source)
    print({'changed': changed, 'written': args.write})
    return 0 if args.write or not changed else 1


if __name__ == '__main__':
    raise SystemExit(main())
