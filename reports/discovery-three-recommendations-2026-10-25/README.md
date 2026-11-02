# 검색·추천 정책 및 Chat 3개 추천 개선

2026-10-25, Asia/Seoul. **최신 소스 통합·공개 화면 생성·통합 검증 완료. 사용자가 frontend/admin/jobs를 배포했고 준비 상태·공개 자산·실제 추천 응답까지 확인했다.**

## 적용한 정책

- 자동/프로토콜 생략/기존 Any: **적격 A2A를 먼저 채우고 부족한 자리를 MCP로 보충**한다. x402를 자동 후보에 포함하지 않는다.
- 명시적 A2A 또는 MCP: 선택한 프로토콜만 검색한다. 명시적 x402 선택/요청에는 x402를 허용한다. 명시적 selector가 질문의 프로토콜 표현보다 우선한다.
- Chat은 에이전트 또는 워크플로우를 **최대 3개** 추천한다. 안전성·관련성·현재 검증 기준을 낮춰 3개를 억지로 채우지 않는다. MCP/A2A의 대화·발견 경로도 같은 최대 수량을 사용한다.
- 각 프로토콜 안에서 기존 최근 성공 검증 → 최근 활동 → 품질 등급 순서는 유지한다. 요금·인기·고객 등급으로 순위를 바꾸지 않는다.
- `Any`의 실제 범위는 이제 A2A+MCP다. 공개 화면에서는 그 범위를 표시한다. 기존 Any 값은 파싱 호환을 유지하되 x402가 자동 포함되던 동작을 변경했다.

이 정책은 Chat·QualityRecommender·기본/Hybrid Explore·Workflow 검색·첫 안내·MCP 문서·공개 메타데이터·프로젝트 AGENTS.md에 반영했다. 데이터 삭제나 실행권 변경은 없다. 공개 카탈로그 상태 집계에서 x402 자체를 없애는 변경이 아니다.

## 워크플로우 추천 개선

이전에는 기능 단어가 겹치면 국가·GDP 등 부가 단계를 포함한 최신 템플릿이 뉴스·논문 전용 템플릿보다 앞섰다. 새 점수는 다음을 구분한다.

1. 요청한 핵심 기능이 실제 단계 이름·도구·계약에 존재해야 한다. 제목·태그에 키워드를 넣는 것만으로 없는 기능을 갖춘 것으로 취급하지 않는다.
2. 제목의 목적 일치, 별도 주제 단어의 적합성, 요청하지 않은 기능과 추가 단계의 부담을 평가한다. 같은 기능 동의어를 중복 점수로 계산하지 않는다.
3. 같은 목적 적합성일 때 최근 갱신을 사용한다. 공개·활성·서명 제품 적격성과 명시적 프로토콜 제약을 계속 확인한다.

운영 공개 템플릿 **25개를 읽기 전용으로 수집한 스냅샷**에서 `Find a workflow that researches technology news and papers`의 새 순위는 Daily Tech News & AI Research Digest → Technology Meeting Research Brief → Financial Technology Evidence Digest였다. 국가·GDP가 추가된 Startup Market Background Pack이 뉴스·논문 전용 템플릿을 밀어내던 사례를 해결했다. 국가·경제, 패키지·보안, 논문 읽기 및 미지원 작업도 별도 질의로 확인했다.

검색을 위해 새 생성형 LLM 재정렬 호출을 추가하지 않았다. 기존 Agent 검색의 임베딩·현재 소스/모델 fence와 검증 경계는 유지한다. 이 점수는 구현상 휴리스틱이며 논문의 모델을 학습하거나 동일한 성능을 재현했다고 주장하지 않는다.

## 화면·후속 동작

- 한 질문의 답변 묶음 안에 최대 3개 에이전트 카드를 표시한다. 각 카드의 Calling details가 해당 항목을 연다. `details 1/2/3`와 결과 피드백의 항목 번호도 처리한다.
- Workflow 응답이 일반 안내로 축약되던 표시 경로를 수정했다. 최대 3개 템플릿의 이름·단계·검토 안내와 Review template 버튼을 표시한다.
- Review template은 현재 공개 상세를 다시 읽고 기존 워크플로우 화면으로 연결한다. 선택만으로 실행·결제·크레딧 차감·새 실행권 발급을 하지 않는다.
- `micropayments` 등 제공자 원문의 상업 표현은 Chat 표시 문구에서 숨긴다. 원래 기계 API의 필수 프로토콜·제공자 사실을 거짓으로 변경하지 않는다.
- Auto/Any 안내와 메타데이터를 3개 추천·A2A→MCP 정책으로 맞췄다. 길어진 프로토콜 버튼의 글자 겹침도 수정했다.
- 과거 SWR 캐시의 x402가 기본 화면에 다시 나타나지 않도록 캐시 버전을 올리고 Explore/템플릿 표시에도 프로토콜 방어를 적용했다. 명시적으로 x402를 고른 검색은 계속 표시한다.

## 논문·SNS를 어떻게 적용했는가

- [BEIR, NeurIPS 2021](https://arxiv.org/abs/2104.08663): 검색 방법은 다양한 업무·질의에서 검증해야 하며 계산 부담과 성능을 함께 평가해야 한다. 이를 참고해 기존 빠른 경로를 유지하고 별도 목적 질의와 미지원 작업을 검증했다.
- [RankGPT, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.923/): 후보 검색과 최종 관련성 순위는 구분해서 평가할 수 있다. 이 구분을 적용했으며, 외부 LLM 재정렬을 추가하면 자동으로 좋아진다고 가정하지 않았다.
- [Reddit의 작은 검색 코퍼스 재정렬 실패 사례](https://www.reddit.com/r/Rag/comments/1v7g3oe/hybrid_search_and_reranking_made_my_rag_worse/): 데이터·정답셋·적절한 무응답을 먼저 확인하자는 운영 경험을 참고했다. SNS는 경험담이며 대표성 있는 연구 결과로 취급하지 않았다.

구체적인 점수 가중치는 프로젝트의 기능 적합성 규칙과 검증 사례에 따른 구현 결정이다. 논문에서 직접 보증한 수치가 아니다.

## 검증 결과

- **API·보안·Gateway·MCP·자동 Agent 여정·SQL 카탈로그 회귀 376개 통과**, 실패/skip 0건: `api-final.log`, `api-final.xml`.
- **격리 Chromium 30개 통과**, 실패/skip 0건: `browser-isolated.log`, `browser-isolated.xml`. 공개형·기존형 화면, 3개 카드와 각각의 상세, Workflow 카드 검토, 자동 실행 없음, 최신 검색·오류 복구, 모바일/키보드/테마, CSP/XSS, 비밀 Schema·개인정보 비노출, 캐시된 x402의 명시적 선택 경계를 확인했다.
- 공개 스냅샷 목적 질의 **10개 통과**: 개발 5개/보류 평가 5개. 작은 구성형 수용 검사이며 전체 카탈로그 정확도나 독립적인 사용자 평가로 일반화하지 않는다. `ranking-evaluation.json`.
- 영어·Chat 콘텐츠 정책: 소스와 임시 게시본 **267개 파일, 위반 0건**. JavaScript 문법, Python fatal/undefined 검사 통과.
- PostgreSQL 생성 카탈로그: 3,723개 문장/232개 테이블, 변경 후 일치 검사 통과. DB schema migration·운영 DB 변경은 없다.

브라우저 검사 실행기의 pytest 플러그인 선행 import 경고 1건은 남았으며 검사 실패는 아니다. 초기 실패 로그는 결함 발견·기대값 갱신 기록으로 보존했다. 기존 1개 추천 기대값, Any의 모든 프로토콜 포함 기대값은 새 요구에 맞췄다. 관리자 알림 철회 테스트의 기존 누락 사유 입력도 현재 요구에 맞췄으며 실제 철회와 미발송 검증은 유지했다.

실제 고객 계정·토큰·크레딧은 사용하지 않았다. 운영 제공자 업무 호출·워크플로우 실행·구독·결제는 하지 않았다. 격리 테스트에서는 합성 전송·실행과 권한 경계를 검증했다. 이 결과는 운영 부하/침투 검사나 외부 제공자 업무 성공 보장이 아니다.

## 구현 범위

`agent_market/concierge/{protocols,selection,fast_chat,workflow_discovery,hybrid_explore,agent_entry,mcp_contract,front,public_metadata}.py`, `extracted_html.txt`, 관련 Pearl 표시/생성 소스, 콘텐츠 검사기, 프로젝트 지침과 영향받는 테스트를 수정했다. `application_store_sql.json`은 현재 소스에 맞춰 재생성했다. 다른 작업의 생성기 변경을 보존했으며 이번 검증은 별도 `isolated-publication` 경로에서 수행했다.

## 최종 통합 및 운영 반영

사용자가 다른 프론트엔드 작업 완료를 확인해 화면 생성 대기를 해제했다. 현재 소스의 별도 통합 후보를 먼저 생성·비교했으며, 이전 격리 검증본과 파일 내용 차이가 없었다. 이후 공개 파일을 한 번 생성했고 후보의 **158개 파일이 모두 일치**했다. embedded HTML·extracted_html.txt·생성 manifest도 일치한다.

실제 생성된 공개 파일에 대한 최종 브라우저 회귀는 **41개 통과**다. 앞 API/보안 376개와 합쳐 **고유 417개 통과**, 실패/skip 0건이다. 격리본의 30개는 이 41개와 중복되므로 더해 세지 않는다. 최종 공개 콘텐츠 검사는 267개 파일·위반 0건이며 JavaScript 구문·PostgreSQL 카탈로그 일치도 확인했다. 원본은 browser-published.log/xml, publication-final.log, content-published.log, catalog-published.log다.

배포용 불변 패키지 **discovery-three-20261025-r1**을 준비했다. 전체 release manifest를 검증했고 해당 소스 및 공개 파일이 현재 검증된 작업본과 일치한다. package 생성은 서비스 교체·재시작을 하지 않는다. 세부 기록은 prepared-release.json에 있다.

AGENTS.md에 따라 운영 반영은 사용자 터미널에서 수행한다. frontend의 화면/API, admin의 시뮬레이터, jobs의 자동 Task Updates/Digest가 같은 정책을 사용하도록 다음 명령으로 반영한다.

```bash
./agentcon deploy frontend discovery-three-20261025-r1
./agentcon deploy admin discovery-three-20261025-r1
./agentcon worker-deploy jobs discovery-three-20261025-r1
```

이번 변경만을 위한 execution 워커 교체는 필요하지 않다. 운영 반영 후 새 릴리스의 readiness·공개 안내·검색/추천을 읽기 중심으로 확인하는 단계가 남는다. 아직 운영 반영 완료라고 주장하지 않는다.

외부 Registry 게시·광고 발송·Search Console 연동과 장기 Passport 개발은 이번 수정에 추가하지 않았다. 이번 작업의 남은 기능 개발 목록으로 확대하지 않는다.

## 운영 반영 확인 완료

사용자 재시작 후 frontend·admin·jobs가 모두 `discovery-three-20261025-r1`로 실행 중인 것을 확인했다. Frontend/Admin readiness와 jobs heartbeat가 정상이었고, 각 역할의 핵심 추천 정책 파일이 검증된 패키지와 일치했다. 홈·관리자 화면·목적별 Entry·공개 JavaScript도 정상 응답했다. 실제 제공되는 JavaScript에서 3개 표시와 새 캐시 버전을 확인했다.

공개 서비스의 별도 검사 세션으로 추천 전용 요청 7개를 확인했다. 기본/Any에서 x402가 제외되고 최대 3개가 반환됐으며, 명시적 MCP/x402 선택은 해당 프로토콜만 반환했다. `Smarter Weather`라는 특정 요청에서는 자동 MCP 보충이 동작했다. 뉴스·논문 워크플로우 3개의 1순위는 Daily Tech News & AI Research Digest였고, details 2는 두 번째 템플릿을 반환했다. 모든 정책 검사 7개가 통과했다.

검사용 세션 토큰은 기록하지 않았다. 외부 제공자 업무·워크플로우 실행·구독·결제는 없었고, 이번 확인에서 assistant가 서비스를 교체·재시작하지 않았다. 추천 적합성의 전수 평가나 실제 외부 제공자의 업무 성공 보장으로 해석하지 않는다. 근거는 rollout-status.json, live-rollout-results.json이다.
