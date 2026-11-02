# 공개 GitHub 이슈·PR 검색 자체 에이전트 (2026-10-27~28)

## 배경
Chat "GitHub 이슈 검색"에 검증된 GitHub 전용 서버가 없어, 도구를 여러 개 묶은 서비스(Agent Tollgate)가 1위였다. 카탈로그의 GitHub 이슈 도구 4개는 토큰이 필요하거나(호출 시험 실패), 개인 저장소용이거나, 아직 검사 전이었다. 결정(E): **직접 만들고, 인증 없이 분당 10회, 이슈와 PR을 함께 다루며, 캐시는 가장 효율적인 방식으로**.

## 구성

| 항목 | 내용 |
|---|---|
| 형태 | 자체 데이터 에이전트 `github-issues`(Research Papers와 같은 구조). 이름 "GitHub Issues and Pull Requests", 도구 `search_github_issues` |
| 공개 주소 | `https://agentconcierge.biz/api/owned-data-agents/github-issues/mcp` (카탈로그 ID 214845, 게이트웨이 `/api/gateway/mcp/214845`) |
| 데이터 출처 | GitHub Search API `GET /search/issues`, 인증 없음. `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28` |
| 입력 | `query`(2~160자), `limit`(1~5), 선택: `repository`(owner/name 형식만), `type`(any·issue·pull_request), `state`(any·open·closed) |
| 출력 | 제목, 링크(github.com만), 저장소, 번호, 종류(이슈/PR), 상태, 갱신 시각, 댓글 수, 라벨 최대 5개, 전체 건수, 일부 결과 여부. 출처·조회 시각·캐시 상태도 함께 반환 |
| 개인정보 | 작성자 ID와 본문은 넣지 않는다 |
| 검색어 보호 | 검색어 안의 GitHub 한정자(`user:`, `repo:` 등)는 지우고, 저장소·종류·상태는 정해진 입력으로만 붙인다. URL·토큰·이메일 형식이 든 검색어는 거절한다 |

## 요청 한도와 캐시
- **분당 10회 창 제한(`WindowLimiter`):** 최근 60초 요청이 10건이면 보내지 않는다. GitHub의 `retry-after`, `x-ratelimit-remaining`·`x-ratelimit-reset`, 403·429 응답을 받으면 그만큼 쉰다.
- **정상 캐시 10분:** 같은 검색은 10분 동안 GitHub를 다시 부르지 않는다.
- **비상 캐시 6시간:** 한도에 걸리거나 장애가 나면, 최대 6시간 전 결과를 "stale_cache" 표시와 함께 쓴다. 그보다 오래된 결과는 쓰지 않고 실패로 알린다.
- **같은 뜻은 한 캐시:** 대소문자·공백·기본값 필터(any)·저장소 대소문자만 다른 검색은 같은 캐시를 쓴다.
- **캐시 크기:** 자체 에이전트 공통 캐시를 128개에서 512개로 늘렸다. 실패한 검색은 15초간 다시 부르지 않는다.

## 추천·검색에 나오게 한 작업
1. **등록:** frontend가 시작할 때 카탈로그에 자동 등록된다. 첫 상태 점검은 배포 전환 중이라 404를 받았고, 다음 점검에서 `reachable`이 됐다.
2. **순위:** Chat은 최근 검증된 에이전트를 먼저 보기 때문에, 실행 기록이 없는 새 에이전트는 후보 320위에 머물러 추천되지 않았다. 공개 게이트웨이로 한 번 실행해 기록을 남겼다.
3. **기록 유지:** 재검증 작업(jobs)이 자체 에이전트 7개 모두를 예시 입력으로 12시간마다 한 번 실행해 실행 기록을 갱신한다(GitHub 하루 2회).
4. **PR 질의 정확도:**
   - "pull requests **that** fix …"에서 that·which 뒤는 주제로 본다.
   - PR 요청은 GitHub·GitLab·저장소·merge 같은 코드 호스팅 문맥을 요구한다. 보험 서비스의 `pull_requests` 도구가 나오던 문제를 막는다.

## 연쇄 영향과 조치
자체 에이전트 코드가 바뀌면, 그 코드의 해시로 만든 Research Papers 계약 증거가 무효가 된다(설계상 재검증 필요). 이 때문에 워크스페이스 AI 생성이 다시 꺼졌다.
- jobs·execution에도 같은 자체 에이전트 코드를 배포해 세 역할의 해시를 맞췄다.
- 재검증기가 기록 시점이 아니라 실제 검증 상태로 다시 검사 여부를 판단하게 했다. 재검증 직후 계약이 회복됐다.

## 배포 이력
| 릴리스 | 내용 |
|---|---|
| `github-issues-frontend/admin-20261027-r1` | 에이전트 추가 |
| `github-issues-jobs/execution-20261028-r1` | 자체 에이전트 코드 통일, 재검증기 수정 |
| `owned-refresh-frontend/admin/jobs-20261028-r1` | 자체 에이전트 실행 기록 주기 갱신, PR 질의 수정 |

## 확인 결과 (운영)
- MCP 직접 호출과 게이트웨이 호출 모두 실제 GitHub 결과를 반환한다(nodejs/node "memory leak" 등).
- Chat "Search GitHub issues about memory leak bugs" → 1위 GitHub Issues and Pull Requests.
- Chat "Find pull requests that fix memory leaks" → 1위 같은 에이전트. 보험 서비스는 빠졌다.
- Explore "github issues" → 1위.
- 재검증 로그: 4건 확인, 4건 성공.

## 테스트
- `tests/test_owned_data_source_limits.py`: 분당 10회 제한과 재시도 신호, 한정자 제거, 작성자·본문 제외, 같은 뜻 검색의 캐시 공유, 잘못된 저장소 이름 거절.
- `tests/test_owned_data_agents*.py`: 에이전트 7개 기준으로 갱신, GitHub 모의 응답 추가.
- `tests/test_owned_data_agents_local_execution.py`: 자체 에이전트 실행 기록 주기 갱신.
- `tests/test_model_contract_reverify.py`: 오래된 구현의 증거는 다시 검사.

## 한계와 다음 단계
- **한도는 서버 IP 기준 분당 10회다.** 사용이 늘면 캐시와 비상 캐시로 버티지만, 새 검색어가 몰리면 일부는 "잠시 후 다시" 응답이 된다. 필요하면 서비스 토큰(분당 30회)으로 바꿀 수 있다.
- **워크스페이스 워크플로우 계약(문서·뉴스 검색)에는 연결하지 않았다.** 이슈 검색 전용 계약이 생기면 어댑터를 추가한다.
- 결과에는 이슈 본문이 없다. 내용을 보려면 링크를 열어야 한다.
