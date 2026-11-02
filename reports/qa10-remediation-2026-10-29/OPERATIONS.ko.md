# 추가 개선 적용 후보

2026-10-30(KST) 사용자 승인 후 아래 세 후보 적용 및 운영 API 확인을 완료했다. 기존 protocol-disclosures 웹 2개는 롤백용으로 유지한다.

- qa10-remediation-frontend-20261029-r1
- qa10-remediation-admin-20261029-r1
- qa10-protocol-disclosures-worker-20261029-r1
  - SHA-256: 8cc80a6d0e972efbc4b918b34bf87bdee65e5d9297ccdd4584d76331770d536e
  - 파일: worker-candidate.mjs
  - 기준 Worker: 84d45696-dd5c-4eec-9457-19f63d272ef0 (100%)

DB 스키마·jobs·execution·모델 서버 변경 없음. 현재 활성 릴리스에 검토한 변경 파일만 덧씌웠다. 전체 공유 작업 트리로 패키징하지 않았다.

아래는 승인 후 실행한 적용 명령의 기록이다. 현재 활성 버전이 바뀌었으므로 그대로 재실행하지 않는다. 새 배포는 현재 상태를 다시 확인한다.

```sh
./agentcon status
.venv/bin/python reports/qa10-remediation-2026-10-29/cloudflare-release.py inspect
./agentcon deploy frontend qa10-remediation-frontend-20261029-r1
./agentcon deploy admin qa10-remediation-admin-20261029-r1
.venv/bin/python reports/qa10-remediation-2026-10-29/cloudflare-release.py upload --apply
.venv/bin/python reports/qa10-remediation-2026-10-29/cloudflare-release.py deploy --apply
```

Worker는 고정 파일 해시, 현재 활성 버전, 최신 업로드가 실제 활성 버전인지, 계정·도메인·기존 바인딩을 검사한다. 기존 비밀 값은 읽거나 출력하지 않고 상속한다. 원래 일반 바인딩 값·설정은 보존하고 라우트는 변경하지 않는다. 기준이 다르면 덮어쓰지 않고 중단한다.

적용 후 실제 서비스에서 MCP 도구 4개의 주석, 일반 날씨·4턴 참조·의미 없는 검색어, 실제 입력창 포커스, 공개 OpenAPI를 확인한다. x402는 결제 없이 맨 경로의 첫 GET/POST 402 본문·헤더·검사 전용 안내를 확인한다. 제공자 결제 증명을 보내지 않는다. 운영 정책 차단을 억지로 발생시키지 않으며 통제된 403 분기는 격리 시험 증거와 구분한다.

배포 후보: candidates.json. PostgreSQL: frozen-verification.json. Worker 기준: worker-current.json. 화면·검증: verification-summary.json, isolated-ui-matrix.json, focus-target-assessment.json, chat-focus-*.png. API/과거 보고서 표본: live-triage.json, read-only-report-sample.json.
