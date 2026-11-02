# 전면 게이트웨이 개선 구현·검증 결과

2026-10-17 · 기존 검토 F01–F08에 대한 구현 후 검증

앞서 확인한 8개 개선사항을 구현했다. 검증은 격리 API·일회성 SQLite·통제된 제공자·실제 Chromium·인증서를 검증하는 로컬 TLS 통신으로 진행했다. 운영 서버 재시작, 운영 DB 변경, 실제 제공자에 대한 실행·공격 검사는 수행하지 않았다.

## 반영한 변경

1. **F01 · 실제 연결 경로:** `/api/gateway/{kind}/{id}`에 MCP stateless JSON-RPC, A2A 동기 메시지, x402 GET probe/명시적 probe wrapper를 구현했다. 지원하지 않는 스트리밍·세션·장기 task 조회·취소·자동 결제는 광고하지 않는다. 등록 ID와 프로토콜을 검증하며 미등록 대상·임의 URL/인증/콜백 덮어쓰기를 허용하지 않는다.
2. **F02 · 공통 공개 응답:** 추천 단계에 공통 projection을 적용해 REST Chat·MCP·A2A·업데이트 추천의 원본 호출 주소를 관리형 연결 주소로 바꾼다. 상세는 공개 필드 allowlist를 사용한다. 실제 DB의 호출 주소와 원본 보고서는 변경하지 않는다.
3. **F03 · 실행 진입점:** Testbench와 신규 연결은 공통 active/health/quarantine/auth/input 검증 및 MCP 프록시를 사용한다. 기존 MCP call·workflow에도 공통 최소 admission/입력 검증이 적용된다. 등록된 안전 도구와 pinned capability hash를 확인하고 실제 호출 전 전체 live schema도 검증한다. 기존 별도 승인·원장 경로의 머신 계약은 유지한다.
4. **F04 · 출처 보존:** 모든 외부 URL을 바꾸는 정책을 제거했다. 명시적인 호출/발견 바인딩을 치환하고 뉴스·문서·결과 링크는 보존한다. 같은 제공자 도메인의 문서 링크와 중첩·이중 JSON 보고서도 검사했다.
5. **F05 · 관측 구간 정정:** Inspector는 실제 `/api/test/execute`의 정제된 client request를 보여 준다. 응답은 gateway result summary로 명시한다. 시간은 gateway processing 범위이며 브라우저 RTT나 provider 전용 latency로 표시하지 않는다.
6. **F06 · origin 경계:** scheme·hostname·port·userinfo를 URL parser로 검사한다. 접미사 도메인·userinfo·다른 포트를 관리형 origin으로 인정하지 않는다. ID 없는 항목이나 데모에 가짜 대체 실행 주소를 만들지 않는다.
7. **F07 · 데모 정직성:** 4개 프리셋은 Demo이며 provider 호출·실측 품질 등급·실제 금융 결과·실행 성공을 주장하지 않는다. 인위적 sleep/latency 가산을 제거했다. 이전 캐시·허위 성공 형태의 구버전 세션 이력은 재사용하지 않고 관련 없는 사용자 설정·워크플로우는 유지한다.
8. **F08 · 결과 구분:** transport·protocol·task state·execution success를 분리했다. A2A working/failed/mismatched-id, MCP tool error, 잘못된 x402 challenge를 완료로 처리하지 않는다. 402 challenge는 검증되어도 실행 성공이 아니다.

Home/Test 메타데이터·소셜 설명·화면 설명을 현재 동작에 맞추고 CSP·이스케이프·영어·Lucide 기반 표시를 유지했다. 새로운 managed 호출은 개발용 private-network 허용 설정을 물려받지 않으며 동시 실행 4개·대기열 없음·deadline/응답 크기 제한을 적용한다. 타임아웃된 worker는 끝날 때까지 슬롯을 유지한다.

## 기능·동적 보안 검증

**고유 테스트 494개 통과, 중복을 포함한 실행 500회 통과.** 최종 숫자는 [verification.json](verification.json)의 테스트별 XML 집계를 기준으로 한다. 중복 실행을 제외한 고유 테스트와 전체 실행 횟수를 별도로 기록한다. 모든 최종 suite의 failure/error/skip은 0이다.

- `api-security.xml`: 연결 handshake·실제 허용 tool call·추천 3채널·미등록/파괴적/비활성/격리/스키마 drift/타입 오류 거절, 출처·중첩 JSON 보존, 실제 request body 대조, A2A 상태·버전·x402 challenge.
- `boundaries.xml`: private DNS·연결 직전 DNS rebinding·개발 설정 상속 차단, 4개 worker timeout 중 추가 요청 거부, 잘못된 challenge, 등록 A2A guide/method 바인딩 및 초기 로딩 성능.
- `browser-security.xml`: Chromium에서 데모/완료/대기 표시·출처·XSS/CSP·origin lookalike·구버전 캐시 제거·이력 export·반응형 Chat, 공개 ZIP과 어드민 SDK 앱의 다른 호스팅 실행·취소·철회.
- `transport-compatibility.xml`: 본문/응답 크기·timeout·인증·헤더·공통 transport·기존 workflow/REST/x402·알림·프로토콜 기본값·어드민 배포 호환성.
- `verified-delivery.xml`: 실제 TLS socket을 통한 MCP/A2A/x402 연결, webhook/A2A inbox 인증·서명 전송·중복·변조·철회. 테스트용 DNS/전송 매핑만 사용하며 운영 egress 제한은 완화하지 않았다.

공개 frontend 콘텐츠 검사 **51개 파일, 위반 0건**. embedded HTML과 `extracted_html.txt` 일치. Python compilation과 변경 파일 whitespace 검사 통과.

공개 workflow SDK 원본 SHA-256은 이전 기준과 동일하다. 패키지의 SDK·app JS·CSS·README·manifest 5개도 이전 hash와 일치하며 HTML은 내보낼 때마다 새 CSP nonce를 발급한다. 공개 v1.0 및 어드민 v1.1 실행·다운로드 회귀를 통과했다.

## 시큐어코딩 점검

Bandit의 신규 3개 모듈 경고는 **0건**, 전체 검사 파일의 High는 **0건**이다. 전체 파일 scan에는 기존 Medium 9건·Low 12건이 남아 있으며 모두 무경고인 결과로 표현하지 않는다.

- SQL 구성 경고 9건: 고정/allowlist SQL 조각과 `?`로 바인딩한 값의 조합인지 검토했다. 검색·등록·프로토콜 injection 회귀에서 사용자 문자열이 SQL 구조를 바꾸지 못하는지 검증했다.
- 예외 처리 경고 12건: 기존 optional metadata 파싱 및 protocol fallback 부분이다. 신규 실행 경로에서 정책 거절·파싱 오류·프로토콜 오류가 실행 성공으로 전환되지 않는지 검사했다. 경고 원문은 `bandit.json`에 보존한다.
- 변경된 연결 경로에서 임의 목적지/Host/인증 전달, private IP/DNS 변경, 원격 schema 참조·regex 평가, 무제한 body/response/queue, 잘못된 JSON-RPC id, HTML/script 실행과 원본 바인딩 노출을 점검했다.

## 운영 적용 범위

소스 구현과 격리 검증이 완료된 상태다. 사용자가 터미널에서 실행 중인 서버를 재시작하거나 자동 reload가 반영되어야 새 코드가 적용된다. 실제 운영 reverse proxy 경로·배포 버전·전 세계 제공자 가용성은 이번 격리 검사로 확인한 사항이 아니다.

공개 연결은 문서화한 제한 profile이다. 장기 A2A task 영속 처리, 전체 schema version registry, 조직/배포별 권한과 상용 결제·정산, 운영 성능 SLA 및 G0의 전체 운영 승인까지 완료했다고 의미하지 않는다. HTTP 200이나 구조가 맞는 challenge만으로 provider 품질/권한/정산을 보증하지 않는다. 자연어 screening도 독립 제공자의 내부 동작을 완전히 제한하는 sandbox가 아니다.

구현 계약: [MANAGED_AGENT_GATEWAY.md](../../docs/MANAGED_AGENT_GATEWAY.md). 증적: `verification.json`, `source-snapshot.json`, `bandit.json`, suite XML, `testbench-completed.png`. 이전 검토 보고서와 재현 증거는 과거 상태로 보존했다.
