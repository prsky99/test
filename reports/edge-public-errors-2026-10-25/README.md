# 공개 Edge Gateway 오류 2건 원인·복구 확인

2026-10-25 · 확인 시각 21:01 KST 기준

## 결과

공개 Gateway 오류 2건은 같은 자체 Agent, **Technology News (리소스 133018)** 실행에서 발생한 과거 기록이다. 현재 배포에는 자체 Agent를 내부 함수로 실행하는 경로가 들어 있으며, 실제 동일 도구 호출로 정상 동작과 Edge 출력을 확인했다.

- 실제 공개 Gateway tools/call 1회: HTTP 200, isError=false, 뉴스 결과 1건.
- 응답 전달: `X-Execution-Delivery: edge`, `X-Edge-Origin-Output: 1`.
- 공개 Gateway 최근 1시간 오류: **0건**.
- 선택한 최근 24시간의 과거 오류: **2건 유지**.
- Python·Worker·보안 자동 검사: **200개 통과**.

이번 작업에서 제품 실행 소스를 새로 바꾸거나 서버·Worker를 재배포하지 않았다. 이미 배포된 복구 경로를 대조·검증하고 회귀 검사 4개와 읽기 전용 진단 도구를 추가했다. 추가 재시작은 필요하지 않다.

## 정확한 원인

1. 19:07:34 KST에 Cloudflare Worker 공용 주소 `2a06:98c0:3600::103`에서 `/wp-admin/install.php` 스캐너 요청이 관측돼 900초 자동 차단이 적용됐다.
2. 19:15:32 및 19:16:05 KST에 Worker가 자체 Technology News의 공개 MCP 주소를 Provider처럼 HTTP 호출했다.
3. 두 요청은 차단 구간에 포함됐고, Origin 접근 로그에 해당 MCP 경로의 403이 남았다.
4. 같은 시각 실행 원장 2개는 resource_id=133018, backend=worker, state=failed, error_code=PROVIDER_AUTH_REQUIRED였다.
5. 출력 관측에는 각 요청 직후 `error:public:edge_error`가 1개씩 기록됐다. 이 일반 분류만으로 보면 Worker 전달 장애처럼 보일 수 있지만, 실행 원장과 Origin 로그를 함께 보면 자체 Provider 접근 거부와 일치한다.

근거:

- recorded-output-errors.json: 출력 오류 2개와 시각.
- correlated-execution-security.json: 대응 실행 실패·스캐너 차단·403 기록.
- Origin 접근 로그: logs/services/biz.agentconcierge.498590e0b3.frontend.a.log의 해당 시각.
- execution-failure-groups.json: 최근 24시간 실행 실패 6개 중 Technology News 2개와 전날 Research Papers 4개를 구분한다. 이를 공개 출력 오류 6건으로 합산하지 않는다.

Cloudflare의 공식 문서는 서로 다른 Zone으로 향하는 Worker subrequest에서 위 공용 주소가 사용될 수 있다고 설명한다. 이번 개별 호출의 구체적인 Zone 경로까지 기록돼 있지는 않으므로 이를 임의로 확정하지 않았다. 공용 주소 차단과 자체 MCP 403의 관계는 실제 서버·실행 기록으로 확인했다.

## 현재 적용된 정상 경로

현재 Frontend·Admin 활성 릴리스는 검사 시점 `b2a-schema-20261025-r1`이다. 다음 파일이 작업 소스와 일치했다(active-local-dispatch.json).

- `edge_gateway/router.py`: public-prepare에서 자체 소유 리소스를 별도 Worker Provider 실행권으로 만들지 않고 기존 플랫폼 실행 경로로 보낸다.
- `owned_data_agents/dispatch.py`: 정확한 자체 소유 key/source/URL/Schema를 검사하고 로컬 handler를 호출한다.
- `concierge/proxy.py`: 자체 Agent를 외부 공개 MCP 주소로 재호출하지 않고 로컬 dispatcher로 연결한다.

실행 위치와 출력 전달 위치를 분리한다. 자체 Agent 계산은 플랫폼 내부에서 한 번 수행하고, 응답은 기존 Cloudflare Worker를 통해 사용자에게 전달한다. 실제 공개 응답의 Edge 헤더로 전달 위치를 확인했다.

Cloudflare 공용 주소 전체를 허용 목록에 넣거나 스캐너 차단을 해제하지 않았다. 격리 회귀 검사에서도 공용 주소의 차단 상태를 그대로 유지한 채 자체 Gateway 실행이 성공하는지 확인했다.

배포된 Worker의 소스는 작업 소스와 같았다. 활성 버전과 소스 해시는 worker-live-before.json, 실제 코드 사본은 worker-live-before.mjs다. 이번 문제의 복구 확인을 위해 불필요한 Worker 배포는 하지 않았다.

## 검증 범위

### 추가한 회귀 검사 4개

1. 자체 Agent public-prepare가 외부 Worker 실행권·실행 행을 생성하지 않는지 확인.
2. 공용 Worker IP가 차단된 상태에서도 자체 MCP 실행이 내부에서 성공하며, 자신의 공개 주소로 HTTP 요청하지 않는지 확인.
3. 공개 MCP Gateway가 자체 handler를 한 번만 호출하고 Edge로 응답하는지 workerd에서 확인.
4. 공개 Testbench도 같은 단일 실행·Edge 전달 조건을 유지하는지 확인.

### 결과

- Python 관련 회귀: **59 passed**(python-regression-final.log).
- 실제 workerd/Miniflare Worker 회귀: **75 passed**(worker-regression-complete.log).
- 자체 Agent 및 Frontend 보안: **66 passed**(security-regression.log).
- 공개 콘텐츠 정책: **273 files / 0 violations**(content-check.log).
- 실제 공개 tools/list: HTTP 200, 도구 1개, Edge 전달(live-metadata-probe.json).
- 실제 Technology News 도구 실행: HTTP 200, 오류 없음, 결과 1건, Edge 전달, 약 2.1초(live-public-execution.json).

격리 검사의 원천 데이터는 모의 처리했다. 운영 검증에서는 자체 Agent 공개 호출을 1회 실행했다. 장기 부하 검증이나 전체 Provider 검증으로 확대 해석하지 않는다.

첫 Worker 시험은 sandbox의 로컬 listen 제한으로 실패해 허용된 임시 workerd 실행으로 다시 검증했다. 추가 테스트 작성 중 fixture 설정 두 가지(None Redis와 잘못된 Testbench 기본 인자)를 바로잡은 뒤 최종 검사에서 통과했다. 제품 실행 소스 오류로 집계하지 않는다.

## 모니터링 해석과 진단 보강

대시보드의 오류 2건은 선택 기간의 누적 이력이다. 이전 행을 삭제하거나 성공으로 바꾸지 않았다. 최근 1시간 필터에서는 이 두 건이 제외되며, 확인 시점 오류는 0건이었다.

출력 오류와 실행 원인을 분리하는 읽기 전용 진단 도구를 추가했다. 대시보드 UI 자체를 변경한 작업은 아니다.

```
PYTHONPATH=. .venv/bin/python reports/edge-public-errors-2026-10-25/inspect-current.py
```

이 도구는 최근 1시간·24시간·실검증 이후 공개 출력 오류 수와 실행 실패 사유를 별도로 조회한다. 입력·출력 본문, 방문자 프로필, Secret을 읽거나 출력하지 않으며 오류 이력을 바꾸지 않는다. 결과는 current-diagnosis.json에 있다.

## 논문·공식 문서·SNS 근거

- [Cloudflare HTTP 헤더 공식 문서](https://developers.cloudflare.com/fundamentals/reference/http-headers/): Worker subrequest에서 사용하는 공용 주소의 의미를 확인했다.
- [Discord API 공식 저장소의 Worker 차단 사례](https://github.com/discord/discord-api-docs/issues/7146): 동일 공용 주소의 차단이 서로 다른 Worker 요청에 영향을 주는 사례를 대조했다.
- [Cloudflare Reddit 관련 논의](https://www.reddit.com/r/CloudFlare/comments/1lehg3l): 원글은 삭제돼 남은 댓글의 proxy 신뢰 경계 논의만 참고했다. 개별 서비스의 오류 증거로 사용하지 않았다.
- [ExoFlow, OSDI 2023](https://www.usenix.org/conference/osdi23/presentation/zhuang): 실행과 복구를 구분하는 설계를 참고했다. 이번에는 차단을 만난 실행을 Origin에서 무작정 반복하는 대신, 자체 Agent의 실행 경로와 결과 전달 경로를 분리하는 기존 구현을 검증했다. Exactly-once를 서비스 전체에 대해 증명했다고 표현하지 않는다.
- [Cloudflare 오류·예외 공식 문서](https://developers.cloudflare.com/workers/observability/errors/): Worker 런타임 오류와 Origin/Provider 응답 실패를 구분해 확인했다.

현재 정상화 판정은 논문이나 SNS 주장 자체가 아닌, 해당 시각의 실행 원장·403 로그·활성 코드 대조·격리 검사·실제 공개 Gateway 응답에 근거한다.
