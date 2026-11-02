# 고도화 설계 v1.1 — 전면 게이트웨이화 반영

설계 기준일: 2026-10-17. 사용자 첨부와 진행 중 작업 소스를 읽고 설계서·구조화 백로그·기존 Canvas를 수정했다. 운영 배포나 게이트웨이 보안 검증 완료 보고서가 아니다.

## 변경한 설계

1. **P0 공통 게이트웨이 계층:** 공개 projection, 안정적인 agent ref, 실제 호출 profile, 내부 원본 바인딩과 공통 admission을 분리했다. 내부 resources.url은 게이트웨이 주소로 덮어쓰지 않는다.
2. **공개 표면 전체 적용:** Explore/Chat/Testbench/리포트/로그 다운로드/머신 탐색/관련 메타데이터·캐시를 점검 범위로 정의했다. 원본 실행 주소·비밀값을 숨기되 뉴스·문서 출처와 고객 수신처를 일괄 치환하지 않는다.
3. **실제 연결의 진실성:** 지원되는 wrapper/MCP/A2A 계약만 광고한다. 현재 Concierge /mcp 탐색 도구와 임의 제공자 도구 프록시를 구분한다. 검토 중 도입된 /api/gateway/{proto}/{rid}는 실제 handler·scope·프로토콜을 확인해 registry에 연결하는 대상으로 반영했다. v2 경로는 신규 계약 예시이며 기존 별칭의 재구현 요구가 아니다.
4. **Wire·Telemetry:** 실제 client_to_gateway 구간의 endpoint/method/body와 측정값을 표시한다. upstream wire의 URL만 바꿔 브라우저 패킷처럼 표시하지 않는다. 원문은 별도 관리자 권한으로 제한한다.
5. **보안·사업 경계:** 서버 인증·안전한 도구·schema·egress·quota·token audience는 주소 비노출과 별개다. 완전한 경유 강제·스크래핑 방지·자동 과금 동의를 주장하지 않는다. 결제 표준의 금액·수취인도 주소처럼 바꾸지 않는다.
6. **이후 기능 정렬:** AI 합성·폴백·알림·개발지원 예제와 원장이 같은 gateway ref/operation 정책을 사용하도록 변경했다. 게이트웨이 장애와 제공자 장애를 분리한다.
7. **G0와 백로그:** G0 Gateway Public Surface & Connection Readiness를 G1 앞에 추가했다. AC-00 공개 DTO/표면/이전 계약, AC-13 실제 연결/세션/task/공통 admission을 추가해 7개 모듈·14개 작업·4개 Gate로 정리했다. 범위 증가에 따른 일정 재산정도 명시했다.

## 유지한 사항

- 공개 workflow ZIP/SDK v1.0, 어드민 SDK v1.1의 다운로드·실행 호환성.
- 영어 공개 UI, Lucide·접근성·CSP, Chat의 단일 추천·기본 A2A·개인정보·상업 표현 정책.
- 목적별 연락처 검증·동의와 별도 광고 비활성 정책.
- 상용 과금은 조직 인증·별도 승인·원장/대사 Gate 이후에 검토하는 순서.

## 이번 작업의 검증 범위

문서/JSON/Canvas의 버전·작업 ID·의존성·Gate·소스 참조 일치, TSX 구문과 Canvas의 허용 import/inline data 조건을 확인했다. 새 기능의 동적 API/브라우저 보안 테스트는 이 설계 수정에서 실행하지 않았다. G0는 이후 구현 검증의 수용 기준이며 통과 완료가 아니다.

작업 중 다른 실행이 front.py와 extracted_html.txt를 변경하는 것을 관찰했다. 해당 변경은 사용자께서 진행 중이라고 알려주신 구현 작업으로 취급하고 그대로 두었다. 이번 작업은 제품 소스·실행 서버·운영 DB를 수정하지 않았다. 파일 해시 비교는 gateway-revision-verification.json에 기록했다.
