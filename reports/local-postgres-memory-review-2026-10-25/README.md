# 재시작·PostgreSQL 14 정지·메모리 점검

2026-10-25

## 재시작 확인

Frontend·Admin 활성 릴리스는 `web-20261025-202033-b4d1`이다. PostgreSQL scalar 파라미터 수정 파일이 작업 소스와 일치하며 두 서비스 모두 readiness=true였다. Jobs·Execution의 PID 생존도 확인했다.

## PostgreSQL 14 — 미사용 상주 서버 정지 완료

- Homebrew의 PostgreSQL 14.22, 포트 5432, 부모 PID 1680을 확인했다.
- Agent Concierge의 현재 DB는 별도 PostgreSQL 18.6, 포트 55432다.
- 두 차례 확인에서 감사용 접속을 제외한 클라이언트 세션·진행 중 사용자 트랜잭션·복제 연결·활성 복제 슬롯이 0개였다. 정지 직전 활성 구독도 0개였다.
- 검사한 사용자·시스템 LaunchAgent/LaunchDaemon 및 crontab에서 PostgreSQL 14의 자체 시작 항목 외에 관련 실행 참조가 발견되지 않았다. 현재 프로젝트의 활성 설정 참조에서도 관련 항목이 발견되지 않았다.
- PostgreSQL 14에는 다른 프로젝트용 DB가 저장돼 있었다. 이 파일들은 삭제하지 않았다. 미래에 다른 프로젝트를 다시 실행할 때 PostgreSQL 14가 필요할 가능성은 남아 있다.
- 사용자 요청에 따라 `brew services stop postgresql@14`로 정상 정지했다. 종료 코드 0, Homebrew 상태 none, 5432 닫힘, postmaster.pid 제거, PG_VERSION과 데이터 디렉터리 보존을 확인했다.
- 정지 후 Frontend·Admin readiness와 Jobs·Execution 생존을 다시 확인했다. 운영 PostgreSQL 18의 시작 시각이 유지됐고 읽기 전용 차단 조회도 성공했다(postgres18-after.json).

이 판단은 현재 사용 연결·서비스 설정·검사한 자동 실행 작업에 근거한다. PostgreSQL 14의 설치 도구와 보관 DB 자체가 영구적으로 불필요하다는 판단은 아니다.

다른 프로젝트에서 다시 필요할 때:

```
brew services start postgresql@14
```

## 앱 메모리 점검

점검 순간 앱과 자식 프로세스의 RSS 합계다. 공유 메모리가 중복될 수 있으므로 고유 물리 메모리나 종료 시 회수량과 같지 않다.

- ChatGPT: 약 1.8 GiB. 현재 Codex 작업과 도구 프로세스를 포함하므로 유지했다.
- Google Chrome: 약 1.2 GiB. 사용하지 않는 창·탭이 있으면 정리할 후보이며, 현재 작업 여부는 프로세스 수치만으로 확정하지 않았다.
- Antigravity: 약 1.2 GiB. 다른 개발 작업을 마쳤을 경우 종료를 검토할 수 있다. 작업 중이라면 유지해야 한다.
- Ollama: 약 0.5 GiB. Jobs PID 7718이 로컬 11434 포트에 실제 연결 중이므로 유지했다.
- Redis: 실행 중이며 프로젝트 구성 요소이므로 유지했다.
- 이전 A/B 릴리스의 Frontend·Admin 프로세스 2개: 본체 RSS 합계 약 74 MiB. 관리 중인 이전 슬롯이며 롤백 용도로 유지했다.
- Chrome Remote Desktop과 macOS 시스템 앱은 종료하지 않았다.

PostgreSQL 14 외에 미사용이 확정된 앱은 없었다. 그 밖의 앱을 임의로 종료하지 않았다. 메모리 점검 시 스왑 사용량은 약 0.8 GiB였으며, 누적 스왑 통계를 현재 장애로 해석하지 않았다.

## 확인 자료

- restart-check.json: 새 릴리스 준비 상태.
- postgres-usage-before.json: PostgreSQL 14/18 버전·포트·연결 비교.
- memory-and-autostart-before.json: 앱별 RSS와 자동 실행 참조 검사.
- service-dependencies.json: 관리 서비스 슬롯 및 로컬 모델 의존성.
- postgres14-stop.json: 미사용 재확인과 정지 결과.
- after-stop-services.json: 정지 후 네 서비스 상태와 5432 닫힘·DB 파일 보존.
- postgres18-after.json: 운영 PostgreSQL 18의 시작 시각 유지와 읽기 전용 조회.
