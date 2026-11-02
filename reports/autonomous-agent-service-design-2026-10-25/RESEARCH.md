# 조사 근거와 설계 판단

확인일: 2026-10-25. 논문·공식 문서를 기술 근거로 사용하고 SNS는 경험과 반례를 수집하는 자료로 사용했다. 외부 실험 결과는 Concierge의 성과로 환산하지 않았다. 아래의 적용안은 해당 근거와 현재 소스 검토로부터 도출한 **설계 판단**이다.

## 도구 선택과 검색 품질

**Retrieval Models Aren't Tool-Savvy / ToolRet — ACL 2025**  
[논문](https://arxiv.org/abs/2503.01763)

일반 IR 성능과 도구 검색 성능의 차이를 평가한다. 설계에 적용할 내용은 일반 문서 검색 점수 대신 실제 업무→Agent/Workflow 정답으로 검색을 평가하는 것이다. 실패한 템플릿 질의, 비슷한 단어지만 다른 업무, 입출력이 다른 도구를 정답셋에 넣는다. 논문의 도구 수·검색 품질을 현재 Catalog의 실행 가능 수치로 사용하지 않는다.

**Tools are under-documented: Simple Document Expansion Boosts Tool Retrieval — 2025**  
[논문](https://arxiv.org/abs/2510.22670)

구조화된 도구 설명 보강과 검색을 연구한다. Workflow의 노드 목적·입출력·예시·제약을 색인하는 판단에 참고했다. 모델이 보강한 설명과 Provider 원본·실제 검증 증거를 따로 보관한다. 생성 설명만으로 실행 도구나 지원 기능을 늘리지 않는다. 자체 평가 없이 특정 모델·개선율을 채택하지 않는다.

**Introducing advanced tool use — Anthropic, 2025-11-24**  
[공식 자료](https://www.anthropic.com/research/advanced-tool-use)

도구 정의의 지연 로딩과 프로그램 호출을 다룬다. 작은 기본 도구 집합, 선택한 대상만 상세 Schema 조회, 실제 사용 예시를 채택한다. 이는 특정 플랫폼 기능을 모든 MCP client가 자동 지원한다는 의미가 아니다. 기존 11개 도구는 유지하고 신규 compact profile의 목적 달성과 지연을 별도 측정한다.

**Code Mode — Cloudflare**  
[공식 자료](https://blog.cloudflare.com/code-mode/)

코드와 sandbox를 통한 도구 조합을 설명한다. 여러 단계마다 LLM을 왕복하지 않고 typed Workflow에서 연결하는 판단에 참고했다. 초기 제품은 임의 코드 실행보다 공개 템플릿·검증된 adapter를 우선한다. sandbox·network mediation·CPU·격리 조건이 검증되기 전에는 실행 도구에 임의 JavaScript/Python을 받지 않는다.

## 반복 신뢰성과 실행 복구

**τ-bench — 2024**  
[논문](https://arxiv.org/abs/2406.12045)

대화 후 목표 상태와 반복 실행의 일관성을 평가한다. HTTP 응답, 검색 정답, 입력 준비, 실제 실행 완료를 각각 측정한다. 5회 반복 모두 성공한 업무 비율을 별도로 기록하는 pass^5 지표를 제안한다. 이 설계의 예정 검사를 논문 benchmark 재현 결과로 표현하지 않는다.

**ExoFlow — OSDI 2023**  
[논문·발표](https://www.usenix.org/conference/osdi23/presentation/zhuang)

실행과 복구 계층을 분리한다. 기존 Ticket과 durable Task가 실행 소유권을 유지하도록 설계한다. 응답을 잃은 뒤 다른 Provider를 즉시 호출하지 않고 receipt를 조회한다. 임의 외부 Provider의 부작용에 대한 무조건적인 exactly-once 보장으로 확대하지 않는다.

## 신뢰와 안전한 도구 사용

**AgentDojo — 2024**  
[논문](https://arxiv.org/abs/2406.13352)

신뢰하지 않는 도구 데이터가 Agent 행동을 바꾸는 prompt injection을 평가한다. 설명·Schema·결과 본문의 지시가 권한·목적을 확대하지 못하는 검사를 추가한다. 공격 성공률과 정상 업무 성공률을 같이 측정한다. 탐지 모델 하나로 모든 공격을 막았다고 선언하지 않는다.

**MCP Security Best Practices — 2025-11-25 문서**  
[공식 문서](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)

token passthrough, confused deputy, SSRF, 세션과 scope 문제를 다룬다. client 신원·Workspace 권한·Provider Credential을 분리하고 외부 주소·redirect·DNS·token audience를 검사한다. Origin header나 client의 권한 주장만으로 Agent 실행권을 발급하지 않는다.

## 상호운용과 공개 배포

**MCP Tools — 2025-11-25 규격**  
[공식 규격](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

도구 입출력 계약과 structuredContent·outputSchema·오류 상태의 기준이다. 단일 계약 원천과 명세 snapshot 검사를 유지한다. readOnlyHint 등 annotation은 권한·안전성 보증으로 사용하지 않는다. 기존 공개 검색 0건과 실행 실패를 다른 상태로 표현한다.

**MCP Tasks — 2025-11-25 규격**  
[공식 규격](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)

확인한 문서에 experimental로 표시되어 있다. 안정적인 자체 REST Task와 상태 저장을 먼저 만들고, 협상된 client만 MCP Tasks adapter를 사용한다. 단순 검색에 불필요한 비동기 수명주기를 강요하지 않는다. 출시 시 선택한 버전과 실제 지원 기능을 다시 검사한다.

**A2A v1.0.0 고정 문서**  
[공식 규격](https://a2a-protocol.org/v1.0.0/specification/)

버전 전달, Task와 상태·취소·입력 요청, Card 선언의 기준이다. 0.3과 1.0의 표현 차이를 adapter·적합성 검사로 관리한다. 기존 소스의 SendMessage alias와 응답 분기를 전체 1.0 적합성 인증으로 간주하지 않는다. 필요한 기능이 검증된 뒤에만 Card capability를 광고한다.

**MCP Registry remote server 게시 안내**  
[공식 저장소 문서](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/remote-servers.mdx)

remote server 게시와 namespace 소유권 확인을 다룬다. Registry는 name의 namespace를 확인하며 remote URL 소유·품질까지 보장하지 않는다. 공식 게시를 유입 채널로 사용하되 자체 endpoint·Schema·실행 검증을 유지한다. 이 조사는 실제 Registry 게시 작업이 아니다. main 문서는 바뀔 수 있으므로 구현 시 사용한 schema와 commit을 고정한다.

## SNS에서 수집한 반례와 실험 가설

**“Tool selection at scale is a retrieval problem…” — r/mcp**  
[토론](https://www.reddit.com/r/mcp/comments/1uirauu/tool_selection_at_scale_is_a_retrieval_problem/)

제작자는 짧은 도구 문서에서 lexical 방식이 semantic 방식보다 나았다는 경험을 공유하고 본인이 관련 도구 제작자임을 밝힌다. 이를 “항상 BM25가 우수하다”로 일반화하지 않는다. 필드명·고유 도구명·모호한 표현을 나눠 lexical·semantic·hybrid를 비교하는 가설로 사용한다.

**“An attempt to replicate and benchmark…” — r/ClaudeAI**  
[토론](https://www.reddit.com/r/ClaudeAI/comments/1pbhylx/an_attempt_to_replicate_and_benchmark_the_tool/)

작성자의 작은 mock 실험에서는 단순한 search/execute 추가가 악화됐고, category·출력 Schema 등의 보강이 도움이 됐다고 보고한다. 외부 모델 평가와 합성 도구 실험이라는 한계가 있다. Concierge에서는 기본 도구를 줄이는 것 자체를 목표로 삼지 않고 목적 달성·도구 호출 수·지연·token을 함께 비교한다.

**“Cloudflare's new MCP setup…” — r/mcp**  
[토론](https://www.reddit.com/r/mcp/comments/1wu0e3o/cloudflares_new_mcp_setup_is_pretty_interesting/)

catalog+executor에 대한 관심과 비슷한 endpoint의 잘못된 선택 우려가 함께 나온다. 원글은 직접 benchmark를 했다는 증거가 아니다. Concierge는 짧은 curated 목적 경로를 먼저 사용하고 필요할 때 전체 Catalog를 탐색하는 실험을 설계한다. 원글의 token 수·효과 수치를 우리 제품에 적용하지 않는다.

## 이번 조사에서 채택하지 않은 단순화

- 도구를 둘로 줄이면 항상 더 빠르다는 가정.
- embedding만 붙이면 도구·템플릿 목적을 정확하게 이해한다는 가정.
- robots·llms 안내가 있으면 자동 홍보·검색 노출이 완료됐다는 가정.
- Registry 등록·도메인 증명·높은 등급이 업무 성공을 보장한다는 가정.
- Edge 사용이 곧 Origin egress 제로라는 가정.
- HTTP 200·Agent의 자기 보고·한 번의 성공이 반복 업무 신뢰성을 입증한다는 가정.

설계에서는 각 가정을 독립적인 관측·회귀·부하·의미 평가로 확인한다.
