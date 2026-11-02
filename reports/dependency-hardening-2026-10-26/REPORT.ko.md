# 의존성 정리·최신 보안 업데이트 결과

2026-10-26 기준. 사용자 승인 후 운영 반영과 최종 확인을 완료했다. 최신 프론트엔드의 화면 변경을 보존하기 위해 동일 보안 환경에 최신 소스를 포함한 `dependency-security-20261026-r3`를 준비했다. 프론트엔드는 이미 이 패키지와 파일·보안 환경이 모두 같은 최신 릴리스라 유지했고, 어드민·jobs·execution을 r3로 교체했다. PostgreSQL 서버와 모델 서버는 재시작하지 않았다.

## 정리 결과

운영 가상환경은 77개에서 60개 배포 패키지로 줄였다. 애플리케이션 의존성 59개와 pip 1개이며, 모든 패키지가 검토된 프로필과 정확히 일치한다. 실제 설치 내역은 `runtime-environment-final.json`에 남겼다.

- `sqlite-vec`: 운영 프로필에서 제거. 기존 SQLite 벡터 복구·마이그레이션 도구와 격리 호환성 테스트용으로 `requirements-legacy-sqlite.txt`에만 유지했다. Python 내장 `sqlite3`는 공유 코드 계약·테스트·복구 도구에서 여전히 참조하므로 삭제하지 않고 3.54.1로 갱신했다. 운영 DB는 PostgreSQL이고 벡터 확장은 pgvector 0.8.2임을 실제 읽기 전용 쿼리로 확인했다.
- `anthropic`: 현재 로컬 모델 경로에서 사용하지 않아 운영 기본 환경에서 제거했다. 기존 Claude 판매/분류 기능은 선택형으로 유지하고 SDK를 1.13.0에서 2.3.0으로 갱신했다. 선택형 SDK 없이도 서비스 모듈을 가져올 수 있게 지연 로딩하고, 실제로 해당 제공자를 선택할 때만 설치 안내를 제공한다. 주입한 테스트 클라이언트는 SDK 없이 작동한다.
- `httpx2`, `httpcore2`, `jiter`, `docstring-parser`, `sniffio`, `truststore` 등 기본 운영 프로필에서 더 이상 필요한 부모 의존성이 없는 항목은 깨끗한 환경을 새로 만들어 제거했다. 다른 프로필에서 실제 필요한 항목은 해당 프로필에만 설치된다.
- pytest·Playwright 및 테스트 전용 전이 의존성은 `.venv-tests`로 분리했다. pip-audit·pip-tools·사용 중인 빌드 도구는 `.venv-security`로 분리했다. setuptools·wheel·packaging은 운영 환경에서 제거했다. 정리 기준은 단순 import 검색이 아니라 소스의 직접 사용과 전체 전이 의존성이다.
- PostgreSQL 드라이버의 `psycopg-binary`를 제거하고 동일 버전 3.3.6의 `psycopg[c]`로 교체했다. 최신 binary 배포본에도 OpenSSL 3.5.8이 포함된 것을 실제 dylib 검사로 발견했기 때문이다. libpq 18.6을 패치된 OpenSSL 3.5.9 공유 라이브러리에 연결했다. PostgreSQL 서버는 설치하거나 재시작하지 않았다.

## 적용한 버전

- Python 3.11.8 → 3.11.18: 현재 사용하는 3.11 계열의 최신 보안 패치. 메이저 기능 버전 전환 대신 호환되는 보안 패치를 선택했다.
- Python TLS OpenSSL 3.4.0 → 지원 중인 LTS 계열 3.5.9. 별도 cryptography 50.0.2의 실제 내부 OpenSSL은 4.0.3으로 확인했다.
- PostgreSQL 클라이언트 libpq 18.6 유지, 내장 OpenSSL 3.5.8 → 검토된 공유 OpenSSL 3.5.9로 변경. 패키지 버전 문자열 외에 실제 로드된 라이브러리와 CA 번들까지 확인한다.
- certifi 2026.10.19 → 2026.10.23. Python의 기본 TLS 저장소와 libpq가 사용하는 신뢰 저장소에도 같은 검토된 번들을 적용했다.
- FastAPI 0.143.0 → 0.162.0, Starlette 1.8.0 → 1.10.0, pip 26.2.1 → 26.2.2.
- Playwright 1.64.0 → 1.64.1. 포함된 브라우저 드라이버 Node는 패치 버전 24.22.1로 확인했다.
- 프로젝트용 Node 26.12.1, npm 12.2.1을 별도로 준비했다. 기존 전역 Node 22.22.2·npm 10.9.7이나 Conda/Homebrew 설치는 변경하지 않았다. `cloudflare/edge-gateway/npmw`가 검토된 프로젝트용 도구를 사용한다.
- sharp 0.35.5, 호환 가능한 Undici 7.30.1, workerd 1.20261025.1을 선택했다. Wrangler 4.152.0과 Miniflare 4.20260730.0은 조사 시점의 공식 안정 배포를 유지했다. 이 전체 조합으로 Worker 검사 75개가 통과했다. Cloudflare에 실제 Worker를 배포하는 작업은 하지 않았다.
- bitarray 3.12.3, multidict 7.2.1, pycparser 3.12 등 호환되는 전이 의존성도 갱신했다.
- PyCryptodome의 최신 주 버전 4.2.0은 eth-keyfile의 `<4` 제약과 충돌해 최신 호환 3.24.1을 유지했다. Parsimonious·Playwright 하위 의존성·Undici도 부모 라이브러리가 지원하는 범위의 안정 버전을 사용한다. 제약을 무시해 결제·암호화 기능을 깨뜨리지 않는다.

## 보안 조사와 반영

기존 Python 패키지 77개의 공식 PyPI 메타데이터·취약점 정보를 대조했고, 완전한 의존성 잠금과 실제 설치 환경을 다시 감사했다. npm 잠금 감사에서는 수정 전 영향받는 패키지 4개(Undici·sharp와 이들을 포함하는 부모 패키지)가 확인됐고 수정 후 알려진 취약점 0건이다.

setuptools 84.0.0에는 [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w)가 등록돼 있었다. Windows의 레거시 wheel 설치 경로가 조건인 취약점으로, 현재 Mac 웹 서비스가 해당 방식으로 공격받았다고 판단한 것은 아니다. 운영에서는 필요 없는 setuptools를 제거하고 빌드·보안 도구와 ensurepip 부트스트랩에는 수정된 84.2.1을 사용한다.

최근 SNS에서 확산된 Brotli/Node 문제는 [Node.js 공식 2026-10-21 보안 공지](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases), [Brotli 공식 1.2.1 릴리스](https://github.com/google/brotli/releases/tag/v1.2.1), [PyPA 권고](https://github.com/pypa/advisory-database/blob/main/vulns/brotli/PYSEC-2026-4322.yaml)와 대조했다. 운영 Python에는 Brotli/brotlicffi가 설치돼 있지 않아 불필요한 디코더를 추가하지 않았다. 프로젝트 Node 및 Playwright 내부 드라이버는 공식 수정 버전으로 준비했다. [Aikido의 LinkedIn 공개 게시 내용](https://ea.linkedin.com/company/aikido-security/)과 [Python 커뮤니티 논의](https://www.reddit.com/r/Python/comments/1xe1zp2/cve2026111497_if_you_run_a_python_server_you/)는 이슈 탐지 자료로 사용했고, 실제 영향·수정 버전 판단은 공식 공지와 설치 내역을 우선했다.

[Python 3.11.18 공식 보안 내용](https://www.python.org/downloads/release/python-31118/)의 eMudhra/emSign 인증서 사고 대응과 Expat 2.9.0 등의 수정도 반영했다. [OpenSSL 3.5.9 보안 릴리스](https://www.openssl-library.org/news/openssl-3.5-notes/index.html)를 선택했고, [Psycopg 공식 로컬 C 설치 지침](https://www.psycopg.org/psycopg3/docs/basic/install.html#local-installation)에 따라 구 TLS 라이브러리를 별도 내장하는 binary 대신 검토된 libpq/OpenSSL에 연결했다.

## 재유입 방지

1. 운영·개발·보안·빌드·선택형 SDK별 정확한 버전과 전체 다운로드 해시를 잠금 파일에 저장했다.
2. 공식 소스의 SHA-256/SHA3/SHA-512를 검증하는 프로젝트 전용 도구 체인 준비 스크립트를 추가했다. 시스템 설치나 운영 프로세스를 변경하지 않는다.
3. 소스 배포만 있는 http-ece와 Psycopg C 확장은 검토한 해시와 고정된 빌드 도구로 빌드한다. 설치 시 임의의 빌드 격리 의존성을 가져오지 않는다.
4. 릴리스 패키징에서 생산용 프로필·Python 보안 패치 기준·실제 네이티브 libpq/OpenSSL 링크·CA 번들을 검증한다. 오래된 바이너리나 예상하지 않은 패키지가 있으면 패키징을 중단한다. 모든 잠금 파일과 비공개 런타임 내역을 릴리스에 보존한다.
5. npm 설치 생명주기 스크립트를 비활성화하고 안전한 Node 버전을 요구한다. PR/push CI에 Python 잠금 감사·npm 감사·Worker 검사를 추가했다. 예약 작업이나 자동 운영 배포는 만들지 않았다.
6. 실제 설치 내역의 SBOM은 `runtime-sbom-final.cdx.json`에 남겼다. 개인 설정·토큰·비밀값은 포함하지 않는다.

## 검증 결과

- 최종 Python/API·암호화·보안 회귀 453개 통과: `api-crypto-tests-r2.xml` / `.log`.
- 공개·어드민·워크스페이스 브라우저 및 관련 홈 통계 검사 80개 통과: `browser-security-tests.xml` / `.log`. 해당 앱 프레임워크·브라우저·Python 버전은 최종 조합과 같으며, 이후 변경한 C 드라이버는 API 회귀와 실제 DB 읽기 검증으로 별도 확인했다.
- 최신 Node·npm·workerd 조합의 Worker 서명·스트리밍·권한·정보 노출 경계 75개 통과: `worker-tests-r2.log`.
- 합계 608개 고유 검사 통과. 재실행한 동일 검사는 중복 합산하지 않았다.
- 운영 PostgreSQL 18.6과 pgvector 0.8.2 읽기 전용 검증 성공: `native-postgres-readonly-r2.json`. bigint·numeric·bytea·JSON·시간 값 전달 및 pgvector 코사인 거리 계산 성공: `native-postgres-adaptation-r2.json`. DB 쓰기는 0건이다.
- SDK 2.3.0 작업·분류 모의 응답 검증 성공: `anthropic-compatibility.json`; 실제 제공자 호출 0건. 최종 선택형 프로필에서도 네이티브 TLS 검증이 통과했다: `anthropic-environment-r2.json`.
- SDK와 SQLite 확장이 없는 운영 프로필에서도 공개 HTML/API와 PostgreSQL 벡터 파이프라인 진입이 가능한 것을 격리 점검했다: `production-profile-smoke.json`.
- 운영·개발·선택형 잠금에서 알려진 취약점 0건: `python-runtime-audit-r2.json`, `python-dev-audit-r2.json`, `python-optional-audit-r2.json`. npm 결과: `npm-after-r2.json`. 실제 설치 SBOM 감사도 통과했다.
- 공개 콘텐츠 292개 파일, 위반 0건. 변경된 보안·의존성 도구 및 선택형 SDK 모듈의 Ruff F/E9/S 검사 통과. SQL 카탈로그는 3,802개 문장·232개 테이블을 유지하며 동기화 검사가 통과했다.
- 기존 속도 제한 테스트는 호스트 Redis 연결 상태와 실제 시간 창에 영향을 받아 실패했다. 운영 제한값은 유지하고, 분당 120건 기본 제한을 직접 확인한 뒤 작은 실제 제한으로 HTTP 429/Retry-After를 검증하도록 테스트만 격리했다.
- 최초 실행에서는 OS 공유 메모리 자원 제한으로 전체 임시 네이티브 서비스 리허설 1건을 제외했으나, 후속 검증에서 자원 정리와 PostgreSQL 18 도구 선택을 보완해 해결했다. PostgreSQL 18.6의 전체 네이티브 런타임·롤백과 일일 통계 동시성 검증 2건이 모두 통과했다. 운영 DB 검증은 읽기 전용이며, 추가 권한·운영 재시작 없이 임시 DB를 정리했다. [보완 검증 보고서](../postgres18-isolated-verification-2026-10-26/REPORT.ko.md). Docker 이미지는 이 Mac 점검에서 빌드하지 않았다.

확인된 한계: 의존성 감사는 미공개 취약점 부재·침해사고 포렌식·외부 제공자/Cloudflare 관리 인프라 전체 감사를 대신하지 않는다. 전역 Conda/Homebrew 설치와 보관 중인 기존 롤백 릴리스는 이번 프로젝트 운영 프로필과 별개다. 업데이트된 기본 환경이 실행 중인 별도 릴리스 프로세스를 자동으로 바꾸지는 않는다.

## 운영 적용 완료

사용자가 네 서비스 반영 및 프록시에서 분리되고 요청 처리 0건인 이전 웹 프로세스 정리를 명시적으로 승인했다.

승인 시점에는 프론트엔드가 `frontend-guidance-design-20261026-r1`로 추가 갱신되어 있었다. 해당 릴리스의 보안 환경이 r2와 정확히 같음을 확인했고, 최신 화면·소스를 포함한 공통 `dependency-security-20261026-r3`를 만들었다. 현재 프론트엔드와 r3의 전체 동결 파일 해시도 차이가 없었다. 화면을 이전 버전으로 되돌리거나 동일 환경을 불필요하게 재기동하지 않고 프론트엔드를 유지했다.

- frontend: 기존 최신 릴리스 유지, 슬롯 b, Python 3.11.18/OpenSSL 3.5.9/native Psycopg C 보안 구성 확인.
- admin: `dependency-security-20261026-r3`, 슬롯 b 전환 완료.
- execution: `dependency-security-20261026-r3` 교체 완료, 작업 하트비트 정상.
- jobs: `dependency-security-20261026-r3` 교체 완료, 일시정지 상태 아님. 수집·A2A/MCP/x402 헬스·기능 조사·에이전트 해석·벡터 인덱스 등 8개 작업 스레드가 살아 있다. 벡터 작업은 running이며 SQLite 확장 부재 때문에 비활성화되지 않았다.
- 실제 Caddy 설정을 조회해 이전 웹 슬롯이 프록시 대상에서 분리됐고 처리 요청이 두 차례 모두 0건인 것을 확인한 뒤 이전 프로세스 2개를 종료했다. 롤백 릴리스 파일은 보존했다. Caddy 프로세스는 유지됐다.

증적: `rollout-plan.json`, `operating-rollout-final.json`, `old-web-process-cleanup.json`, `operating-jobs-health.json`.

실제 공개 홈·워크스페이스 진입/로그인·탐색 검색·워크플로우 템플릿과 로컬 어드민을 HTTP로 확인해 12개 기대 상태가 모두 통과했다. 비인증 워크스페이스는 로그인으로 이동하며, 어드민 API는 인증 없이 접근할 수 없다. 런타임 내역·도구 체인 설정·잠금 파일·내부 준비 상태·어드민 페이지는 공개 주소에서 404다. `operating-http-checks.json`에 기록했다.

새 격리 Chromium으로 실제 홈·워크스페이스 로그인·어드민 로그인 화면을 확인했고 스크립트 오류는 0건이었다. Google/GitHub 로그인 선택이 표시되는 것을 확인했으며 실제 OAuth 인증정보는 입력하지 않았다. `operating-browser-checks.json`, `operating-home.png`, `operating-workspace-sign-in.png`, `operating-admin-sign-in.png`가 증적이다.

새 jobs 로그 범위에서 ModuleNotFoundError·ImportError·네이티브 라이브러리 로딩 오류·Traceback·TLS 인증서 검증 오류가 발견되지 않았다: `jobs-startup-log-check.json`. 운영 반영 후 전체 상태는 stable이며 모든 활성 서비스의 개별 런타임 내역에서 네이티브 libpq 18.6/OpenSSL 3.5.9 및 CA 번들 일치를 다시 확인했다.

의존성 변경의 608개 회귀 증적은 위에 명시한 범위다. 이후 최신 화면 소스 보존에 대해서는 현재 운영 프론트엔드와 최종 패키지의 해시 일치 및 추가 실제 화면/HTTP 검증을 수행했다. 실제 Google/GitHub 신규 OAuth 인증, 유료 외부 제공자 실행, Docker 이미지 실행은 이번 운영 확인 범위에 포함하지 않았다.

이후 관리 명령과 프로필별 설치 방법은 `deploy/DEPENDENCY_MAINTENANCE.md`를 참고한다.

최종 패키지 자체를 별도 격리 앱으로 실행해 생산 프로필·네이티브 링크를 확인했다. 홈과 명명된 홈은 200이며, 비공개 런타임 내역·도구 체인 설정·잠금 파일의 공개 URL은 모두 404였다: `immutable-release-smoke.json`. 임시·구버전 기본 환경 백업은 검증 후 삭제했으며 운영 롤백 릴리스는 보존했다: `environment-cleanup.json`.
