# Explore protocol scope — 2026-10-26

## Result

탐색 결과 위에 **Search scope: A2A + MCP**를 상시 표시한다. 기본 선택 상자도 **A2A + MCP (default)**로 명확히 변경했다. 기본 안내는 A2A 우선, x402 명시 요청 시 포함, 현재 프로토콜/필터 기준 건수임을 설명한다.

명시 A2A/MCP/x402 선택과 검색어의 프로토콜 요청에 맞춰 안내와 결과 제목을 갱신한다. 선택 상자가 검색어보다 우선한다. 새 응답이 도착해야 결과 범위 안내를 바꾸므로 이전 결과 건수를 새 범위로 오해하게 하지 않는다. 빈 결과·캐시·재검색에서도 같은 규칙을 적용한다. 기존 검색/추천 범위와 홈 전체 카탈로그 집계는 변경하지 않았다.

영어 문구, 로컬 Lucide SVG, 기존 테마 변수, 반응형 배치와 접근성 안내를 사용했다. 공개 Pearl 화면과 embedded fallback 양쪽에 적용했으며 `front.py`와 `extracted_html.txt`를 동기화하고 빌드했다.

## Related fixes found during verification

- A2A/MCP 결합 시 보고서/과거 에이전트 수가 첫 그룹의 값으로만 표시되는 결함을 수정했다. 확인된 수는 합산하고 한 그룹이라도 미확정이면 `None`을 유지한다. 제한된 검색 창 flag도 전체 범위를 반영한다.
- x402를 기본/Any 검색에 포함한다고 가정하던 기존 테스트 두 곳을 현재 정책에 맞췄다. x402 검사는 명시 선택으로 유지한다.
- HTML 동기화 중 UTF-8 AST byte offset을 문자 위치로 처리해 함수 선언부가 잘리는 오류가 있었다. 손상된 선언부만 복원하고 나머지 최신 소스는 보존했다. 최종 Python 구문·HTML 동일성·빌드·API 회귀를 통과했다. 운영 서버는 불변 릴리스에서 실행되므로 이 과정에서 교체하거나 중단하지 않았다.

## Validation

- [브라우저 47건 통과](browser.log): 신규 3건, 기존 탐색 layout/필터/비동기 갱신, CSP·XSS 회귀. 기본/명시/검색어/우선순위/빈 결과와 375px 배치를 확인했다.
- [API·메타데이터·보안·batch 조회 36건 통과](api.log).
- [보고서 정합성·B2A 95건 통과](counts-and-b2a.log).
- 위 세 그룹 합계 **178건 통과**.
- 공개 콘텐츠 **292개 / 위반 0**, embedded/extracted 동기화 통과.
- SQL catalog **3,802 statements / 기존 필수 232 tables**, 최종 소스와 일치. 신규 SQL/스키마는 없다.
- [변경된 프로토콜 병합 모듈 Bandit 검사](bandit-protocols.json): 발견 사항 0건. 새 화면 문구는 `textContent`, 기존 검색어는 escaping을 유지하며 실제 브라우저 공격 입력 검사도 통과했다. 전체 플랫폼 무취약을 보장하는 검사는 아니다.

## Rollout

검증한 package: **explore-protocol-scope-20261026-r1**. [release.json](release.json)에 검증 결과를 기록했다. 운영 서버는 변경하지 않았다. DB migration과 admin/jobs/execution 재배포는 필요 없다.

사용자 터미널에서:

```bash
cd <저장소>
./agentcon deploy frontend explore-protocol-scope-20261026-r1
```

배포 후 탐색 화면을 전체 새로고침하면 된다.
