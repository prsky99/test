# 사용자 지정 가상 고객·로컬 PostgreSQL 마감 검증

2026-10-20 KST. 사용자는 실제 고객을 가상 고객으로 대체하고 별도 로컬
PostgreSQL DB에서 검증하도록 지정했다. ChatGPT 추론은 보류하고,
Gemini/Claude 구독 로그인은 제외·기록만 유지하며, 결제 TEST/Connect,
hosted CI와 동료 승인은 보류했다. 현재 범위의 작업을 완료했다.

## 변경 및 검증

제품 런타임은 수정하지 않았다. 재사용 가능한
`scripts/validate_postgres_acceptance.py`, 안전 경계 테스트,
`docs/SYNTHETIC_ACCEPTANCE_RUNBOOK.md`, 연결 설정 예시와 현재 범위 기록을
추가했다. 최초 검증 후 별도 작업에서 CSS2개와 UI 테스트1개가 바뀌어 해당4개 모듈을 다시 검증했다. 운영 서버와
기존 데이터베이스·자격증명을 교체하거나 재시작하지 않았다.

- 최신 프론트엔드 영향: `delta.xml` 138개 통과.
- 가상 고객/조직/역할/다중 워크플로우/SDK/A2A/TLS 알림/복구:
  `synthetic-customer.xml` 213개 통과.
- 새 CLI 안전 경계·고객 링크 숨김·동의·암호화/키·SDK·콘텐츠:
  `security.xml` 111개 통과.
- 가상 평가자·신뢰 증거·코퍼스·프로토콜:
  `synthetic-evidence.xml` 79개 통과.
- 최종43개 모듈/고유542개, 실패·오류·skip 0. 최초541개 중 영향 모듈64개 사례를 최신65개로 교체하고, 영향이 식별되지 않은477개를 유지했다. 사례 ID 중복/누락을 대조했고 교체 검사 중 추가 소스 변경은 없었다. 최종542개 전체를 한 번에 새로 실행한 것은 아니다.
  마지막 CLI 테스트17개 재확인은 합산하지 않는다. 기존5,796개 고정
  후보 전체를 이번에 새로 실행한 것으로 표시하거나 결과를 합산하지 않는다.
- 공개 콘텐츠217개 파일 위반0, HTML mirror 일치,
  SQL catalog3,473개 문장/223개 테이블 일치.
- 새 CLI·테스트 Ruff0. 새 CLI만의 Bandit High0/Medium1/Low6.
  Unix socket 경로·환경변수명·가상 토큰·shell 없는 명시적 PostgreSQL
  도구 호출 경고를 `bandit-review.json`에서 검토했다. 전체 저장소의
  기존 경고가 사라졌다는 의미가 아니다.

## PostgreSQL 실검증

기존 로컬 PostgreSQL14.22를 사용하고 운영 DB는 읽거나 복제하지 않았다.
최종 신규 DB는 다음 두 개이며 검토를 위해 보존했다.

- `ac_validation_c3a0bf4844a0e2363047`
- `ac_validation_c3a0bf4844a0e2363047_restore`

`postgres-final/result.json`: 애플리케이션223개 테이블, 가상 고객3명,
조직 초대·다른 고객 접근 거부·별도 고객 권한·명시 실행·재생 방지·SDK
PKCE·실행·ZIP 토큰 비포함·철회와 로그아웃 보존 등18개 검사 통과.
8개 연결/800개 트랜잭션의 완료 수와 counter 값이 정확히 일치했다.
한 번의 claim 승자와 오래된 fence 거부, 롤백·재연결도 확인했다.

로컬 관측값: 트랜잭션 p95 약2.11ms, 논리 백업 약0.19초,
논리 복원 약0.28초. 백업 이전 커밋 유실0, 의도적으로 백업 뒤 기록한
1건은 복원되지 않았다. 결과/체크포인트 해시와 철회된 고객 세션 보존을
확인했다. 이는 작은 가상 SQL 부하의 관측이며 운영 애플리케이션의 SLA,
HA 승격, WAL/PITR, 전체 장애 RTO 또는 운영 RPO 보장이 아니다.

도구 개발 중 psycopg TLS 상태 속성명과 직접/SDK 실행기의 구성을 보완했다.
초기 실패는 테스트 도구 구성 오류였고 제품 보안 검증을 낮추지 않았다.
예비 DB6개는 해당 실행의 소유 표시를 확인한 뒤 정리했다.
`fixture-cleanup.json`과 초기 결과를 보존했다. 최종 원본/복원 DB만 남겼다.

다른 서버에서는 [실행 절차](../../docs/SYNTHETIC_ACCEPTANCE_RUNBOOK.md)를
따라 owner-only 연결 파일과 검증된 TLS를 사용한다. 도구는 임의 기존 DB를
쓰기 대상으로 받지 않고 항상 신규 DB2개를 만든다. 기존 서버를 시작·중지·
재구성하지 않는다. 최종 dump/result는0600, 결과 디렉터리는0700이다.
덤프에는 이 실행의 가상 데이터만 들어 있다.

## 공개 GET 클라이언트 차단 해결

`gateway-edge.json`: 기본 Python은 공개2개 경로에서 Cloudflare1010/403,
동일 로컬 요청과 명시적 서비스 클라이언트는200이었다. 컴퓨터유즈로
Cloudflare의 Browser Integrity Check가 켜져 있음을 확인했다.

사용자가 적용 직전 **두 공개 GET 경로에만 적용**을 승인했다.
규칙 `Public agent discovery GET compatibility`를 활성화했고,
조건은 아래와 같다. 다른 설정은 규칙에 포함하지 않았다.

```
(http.host eq "agentconcierge.biz" and http.request.method eq "GET" and http.request.uri.path in {"/.well-known/agent-card.json" "/api/test/presets"})
```

동작: Browser Integrity Check off.

`gateway-edge-after.json`: 기본 Python의 두 GET은200으로 전환됐고,
규칙 밖 HEAD /agent-card, POST /api/test/presets, GET /는403을 유지했다.
이 대조는 해당 요청의 결과이며 모든 보안 규칙의 침투 검증은 아니다.
WAF·DDoS·인증·속도 제한과 관리자/실행 경로의 설정을 바꾸지 않았다.
필요한 rollback은 Cloudflare Configuration Rules에서 이 이름의 규칙만
비활성화하는 것이며, 전역 Browser Integrity Check는 그대로 둔다.

설정 전: `cloudflare-rule-review.png`.
활성 확인: `cloudflare-rule-active.png`.

## 보류와 판정

ChatGPT 실제 추론을 호출하지 않았다. Gemini/Claude 로그인도 시도하지
않았다. 이전 Gemini UNSUPPORTED_CLIENT를 한도 초과로 단정하지 않고,
Claude 개인 CLI 통과를 hosted 고객 연동으로 승격하지 않는다. 금융·광고·
hosted CI·외부 메시지 발송은0이다.

Workspace 공개 탐색 링크는 숨김을 유지한다. 가상 테스트 완료와 별도로,
사용자의 명시적 공개 활성화 지시에 따라 변경한다. 공개 결정 외 결제·CI·
동료 승인 항목은 보류하며 자동으로 다음 개발 과제에 재편입하지 않는다.

가상 Push·평가자·복구 키 및 A2A 제공자는 통제된 시험 대상이다. 실제
기기 알림 클릭, 독립 외부 기관의 평가, 실제 외부 A2A 사업자의 수용을
완료했다는 주장이 아니다. 원래42개 요구/실제 운영 판정은 이력을 유지하고,
[현재 사용자 범위](../../docs/current-synthetic-closeout.json)의 종료를 구분한다.

근거: `late-ui-impact.xml`, `late-source-change.json`, `verification.json`, `test-selection.json`, `source-before.json`,
`source-drift.json`, `source-final.json`, 개별 JUnit/XML과 PostgreSQL 결과.
서버 재시작은 필요하지 않으며 이번 범위의 자동 개발 대기 항목은 없다.
