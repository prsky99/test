# LLM 기본 서버와 폴백 서버 연결

- 기본: `http://192.168.0.24:8000/v1`
- 폴백: `http://192.168.0.25:8000/v1`
- 모델: `gemma4-e4b-mlx`, OpenAI-compatible 방식 유지

두 주소의 `/models`가 HTTP 200과 같은 모델 ID를 반환했다. 이 연결 확인에서 실제 생성 프롬프트나 사용자 데이터는 보내지 않았다.

## 동작

각 새 요청은 기본 서버를 먼저 사용한다. 응답 헤더 수신 전 연결·timeout·전송 장애 또는 HTTP 408/425/429/5xx이면 동일 모델·동일 입력으로 폴백 서버를 한 번 시도한다. 다음 요청은 기본 서버를 다시 먼저 확인한다. 다른 모델이나 로컬 Ollama로 자동 변경하지 않는다. 인증·입력 오류, redirect, 잘못된 모델/결과, 일부 출력 수신 후 단절은 기존 실패 처리와 검증을 유지한다. 양쪽 모두 실패하면 기존 안내/규칙·검토 절차로 처리한다.

Workspace 자동 생성, AI 수정 안내, Workflow Composer, RAG, 공통 LocalLLM에 적용했다. 부모 실행권과 생성 결과의 별도 검토·저장·실행 권한을 유지했다. 원천 Provider 실행 재시도 정책은 바꾸지 않았다.

## 설정과 호환성

`gateway-data/local-model.env`의 기본 URL을 .24로 변경했다. 새 `gateway-data/local-model-fallback.env`에 `WORKSPACE_MODEL_FALLBACK_URL`을 .25로 설정했다. 두 파일은 owner-only 0600이며, 이전 릴리스가 새 키를 strict parser로 거부하지 않도록 폴백 설정을 별도 파일로 분리했다. 이전 기본 설정은 private backup으로 보존했다. IP·모델·장애 정보는 공개 프론트 문구에 추가하지 않았다.

## 검증

신규 폴백·권한·설정 테스트 28개 통과. 실제 Frontend·Admin 준비 패키지에서 관련 회귀 각각 75개 통과. 기존 넓은 회귀는 217개 통과했고, 임시 PostgreSQL 초기화 1건은 macOS 공유 메모리 자원 한도로 실패했다. 별도 initdb 진단에서 `shmget ... No space left on device`를 확인했다. 디스크 부족이나 LLM 응답 실패로 분류하지 않는다. 시스템 IPC/커널 설정과 운영 DB는 변경하지 않았다.

오프라인 Chromium 보안·승인 UI 회귀 9개 통과. 수정 모듈의 문법 검사, 고정 주소·HTTP opt-in·redirect 차단·응답 크기·권한 guard·개인 데이터 비공유를 검토했다. 실제 추론 성능 측정과 운영 DB round-trip의 이번 환경 재검증은 완료 범위에 포함하지 않는다. 테스트 초기 assertion의 잘못된 키는 수정했고, 최종 두 패키지 검증에서 통과했다. 초기 로그도 보존한다.

## 운영 반영

Frontend·Admin의 현재 운영 릴리스를 복제해 이번 변경 10개 파일만 patch로 반영했다. 역할마다 나머지 manifest 파일 1,162개를 그대로 보존했다. `staged-releases.json`과 `implementation.patch`가 검토 대상이다. Jobs·Execution은 이번 웹 생성 연결 반영의 재시작 대상에서 제외한다. 기존 Native Edge 활성화와 무료 한도 폴백 정책은 유지한다.

`activate-llm-standby.py`는 기본 실행 시 계획만 표시한다. `--apply`는 기존에 명시적으로 승인된 Frontend·Admin A/B 반영 범위에서만 사용한다. 기준 릴리스가 달라지면 반영을 중단한다. 이전 슬롯을 보존하며, 실패 시 이전 기본 설정 복원과 이미 전환한 역할의 rollback을 시도하고 불확실한 역할은 별도 기록한다. 새 Secret과 DB 마이그레이션은 없다.

현재 단계: **2026-10-24 16:00 KST 운영 A/B 반영 및 사후 검증 완료.** Frontend·Admin 준비 상태, 페이지·정적 파일·권한 경계, 두 LLM의 같은 모델 가용성을 확인했다. Jobs·Execution의 릴리스와 PID가 기존과 동일하고 Native Edge 활성화가 유지됨을 확인했다. 실제 운영 추론에 대한 장애 주입은 수행하지 않았으며, 서버 전환은 합성 HTTP 장애 테스트로 검증했다. `activation-verification.json`이 최종 확인 기록이다.
