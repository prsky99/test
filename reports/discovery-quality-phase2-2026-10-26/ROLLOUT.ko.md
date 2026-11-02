# 검증된 품질 릴리스 반영

릴리스: `discovery-quality-20261026-r1`. 패키지 Hash 검증 완료. 신규 테이블·Secret·Schema 마이그레이션 없음.

프로젝트 디렉터리에서 다음 명령을 순서대로 실행한다. Frontend·Admin은 기존 A/B 배포를 사용하고, Worker는 기존 진행 작업 보호·교체 절차를 사용한다. 운영 전환은 이번 개발 작업에서 실행하지 않았다.

```sh
agentcon deploy frontend discovery-quality-20261026-r1
agentcon deploy admin discovery-quality-20261026-r1
agentcon worker-deploy jobs discovery-quality-20261026-r1
agentcon worker-deploy execution discovery-quality-20261026-r1
agentcon status
```

반영 후 확인할 내용:

1. Frontend의 기존 검색·Chat·Workspace와 `/mcp/compact` 계약 유지.
2. Admin의 공개 서비스 → **탐색·생성 품질**. 해당 역할에서 요청을 처리한 후 관측 시각·건수·내부 처리시간 확인. 역할별 Snapshot은 최대 30초 간격이고 실제 요청이 없으면 지표가 비어 있을 수 있다.
3. 현재 Source·Schema·권한 조건을 통과한 요청만 추천·검토 대상으로 제공되는지 확인.
4. Edge 우선·Origin 복구 및 승인·결과 불명 상태의 기존 보호 유지.

현재 운영 전체 Provider 성공률이나 운영 SLA 달성으로 표시하지 않는다. 구체적인 실패가 있으면 이전 유지 릴리스와 로그를 확인한 뒤 기존 Rollback 절차를 사용한다.
