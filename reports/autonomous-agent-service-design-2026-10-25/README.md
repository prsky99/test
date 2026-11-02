# Agent Concierge 자율형 Agent 서비스 통합 설계

> 후속 상세 설계: [Autonomous Agent Adoption Design v1.1](../../docs/AUTONOMOUS_AGENT_ADOPTION_DESIGN.md). 생태계 연결·JIT 준비/승인/실행·변경 피드·의존성 감시·OpenAPI/RateLimit·게시 준비를 AE-01~AE-08로 구체화했다. v1.1은 고정된 5개 도구·조건부 Schema·batch/캐시·공통 사건과 비교 실험으로 효율을 보완하며 개발 단계는 8개로 유지한다. 기존 구현을 재사용하고 이 링크는 신규 기능 구현/성능 실증 완료를 의미하지 않는다.

> 구현 현황: 첫 안내·Workflow 목적 검색·Chat/MCP/A2A 추천·세션 재방문 문맥은 개발해 운영에 반영했다. 전체 설계 중 나머지 Task·compact profile·Edge ingress 등과 구분하며 [개발 결과](<저장소>/reports/autonomous-agent-development-2026-10-25/README.md)를 기준으로 확인한다. 사용자 확정 정책은 모든 실행 결과의 Edge 우선·실패 시 Origin 폴백이다.

설계 기준일: **2026-10-25, Asia/Seoul**. 대상은 외부 자율형 Agent가 Agent Concierge를 발견하고, 필요한 Agent·Workflow를 선택하고, 허용된 업무를 실행한 뒤 다시 이용하는 전체 여정이다.

**서비스의 중심을 “Agent 목록 검색”에서 “필요한 능력과 실행 가능한 업무 경로를 빠르게 받는 서비스”로 확장한다.** 외부 Agent는 계획을 유지하고, Concierge는 발견·선택·연결·실행권·결과 증거·재방문 정보를 일관되게 제공한다.

이 문서는 **개발 설계**다. 신규 API·기능·성능 목표·일정은 제안이며, 현재 운영에 구현되었다는 의미로 사용하지 않는다. 완성도는 아래 계약과 출시 검사로 판정한다. 설계만으로 실제 Provider 성공·무결점·비용 제로를 보장하지 않는다.

## 현재 출발점

[방문 경험 검증](<저장소>/reports/autonomous-visit-audit-2026-10-25/README.md)에서 공개 HTTP 27건, Computer Use 화면, 격리 검사 43개를 확인했다. 개별 Agent의 한글·영문 탐색과 날씨·논문 추천, 세션 후속 명령이 동작했다. 현재 공개 Workflow는 3개이며 `research`는 검색되지만 `papers`·한글·자연어 템플릿 요청은 놓쳤다.

이미 있는 기반을 재사용한다. Visitor 문맥, MCP 단일 도구 계약, Registry의 버전·Schema·증거, 공개 Workflow Runtime, Workspace 권한, 목적별 Machine 알림, 원격 A2A Task, Edge Ticket과 중복 실행 보호가 해당한다. 외부 유입·홍보 성과, 자연어 템플릿 추천, 목적별 첫 안내·재방문 정보는 추가 설계가 필요하다.

## 최종 사용자 경험

Agent가 “기술 뉴스와 관련 논문을 정리해줘”라는 업무를 맡았다고 가정한다.

1. 검색·공식 Registry·개발자 설정 예시에서 Concierge를 발견한다.
2. 짧은 기계용 안내에서 `find_agent`, `find_workflow`, `resume_task` 등 목적별 다음 행동을 읽는다.
3. “개별 도구가 필요한지, 연결된 Workflow가 필요한지”를 구분해 요청한다. 모호하면 선택지 한 번으로 확인한다.
4. 이미 공개된 뉴스·연구 Workflow와 추천 이유, 필요한 입력, 출력 구조, 실행 준비 상태를 받는다.
5. 상세 Schema와 데이터 전달 대상을 확인한다. 실행을 원하면 서버가 확인한 권한과 입력에 결합된 실행권을 받는다.
6. 허용된 실행만 시작하고 상태·부분 결과·최종 결과를 조회한다. 응답을 잃으면 기존 실행을 조회한다.
7. 유용했던 작업은 안정적인 작업 참조로 저장한다. 다음 방문에는 문서 전체를 다시 읽지 않고 이전 작업을 재개하거나 변경된 증거만 받는다.
8. 승인한 경우에만 관련 변경을 알린다. 외부 Agent는 그 결과를 다음 계획에 활용한다.

출력물은 실행 결과 외에도 유용하다. Agent·템플릿·Schema·입력 예시·실행 가능 조건만 받아 외부 Agent가 자기 환경에서 이어갈 수 있다. 실행권이 없으면 탐색과 준비까지 완료한다.

## 설계를 결정한 연구와 반례

- [ToolRet](https://arxiv.org/abs/2503.01763)은 일반 검색 성능을 도구 선택 성능으로 대체하기 어렵다는 근거다. Concierge 전용 정답셋으로 선택 품질을 측정한다.
- [도구 문서 확장 연구](https://arxiv.org/abs/2510.22670)는 구조화된 설명 보강을 다룬다. 원본 Schema에 근거한 용도·입출력·동의어·제약을 색인하고, 생성한 설명은 검증 사실과 분리한다.
- [Anthropic의 advanced tool use](https://www.anthropic.com/research/advanced-tool-use)는 필요한 도구 정의를 나중에 불러오는 접근을 제시한다. 기본 도구 수를 작게 유지하고 선택한 대상만 상세화한다.
- [Cloudflare Code Mode](https://blog.cloudflare.com/code-mode/)는 여러 호출을 코드에서 조합하는 방식을 설명한다. 초기에는 검증된 typed Workflow를 실행하고, 임의 코드는 별도 sandbox 단계로 확장한다.
- [τ-bench](https://arxiv.org/abs/2406.12045)는 대화 마지막의 실제 상태와 반복 성공을 평가한다. HTTP 200과 실제 목적 달성을 나눠 검사한다.
- [ExoFlow](https://www.usenix.org/conference/osdi23/presentation/zhuang)의 실행·복구 분리는 durable 실행권을 유지하는 판단에 참고한다. 외부 Provider 부작용까지 자동 exactly-once라고 선언하지 않는다.
- [AgentDojo](https://arxiv.org/abs/2406.13352)와 [MCP 보안 지침](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)은 도구 응답의 신뢰 경계·권한·SSRF·token 전달 검사의 근거다.
- SNS에는 [lexical 검색이 semantic 검색보다 나았다는 제작자 경험](https://www.reddit.com/r/mcp/comments/1uirauu/tool_selection_at_scale_is_a_retrieval_problem/)과 [동적 도구 검색 추가가 작은 실험에서 오히려 악화됐다는 사례](https://www.reddit.com/r/ClaudeAI/comments/1pbhylx/an_attempt_to_replicate_and_benchmark_the_tool/)가 있다. 이를 일반 법칙으로 적용하지 않고 단순 경로와 확장 경로를 비교하는 실험 가설로 사용한다.

자료별 판단·적용·한계는 [조사 근거](RESEARCH.md)에 정리했다. 공급사의 개선율이나 SNS의 수치를 우리 서비스 성과로 옮기지 않는다.

## 외부 Agent가 실제로 발견하도록 만드는 방법

### 공식 입구와 배포 경로

공개 `/.well-known/agent-card.json`, MCP manifest, `llms.txt`, OpenAPI, sitemap을 동일한 계약에서 생성한다. 새로운 custom 안내 `/.well-known/agent-entry.json`을 추가하되 자체 형식임을 명시한다. 표준 프로토콜 이름으로 오인시키지 않는다.

공식 MCP Registry에 게시할 remote server 설명과 저장소·namespace 소유권 증거를 준비한다. 등록은 운영자의 실제 게시 작업으로 진행한다. Registry의 namespace 확인은 원격 endpoint의 품질·도메인 소유권·업무 성공 인증과 구분한다. [공식 remote server 등록 안내](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/remote-servers.mdx)

추가 디렉터리는 검색·개발자 사용 흔적·유입 품질을 확인해 선택한다. 대량 디렉터리 등록보다 “실제로 설치하고 첫 추천에 성공하는 경로”를 우선한다. 공개 Git 저장소의 연결 예시, TypeScript·Python의 작은 공식 client, REST/curl 예시를 같은 버전으로 관리한다. 패키지 배포·Registry 게시·외부 발송은 이 설계에서 실행하지 않는다.

### 검색에 노출할 가치 있는 내용

처음에는 실제 기능을 설명하는 목적별 공개 가이드를 만든다. 예: `find a research agent`, `find a workflow for technology news`, `review package advisories`, `resume an agent task`. 각 가이드에는 입력·실제 공개 템플릿·예상 출력 형식·연결 예시·검증 범위를 담는다. 사용자 질의나 개인 작업을 공개 페이지로 만들지 않는다.

과도한 수의 유사 페이지를 생성하는 대신 기존 Learn·About·Explore·Workflows와 canonical 관계를 유지한다. 공개 문서와 제품 문구는 English로 작성하고 입력은 한글을 포함해 지원한다. 검색 등록 여부, 크롤링, 연결 설정 열람, 첫 검색 성공, 반복 사용은 서로 다른 지표로 기록한다.

### 체험이 설치로 이어지는 경로

세 가지 대표 업무를 “Golden Journey”로 제공한다. 뉴스→논문, 국가→지표, 패키지→보안 권고다. 문서를 읽는 것만으로 무료 예시 결과와 입력 구조를 이해할 수 있게 하고, live 결과·저장된 예시·mock 결과를 명확히 구분한다. Provider 업무 실행은 별도 실행권을 확인한다.

Agent 개발자에게 “Concierge 연결 1회 → 발견 도구 1회 → 관련 후보와 호출 Schema 수신”이라는 최소 설치 여정을 준다. 일반 설치가 끝났다는 이유로 지갑·Workspace·광고 권한을 요청하지 않는다. 공개 호출 예시에는 운영 Secret이나 실제 사용자 token을 넣지 않는다.

## 첫 방문: 짧게 이해하고 바로 목적을 선택

### 단계별 정보량

첫 응답은 서비스 목적, 사용 가능한 동작, 현재 지원 프로토콜, 권한 필요 여부, 다음 호출의 필수 입력만 담는다. 설계 목표는 기본 기계용 안내를 대표 tokenizer 기준 1,500 token 이하로 유지하는 것이다. 기존 문서 전체를 모든 요청에 붙이지 않는다.

세 층으로 정보를 제공한다.

1. **Entry:** 어떤 서비스를 할 수 있는지와 목적별 `quick_actions`.
2. **Discover:** 관련 Agent 또는 Workflow 하나, 추천 이유, 입력 요약·준비 상태.
3. **Describe:** 선택한 대상의 전체 입력·출력 Schema, 버전·검증 근거·실행 제약.

`quick_actions`에는 기계가 사용할 `action`, `method`, 플랫폼 상대 경로, 필수 입력, 상세 문서, 현재 사용 가능 상태를 담는다. 새 기능이 비활성이면 `unavailable`과 사유를 표시한다. bearer token과 임시 실행권은 URL에 넣지 않는다. 미구현 기능을 실행 가능한 항목으로 광고하지 않는다.

### 첫 응답의 목적별 선택

권장 동작은 `find_agent`, `find_workflow`, `describe_resource`, `resume_task`, `get_updates`다. 첫 문장은 “필요한 능력 또는 연결된 Workflow를 설명하세요”로 확장한다. 예시는 단일 도구, 연결된 업무, 이전 작업 재개를 각각 하나씩만 보여준다.

Anonymous Agent는 공개 검색·상세 확인을 사용할 수 있다. 세션 생성은 첫 상호작용에서 수행하고, 읽기 전용 Entry 조회마다 지속 계정을 만들지 않는다. 계정·Workspace 권한은 별도 인증과 소유자 승인으로 연결한다. `User-Agent`나 Agent가 직접 주장한 이름은 권한·신뢰의 근거로 사용하지 않는다.

기존에 허용한 공개 도구 실행을 모두 로그인 뒤로 옮기지는 않는다. 운영자가 승인한 공개 저위험 실행 정책, 검증된 도구 계약, 공개 입력·무결제·제한된 호출 예산을 충족하면 세션에 결합된 단일 목적 실행권을 서버가 발급할 수 있다. 사용자의 별도 승인이나 기존 Workspace grant가 필요한 업무는 그 범위를 따로 확인한다. 사람의 클릭을 매 조회마다 요구하는 대신 공개 정책과 명시적 위임 안에서 Agent가 실제로 일을 진행하게 한다.

## 같은 목적을 어느 입구에서도 같은 의미로 처리

REST·MCP·A2A·Chat·Explore·Workflow 화면이 **공통 Task Router와 Capability Catalog**를 사용한다. 인터페이스별 출력 모양은 달라도 해석·권한·검색·검증 근거는 공유한다.

정규화한 요청에는 목표, `resource_type=agent|workflow|auto`, 명시적 Protocol 선택, 입력·출력 요구, 데이터 민감도, 허용한 실행 범위, 응답 상세 수준을 담는다. `auto`는 요청 종류의 분류에만 사용하며 실행 권한을 만들지 않는다.

### Protocol 처리

- 개별 Agent 추천은 기존 규칙을 유지한다. 명시적 선택이 우선하고, 새 요청의 기본은 A2A, 명시적 Any는 A2A·MCP·x402 전체다. 후속 세부 조회·대체 후보는 이전 선택을 유지한다.
- Workflow는 연결된 노드들의 Protocol을 별도 `node_protocols`로 표현한다. 템플릿 요청에서 명시적 Protocol 제약이 있으면 노드 호환성을 검사한다. 충돌하면 `protocol_mismatch`와 선택지를 반환한다.
- 개별 Agent 추천용 A2A 기본값을 템플릿 노드의 암묵적 허가로 전환하지 않는다. Protocol을 생략한 템플릿 탐색은 공개 템플릿의 연결 종류를 설명하고, 실행 시 실제 각 Provider와 데이터 전달 범위를 승인받는다.
- 외부 Agent와 Concierge 사이의 MCP/A2A는 **접속 Protocol**, 추천 대상이나 Workflow 노드의 Protocol은 **대상 Protocol**이다. 두 항목을 섞지 않는다.

### 빠른 분류와 확인 질문

`workflow/template/chain`, “워크플로우/템플릿/연결해서” 같은 명확한 표현은 결정적인 규칙으로 처리한다. 도메인·언어별 동의어는 버전 관리한다. 모호할 때만 제한된 분류기·LLM을 사용하며 신뢰 수준이 낮으면 “Agent 하나 / 기존 Workflow / 새로운 Workflow 설계”의 짧은 선택지를 한 번 제시한다.

실행·게시·외부 전송 같은 의도가 탐색 문장에 들어 있어도 검색 단계는 계획만 반환한다. 모델 출력은 라우팅 제안이며 서버 정책과 현재 권한이 실행을 결정한다.

## Agent와 Workflow의 공통 검색

### 실제 계약을 기반으로 색인

Agent 문서에는 이름·설명·도구명·입력 필드·출력 형식·사용 목적·제약·지원 Protocol·Schema 버전·검증 범위를 담는다.

Workflow 문서에는 위 내용에 더해 노드 이름·기능, 데이터 연결, 외부 입력, 최종 출력, 관련 업무, 사용 예시, 실패·부분 성공 조건, 실행 가능 상태를 담는다. 따라서 Research Papers 노드가 있는 템플릿은 `papers`, “논문”, “학술자료”로 찾을 수 있어야 한다.

Provider 설명과 Schema는 신뢰하지 않는 데이터다. LLM으로 보강한 설명에는 `inferred` 출처를 붙이고 검색 보조로만 사용한다. 검증 근거나 실행 가능한 도구·권한을 생성하지 않는다. Schema 변화 시 이전 검색 색인·실행 준비 결과를 무효화한다.

### 작은 목록은 단순하게, 큰 목록은 단계적으로

공개 템플릿 3개는 전체 정규화 문서를 메모리에 올려 동의어·토큰·입출력 조건으로 점수화하는 방식부터 시작한다. 이를 위해 별도 Vector DB나 매 요청 LLM을 추가하지 않는다.

대형 Agent Catalog에는 현재 PostgreSQL·lexical·선택적 embedding 기반을 재사용한다. 명확한 고유 도구명·필드명은 lexical 우선, 표현 차이가 큰 요청은 semantic 후보를 보충한다. 두 방식의 합집합을 공통 relevance gate로 검증한다. 결합 방식·후보 한도·reranker 사용은 정답셋으로 결정한다. 기존 최대 후보 한도를 무작정 늘리지 않는다.

검색이 유사 단어를 찾더라도 핵심 업무·입출력·Protocol이 맞지 않으면 제외한다. 뉴스→논문 Workflow 요청을 접근성 기술 논문 Agent로 대체하는 현재 사례를 명시적 hard negative로 넣는다.

현재의 최근 성공 검증 적격성 기간과 실패·격리 제외 정책도 유지한다. 검색 품질을 높인다는 이유로 검증 유효기간을 늘리거나 단순 연결 성공을 업무 성공으로 승격하지 않는다.

### 최종 선택의 순서

개별 Agent는 현재의 관련성·안전성·적격성 조건을 먼저 통과해야 한다. 그 안에서 **최근 성공 검증 → 최근 활동 → 품질 등급**의 기존 우선순위를 유지한다. semantic 점수·매출·인기·고객 등급이 이 순서를 덮어쓰지 않는다. 검증 만료·현재 실패·격리 상태를 캐시로 우회하지 않는다.

Workflow는 목표·입출력·노드 호환성·권한 요구에 맞는지를 먼저 확인하고, 현재 실행 준비 상태와 계약 검증을 제시한다. 최적의 공개 템플릿 하나와 추천 이유를 기본으로 반환한다. 탐색용 여러 결과는 별도 browse 동작에서 명시적으로 요청한다. Chat의 개별 Agent 단일 추천 정책을 유지한다.

### no_match도 다음 행동을 제공

응답은 `no_catalog_match`, `no_recent_evidence`, `protocol_mismatch`, `missing_inputs`, `authorization_required`, `temporary_unavailable` 등을 구분한다. 없는 업무를 있다고 생성하거나 다른 업무의 Agent로 조용히 대체하지 않는다.

다음 행동은 제약 하나 완화, 다른 Protocol을 명시적으로 선택, 입력 추가, Workspace에서 새 Workflow 제안 검토, 목적별 업데이트 신청 중 허용된 항목만 제시한다. “새 Workflow 생성”은 기존 Workspace·구독·권한을 확인한 준비 동작이다.

## Workflow를 Agent가 소비·준비·실행하는 방식

### 소비 경로

공개 템플릿 추천 → 선택한 버전 상세 → 입력 Schema 검증 → 데이터 흐름·목적·Provider 검토 → 실행 준비 → 실행 → 상태/결과의 순서다. 탐색·상세·입력 검증은 Provider 실행 없이 수행할 수 있게 한다. 준비 단계는 실제 호출 성공을 주장하지 않는다.

실행 준비 응답에는 버전, 고정된 입력의 digest, 누락 입력, 필요한 권한, 외부 전달 대상, 자동 복구 가능 범위, 시작 가능한 동작을 담는다. `prepare`는 Provider 요청을 보내지 않는다. 예약된 자원이나 Credit이 있다면 만료·해제 동작을 별도 명시한다.

### 작성 경로

공개 Agent는 기존 템플릿을 찾고, 권한이 있으면 복제·수정안을 제안할 수 있다. 새 Workflow 생성·편집·게시·다운로드는 현재 Workspace 체계의 사용자·조직·승인·구독 정책을 따른다. 설계 제안과 공개 게시는 별도 동작이다.

입출력 Schema가 연결되지 않는 노드는 거부한다. 자동 변환은 사전에 허용한 typed adapter만 적용한다. 자동 템플릿 생성 후 격리 입력으로 검증하고 소유자의 검토를 거친다. 운영 데이터로 검증하는 동작은 별도 권한을 요구한다.

### 반복 테스트와 Credit 정책

대화에서 정한 정책을 유지한다. 무료 초기 3 Credit, AI 자동 생성은 유료 구독자, 자동 Fallback 서비스는 유료 구독자, 요금·플랜별 지급량은 출시 전 검증 항목이다. 이는 기존 합의 정책이며 이번 설계에서 운영 구현 현황을 새로 검증한 것은 아니다.

AI 생성→테스트→재생성→수정을 거쳐 Workflow 하나를 확정하는 작성 주기를 하나의 `creation_session`으로 묶는다. 최종 확정 때 1 Credit을 반영하고 같은 주기의 기술적 재시도로 중복 차감하지 않는 원장 계약을 설계한다. 외부 Provider 실행 비용·실행권은 작성 Credit과 분리한다. Agent가 임의로 구독·충전하거나 사용자의 비용 권한을 상속하지 않는다.

무료 대체 후보 탐색과 유료 자동 Fallback 실행도 구분한다. 이미 승인된 단일 실행의 Worker→Origin 전달 경로 선택은 인프라 복구이며, 다른 Provider를 새로 실행하는 상품 Fallback과 다르다.

## 적은 도구로 사용하는 MCP·REST·A2A

기존 `/mcp` 11개 도구와 별칭은 유지한다. 새로운 compact profile `/mcp/agent`는 **제안 경로**이며 구현·검증 전에는 manifest에 활성 주소로 넣지 않는다.

새 profile은 `discover`, `describe`, `prepare`, `run`, `status`, `resume`, `updates`, `cancel`의 작은 고정 도구 집합으로 설계한다. 이는 모든 Provider 도구를 열거하는 방식과 구분된다. 실제 업무 도구의 전체 Schema는 `describe`로 선택한 대상에 대해서만 받는다. MCP `tools/list`를 매 질의마다 임의로 바꿔 클라이언트 캐시를 혼란스럽게 만들지 않는다.

일반 응답은 선택한 결과 하나·짧은 이유·입력 요약·현재 준비 상태·다음 행동이다. 구조화된 outputSchema와 유용한 짧은 텍스트를 제공하고, 전체 원본 Schema·과거 로그·대형 결과는 명시적 상세 요청으로 분리한다. 문맥 절약은 토큰·지연·목적 달성을 함께 측정한다.

MCP의 malformed request, 도구 실행 실패, 권한 필요, 결과 불확정, 검색 0건을 다른 상태로 표현한다. `no_match`나 확인 질문은 정상적으로 완료된 검색 결과다. 실제 실행 실패·불확정은 `isError=true`와 구조화 상태를 일치시킨다. 전송 인증 실패는 표준 HTTP 인증 흐름으로 처리한다.

[A2A v1.0](https://a2a-protocol.org/v1.0.0/specification/)은 버전·표현 차이를 검사한 adapter로 제공한다. 현재 소스에 0.3과 SendMessage 응답 분기가 존재한다는 사실만으로 전체 적합성을 선언하지 않는다. `A2A-Version`, 입력 파싱·출력 직렬화, 오류·Task 상태·Card 선언을 버전별로 검사한다. 통과한 기능만 광고한다.

[MCP Tasks 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)는 확인한 문서상 experimental이다. 안정적인 자체 REST Task 계약을 먼저 만들고, 협상된 MCP Tasks·A2A Task adapter를 선택적으로 연결한다. 단순 검색은 메시지 응답형을 유지한다.

## 재방문을 실제 이점으로 만드는 기능

### Task Passport

서버에 저장한 작업 참조를 `Task Passport`라는 사용자 기능으로 제공한다. 내부적으로는 소유자·목적·최근 입력의 안전한 요약·선택한 대상·Protocol·버전·최근 결과·권한 만료·다음 행동을 묶는다. 작업 참조 ID는 비밀 인증수단이 아니며 모든 조회에서 소유자·조직·scope를 다시 확인한다.

첫 실행이 없어도 “이 목적의 Agent를 찾고 있었다”는 탐색 Passport를 만들 수 있다. 생성과 장기 저장은 별도 선택을 받는다. 원문 질의·개인정보·결과 전문을 기본으로 영구 보관하지 않는다.

### 변경된 부분만 전달

재방문 `/resume`에는 마지막 작업, 계속할 수 있는 동작, 필요한 새 입력·승인, 만료된 증거, 실제로 달라진 사항을 짧게 반환한다. “기존과 동일”, “더 적합한 후보 발견”, “기존 실행 불가”, “Schema 변경”, “새 템플릿”을 구분한다.

정기 health timestamp만 바뀌었다고 매번 새 소식으로 알리지 않는다. 변경 기준은 업무 능력·적격성·상태·Schema·출력 계약처럼 의미 있는 digest다. 기준 cursor는 소유자와 목적에 결합하고 오래된 cursor는 전체 현황을 안전하게 재조회하도록 한다.

### 안정적인 접속 정보

세션 헤더, 작업 ID, 대상 참조, Schema 버전과 상세·상태 조회 경로를 client SDK에 저장한다. 임시 실행 Ticket은 만료되는 실행권이므로 재방문 북마크로 사용하지 않는다. 새 실행에는 최신 정책·검증과 새 실행권을 요구한다.

목적별 저장 검색, 마지막 성공한 템플릿, 변경된 Schema 확인, 실패한 작업의 확인 대기 상태를 반환한다. 사용자가 목적을 바꾸거나 기록을 지우면 과거 문맥이 새 요청을 강제로 덮어쓰지 않는다.

## 장기 Task·자동 복구·다중 Agent 위임

### durable 상태

내부 Task 상태는 `prepared`, `queued`, `running`, `input_required`, `authorization_required`, `succeeded`, `partial`, `failed`, `unknown`, `cancel_requested`, `cancelled`, `expired`를 구분한다. 검색 상태와 실행 상태는 별도 필드다. Provider를 dispatch한 이후의 시간 초과는 단순 `expired`로 덮어쓰지 않고 결과 불확정을 유지한다.

Task와 node attempt의 상태를 따로 기록한다. 결과는 작업 입력·버전·시도·Provider 실행 증거에 결합한다. Provider가 취소를 확인하지 않으면 `cancel_requested`이며, 이미 일어난 외부 부작용을 취소 성공으로 표시하지 않는다.

### 재시도와 대체 실행

실행 전 거절·확인된 안전한 재시도·불확정 실행을 구분한다. 입력 동일성과 소유자에 결합된 idempotency key를 사용한다. 같은 키에 다른 입력은 충돌로 반환한다. 기존 결과가 확인되면 권한 검사를 거쳐 그 receipt를 읽는 개선을 추가한다. 기존 구현의 반복 호출 중지와 구분되는 신규 기능이다.

현재 Edge 기록 보존 7일 이후의 키 재사용은 무기한 중복 방지로 표현하지 않는다. 제안하는 Task 계층은 실행 ID·입력 digest와 안전한 tombstone을 보존하고 재전송 허용 기간을 계약에 명시한다. 미확정·실행 중 기록은 짧은 일반 캐시 정리로 지우지 않는다.

다른 Provider 실행은 새 attempt이며, 이전 실행이 안전하게 끝났거나 외부 멱등성·취소가 증명되고 기존 grant가 대체 Provider·데이터 전달을 허용한 경우에만 가능하다. 결과 불확정 상태는 자동 Fallback으로 우회하지 않는다. 지수 backoff·jitter·Retry-After를 적용하되 전체 시도 수·시간·지출 한도를 먼저 적용한다.

### 승인 범위 안에서의 자율성

사람이 처음에 목적, 도구·Provider, 입력 데이터, 실행 횟수, 기간, 외부 전송, 비용 상한을 승인하면 그 범위 안에서 다음 단계를 수행할 수 있게 한다. 사소한 조회마다 확인을 반복하는 대신 scope가 변할 때 재승인을 받는다. 클라이언트가 `authorized=true`라고 보낸 것만으로 권한을 발급하지 않는다.

팀 Agent 간 handoff는 Task ID·목적·최소 입력·허용된 결과만 전달한다. 수신 Agent의 서버 검증된 신원과 소유자의 위임 범위가 필요하다. 다른 조직의 Credential이나 전체 대화 기록을 넘기지 않는다. 초기에는 직렬·제한 깊이의 승인된 Workflow만 실행하고, 임의의 재귀 Agent 고용·결제는 별도 확장으로 남긴다.

## 효율·비용·Edge 설계

### 검색의 빠른 경로

일반 질의는 로컬 규칙·기존 lexical index·증거 캐시로 처리한다. 표현이 모호하거나 후보가 부족할 때만 embedding·reranker를 쓴다. 생성형 LLM은 매 검색의 필수 의존성으로 만들지 않는다. 질의 embedding에는 동일 요청 병합, 짧은 실패 캐시, 모델·차원·색인 버전 fencing을 적용한다.

공개 Catalog·Schema 문서는 ETag로 재사용한다. 검색 결과를 캐시해도 반환 직전에 적격성·현재 실패·Schema 버전·권한을 재확인한다. 개인 작업·세션·실행권·준비 결과는 공유 CDN 캐시에서 제외한다. 캐시 키에는 언어·Protocol·Catalog/모델 버전과 접근 범위가 반영되어야 한다.

최초 응답을 빠르게 하기 위해 상세 Schema·대형 이력·대체 후보 전체를 붙이지 않는다. `fields`·`view=compact|full`, cursor 페이지, 조건부 조회를 사용한다. byte 크기·요청 수·모델 왕복·DB 작업량을 함께 예산화한다.

### Control Plane과 결과 전달 분리

Origin은 탐색·권한·버전·작업·실행권·작은 receipt를 담당한다. Edge Worker는 허용된 Provider 요청과 모든 실행 결과의 streaming을 우선 담당한다. 작은 JSON·단건 결과도 Edge가 기본이며 결과 크기에 따른 정상 Origin 경로를 두지 않는다. 검색·embedding·대형 JSON 분석을 Worker의 요청 경로에 넣지 않는다. 노드 연결은 먼저 검증된 typed mapping으로 수행한다.

**현재 MCP의 Origin wrapper가 Worker 결과를 받아 MCP 응답으로 돌려주면 결과 bytes는 여전히 Origin을 통과한다.** 따라서 “Edge 연결됨”을 “Origin 결과 egress 제거”로 평가하지 않는다.

모든 실행 결과에 Edge 우선을 적용하는 목표 경로는 두 가지다. 결과 크기는 라우팅 조건으로 사용하지 않는다.

1. REST/SDK Agent가 같은 플랫폼 도메인의 Ticket 실행 경로를 직접 호출해 Edge→Agent로 받는다.
2. compact MCP의 공개 ingress 자체를 Worker에 두고, Origin에는 인증·실행권·작은 완료 기록만 요청한다. Worker→Provider→Worker→MCP client 경로로 결과를 전달한다. 구현·성능 검사·별도 배포가 필요한 후속 기능이다.

Provider의 실제 접속 주소는 client에게 redirect하지 않는다. Location·Link·오류·부가 header를 안전하게 투영한다. Provider가 본문에 자기 주소를 넣는 경우까지 “주소 정보 완전 비노출”로 보장하려면 별도 결과 계약이 필요하다. 모든 본문을 대형 파싱·치환하는 설계는 기본 streaming 경로에서 피한다.

대형 결과는 가능한 경우 결과 handle·범위 읽기·명시적 요약을 사용한다. object storage·영속 보관·CPU·Provider 요금·Origin fallback은 각각 비용이 있을 수 있다. “비용 제로” 대신 **Origin 경유 bytes 최소화**를 측정한다. 저장소나 유료 Cloudflare 기능을 새로 전제하지 않는다.

### 무료 한도·부하 보호

기존 무료 한도·CPU·상태·quota guard와 fail-open 정책을 유지한다. Worker가 실행권을 점유한 뒤 실패하면 Origin이 같은 업무를 다시 시작하지 않는다. 실행 전의 라우팅 전환과 실행 후 결과 손실을 구분한다. Origin fallback에서는 출력 byte·동시성·전체 시간을 제한하고, 처리 용량이 없으면 정직하게 대기/일시 불가를 반환한다.

이전 부하 검증의 heap safety threshold와 넓은 CPU window 문제는 열린 출시 조건이다. 새 compact ingress·대형 streaming을 실제 24시간 통과했다고 간주하지 않는다. 격리 메모리·CPU·연결 종료·slow reader·큰 결과·SSE 비호환을 각각 재검증한다.

## 신뢰·권한·증거

도구의 `readOnlyHint` 같은 Provider annotation은 참고 자료이며 실행 권한이 아니다. Provider Schema와 도구 응답은 데이터를 설명할 뿐 새 URL·실행 도구·권한·목적을 만들지 못한다. 문서 안의 지시를 도구 선택·자동 승인 근거로 쓰지 않는다.

기본 신뢰 계층은 공개 읽기, 세션 작업, Workspace 작업, 외부 부작용 실행이다. 각 계층은 서버에서 audience·scope·소유자·입력·목적·만료를 확인한다. MCP client token을 Provider에 그대로 전달하지 않는다. 원격 URL·redirect·DNS·내부 IP·파일 경로는 기존 public outbound 정책을 유지한다.

실행 증거는 transport 성공, Schema 적합, 도구 실행 성공, 특정 업무 계약 충족을 나눈다. 품질 등급 하나가 모든 업무의 성공을 대신하지 않는다. Client의 worked/failed 피드백은 관찰로 별도 기록하고, 인증된 receipt 없이 실제 실행 증거로 승격하지 않는다.

새 Provider와 Schema 변경은 버전별 격리 검증 후 적격성을 갱신한다. 새 Catalog 편입만으로 즉시 운영 실행권을 주지 않는다. 공개 설명·작업 로그에서 방문자 신원·token·개인 입력·내부 모델 설정을 노출하지 않는다.

## 업데이트와 적극적 재사용

현재 task update의 목적·목적지 확인을 재사용한다. 알림은 Agent의 관심사나 방문만으로 등록하지 않는다. 원래 목적의 유의미한 변화, 실행 완료, 입력·승인 요청, 사용 불가, Schema 변경 같은 이벤트를 처리한다.

webhook/A2A inbox는 검증된 목적지와 서명·event ID·만료를 사용한다. 같은 이벤트의 중복 수신을 client가 제거할 수 있게 하고, 전송 결과 불확정과 재전송 정책을 명시한다. manual polling은 Push와 구분한다. 의미 없는 매 주기 알림을 없애고, 마지막 cursor 이후 변경만 전달한다.

기존 Machine 증거 알림 grant의 최대 24시간·20건은 유지한다. 일반 업무 반복 실행권은 다른 grant로 설계하고 이 제한을 조용히 확대하지 않는다. 광고 동의는 작업 알림과 독립이며 기존 광고 전달 비활성 정책을 유지한다.

사용을 늘리는 핵심 동기는 “돌아오면 더 짧고 정확하게 이어진다”는 효용이다. 저장된 목적·새 템플릿·실패 확인·변경된 계약을 제공하고, 등록·방문·알림 수 자체를 성과로 삼지 않는다.

## 추가 확장: 사용이 쌓일수록 가치가 커지는 기능

**Capability Gap Radar:** no_match를 업무 유형·Protocol·필요 출력·증거 만료로 집계한다. 운영자는 “공급이 없는 업무”, “검색 설명이 부족한 업무”, “검증만 만료된 업무”를 구분해 개선한다. 고객 원문·조직·비밀 입력을 공개 수요로 게시하지 않는다. 필요한 Provider 검증도 수요와 안전성을 기준으로 제한된 예산 안에서 예약한다.

**개인 Recipe Library:** 성공한 작업에서 입력·버전·연결 구조를 재사용 가능한 recipe로 저장한다. 기본값은 해당 Workspace 비공개다. 원문 데이터 대신 typed 입력·출력 참조를 사용하고, 공개 템플릿으로 바꾸는 작업은 별도 검토·승인을 받는다. 덕분에 반복 작업은 다시 조합하지 않고 입력만 바꿔 준비할 수 있다.

**Portable Receipt:** 외부 Agent가 결과의 출처·실행 범위·버전·상태를 확인할 수 있는 서명된 receipt를 선택적으로 제공한다. 기존 서명/receipt 모듈 재사용을 먼저 검토한다. 서명은 발행자를 증명하며 업무 사실의 진실성을 자동 보장하지 않는다. 수신자는 지원 알고리즘·키·만료·scope를 확인한다.

**Capability Negotiation:** 큰 결과·streaming·structured output·Task·취소·최대 입력 크기 등 client 능력을 처음에 협상한다. client가 처리하지 못하는 SSE나 대형 JSON을 보내는 대신 지원되는 조회·artifact 경로를 안내한다. 미지원 Provider를 지원된 것처럼 포장하지 않는다.

**데이터 전달 최소화:** Workflow 노드마다 필요한 필드만 다음 Provider에 전달한다. 결과 전체를 모든 노드에 보내는 방식 대신 Schema로 허용한 필드만 projection한다. 사용자에게는 데이터 흐름을 한 번에 검토할 수 있게 하고 실행권에는 그 범위를 결합한다.

**평가 가능한 설명 개선:** 검색 실패를 보고 문서·alias 개선안을 만든 뒤 정답셋에서 비교한다. 운영 검색 순위를 즉시 자기 학습으로 바꾸지 않는다. 조정용 데이터와 holdout, source version과 변경 이유를 남겨 품질 회귀를 복구할 수 있게 한다.

**개발자 체험 진단:** 외부 Agent client가 연결·Protocol·Schema 읽기·첫 검색까지 자가 진단하는 작은 conformance fixture를 제공한다. 실제 Provider 실행 없이 client 통합을 확인하며, 테스트 결과와 실서비스 업무 검증을 구분한다.

## 관측 지표와 완료 기준

다음 수치는 **제안하는 초기 출시 목표**이며 현재 실측 성과가 아니다. 기존 방문 표본은 전체 정확도의 baseline으로 쓰지 않는다.

- 첫 방문용 설명: 대표 tokenizer 2종 각각 1,500 token 이하. 필수 목적 찾기 성공률 95.0% 이상.
- Agent/Workflow 목적 분류: 합성·수동 검토한 고정 정답셋에서 95.0% 이상. 위험한 실행 오분류는 출시 검사에서 0건.
- 명확한 템플릿 질의 Top-1: 90.0% 이상. 의도적으로 없는 업무의 잘못된 추천률 2.0% 이하.
- 근거·Schema·입력 권한 재검증 누락: 출시 검사에서 0건. 개별 Agent의 기존 검증·활동·등급 우선순위 회귀 0건.
- 인접 리전 synthetic client 기준 discover 지연: warm p95 1.0초, cold p95 2.5초를 초기 목표로 설정. 공개 인터넷 end-to-end와 서버 내부 시간을 분리한다.
- compact 응답: 상세 Schema를 제외한 응답 8 KB 이하를 초기 목표로 설정. 무조건 요약해 필수 입력·오류를 지우지 않는다.
- 재방문 1회 요청으로 다음 행동을 찾는 성공률 95.0% 이상. 의미 없는 반복 업데이트는 정답셋에서 0건.
- 실행 결과 손실·동시 재시도·Origin 전환·권한 철회 시 중복 부작용 dispatch 0건을 fault injection 출시 조건으로 적용.
- 목표·검증 범위를 충족한 receipt가 있는 업무만 task completion으로 집계한다. HTTP 200·광고 클릭·UA가 Agent처럼 보인다는 사실은 별도 지표다.

질의·의미 정확도·반복 성공·권한 위반·token·지연·Origin bytes·Worker CPU/heap을 함께 비교한다. 한 지표를 개선하려고 나머지 안전성과 목적 달성을 약화하지 않는다.

## 단계별 개발 계획

일정은 1인 개발 기준의 **범위 추정**이다. 첫 핵심 여정은 약 2~3주, 전체 단계는 약 8~12주를 가정하되 기존 리뉴얼·검증 결과에 따라 조정한다. 날짜보다 단계별 검사를 통과하는 것을 출시 조건으로 둔다.

### 첫 단계: 계약과 회귀 기준

기존 인터페이스 snapshot, 목적 분류, 응답·오류·버전 계약, 정답셋을 고정한다. 현재 `papers`·한국어·영어 자연어 템플릿 실패를 회귀 사례로 편입한다. 기존 정책·세션·Provider 안전 경계를 문서화한다.

### 두 번째 단계: Workflow 검색과 첫 안내

작은 템플릿 색인, 한글·영문 동의어, 노드 검색, Chat intent 연결, 목적별 Entry를 만든다. 기존 API·MCP 도구의 호환성을 유지한다. 이 단계만으로 “Agent가 템플릿을 발견하고 필요한 입력까지 읽는 여정”을 완성한다.

### 세 번째 단계: compact 접속과 재방문

작은 MCP profile, focused OpenAPI, Task Passport, 의미 있는 변경 delta와 resume를 제공한다. client 3종·tokenizer 2종·권한/개인 캐시 경계를 검사한다. 기존 MCP 11개를 삭제하지 않는다.

### 네 번째 단계: 승인된 Task 실행

공개 템플릿 실행 준비와 Workspace Task를 권한 adapter로 연결한다. durable 상태·receipt 조회·취소·부분 성공·입력 요청·unknown을 구현한다. 무료/구독·Credit·자동 Fallback 권한과 위임 범위를 서버에서 확인한다. 기존 Machine worker는 이 기능을 위해 일괄 켜지 않는다.

### 다섯 번째 단계: Edge 결과 경로 최적화

direct Ticket SDK와 Worker MCP ingress를 격리 검증한다. byte·CPU·heap·slow stream·free-limit fallback을 검증하고 기존 장기 부하 문제를 해결한 후 소규모 canary를 적용한다. Worker 변경·새 경로·서비스 교체는 구현 후 구체적인 배포 검토로 진행한다.

### 여섯 번째 단계: 외부 배포와 확장

공식 Registry 게시, 검증된 SDK·설정 예시, 목적별 공개 가이드, design partner Agent로 실제 유입→추천→준비→완료→재방문을 측정한다. 별도 승인된 Provider 호출 범위 안에서 검증한다. 여러 Agent 위임·sandbox Code Mode·학습 기반 reranker는 이 근거를 보고 확대한다.

각 단계는 기능 flag로 나눠 적용한다. 문제 발생 시 신규 발견 기능과 실행 시작을 줄이되 이미 시작된 Task·receipt·idempotency 기록은 남긴다. DB 확장은 추가형 migration과 복구 계획으로 진행하고 진행 중인 Admin 리뉴얼과 API 계약으로 분리한다.

## 산출물

- [조사 근거와 적용 판단](RESEARCH.md)
- [구현 위치·API·권한·운영 설계](IMPLEMENTATION.md)
- [제안 검색 계약 Schema](discovery.schema.json)와 [예시](contract-examples.json)
- [예정 인수 검사 목록](acceptance-cases.jsonl)
- [설계 산출물 자체 검사](design-validation.json)

이 문서의 새 API는 현재 주소로 호출하지 않는다. 운영 코드·설정·권한·Provider·외부 게시 작업은 변경하지 않았다. 다음 개발은 두 번째 단계의 첫 방문·Workflow 발견 여정부터 시작할 수 있도록 설계했다.


## 사용자 확정 전달 정책 — 2026-10-25

모든 실행 결과는 크기·형식과 관계없이 Edge가 우선이다. Origin은 Edge 사용 불가·실패의 폴백 경로다. 실행 전 라우팅 실패는 안전한 Origin 전환을 허용하며, Provider가 이미 실행된 뒤에는 중복 실행 대신 기존 상태·결과 회수 가능 여부를 먼저 확인한다. 이 기준은 신규 MCP 입구와 Workspace·Workflow·다운로드 앱에도 동일하게 적용한다. 공개 검색·권한·작업 상태 같은 제어 처리는 Origin을 사용할 수 있으며, 정상 Provider 결과를 크기가 작다는 이유로 Origin에 우선 전달하지 않는다.
