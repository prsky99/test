# 범용 입출력 변환 기반 폴백 개발·검증

2026-10-24 · 범위: 기존 R-06 읽기 전용 MCP 폴백의 스키마 호환성 확장

**에이전트별 하드코딩 대신 재사용 가능한 입력·출력 변환 노드와 검증 프로필을 구현했다. 운영 폴백 스위치는 활성화하지 않았다.** 새 소스 배포와 독립된 실제 주·대체 제공자에 대한 검증은 별도다.

## 조사와 설계 결정

- [Synthesizing JSON Schema Transformers](https://arxiv.org/abs/2405.17681): 스키마 사이의 제한된 재작성 규칙을 이용하는 방향을 참고해, 실행 가능한 코드 문자열 대신 제한된 연산 트리를 사용했다.
- [AI-assisted JSON Schema Creation and Mapping](https://arxiv.org/abs/2508.05192): 매핑 제안과 결정론적 실행을 분리하는 방향을 참고했다. 이번 구현은 관리자가 작성한 규칙의 검증·실행이며 AI의 자동 승인 기능은 없다.
- [Gorilla](https://arxiv.org/abs/2305.15334): 현재 도구 명세와 연결 버전을 고정해야 하는 근거로 참고했다.
- [n8n 공식 구조화 출력 문서](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.outputparserstructured), [공식 운영 가이드](https://blog.n8n.io/production-ai-playbook-deterministic-steps-ai-steps/)에서 스키마 검증과 결정론적 처리의 분리를 확인했다.
- [Reddit의 구조화 파서 실패 경험](https://www.reddit.com/r/n8n/comments/1i8jq8g/tool_agent_error_with_structured_output_parser/)도 검색·열람했다. SNS 경험담을 성능 통계나 자동 재시도 허가로 사용하지 않았다. 출처 불명 코드와 임의 LLM 복구 실행은 도입하지 않았다.

변환은 구조와 형식을 연결한다. 기능이 다른 에이전트를 같은 기능으로 만들거나, 같은 서버·상위 API·계정/한도를 공유하는 에이전트를 독립적으로 바꾸지 않는다. 형식 검증은 사실 정확성과 의미적 동등성을 인증하지 않는다.

## 구현

`workflow_transforms.py`는 필드 이동·이름 변경, 중첩 객체·배열 매핑, 누락/null 대안, 조건 분기, 엄격한 자료형 변환, 문자열 처리, 목록 제한, 원래 시각의 UTC 정규화, 엄격한 JSON 문자열 해석을 지원한다. 코드·파일·네트워크·모델 실행과 현재 시각 생성은 없다. 크기·깊이·배열·연산 수를 제한하고 프로토타입 관련 예약 키·중복 JSON 키·비유한 수·손실성 정수 변환을 거부한다.

공유 워크플로 실행기에 `input_transform`과 `output_transform`을 추가했다. 일반 업스트림 참조를 받아 로컬에서 변환하고 다음 단계로 전달한다. 이 노드는 외부 시도 횟수 0으로 기록되며 품질·실행 증거를 발급하지 않는다. 기존 private canvas에서 노드 추가와 규칙 편집을 제공한다.

`workflow_io_profiles.py`는 서로 다른 네이티브 입출력 스키마를 공통 계약과 연결한다. 현재 도구의 명시적 계약 승인, 정확한 원본·목표 스키마, 읽기 전용 어노테이션을 확인한 뒤 공개 입력 1~3건으로 **실제 프록시 호출**이 모두 성공해야 서명된 프로필을 저장한다. 운영 검증은 합성 성공 플래그나 사용자가 제출한 결과를 신뢰하지 않는다. 테스트의 제공자·전송 경로는 격리된 통제 대상임을 별도로 구분한다.

프로필은 자원·연결 버전·도구·계약 승인 시각·규칙·변환/검증 구현 해시와 실제 검사 산출물 해시를 묶고 24시간 후 만료된다. 일반 실행 노드에는 `data.io_profile`, 대체 정책에는 `alternate_io_profile`을 지정할 수 있다. 주·대체 도구의 이름과 스키마가 달라도 변환 후 동일 계약을 만족해야 한다. 실행 직전 철회·변조·스키마/승인/구현 변경을 재검증한다. 백업 복원은 프로필을 철회한다.

제공자의 성공 상태·요청 일치 조건을 설정할 수 있다. URL·조회 시각의 리터럴 위조와 리터럴 JSON 문자열을 통한 출처 위조도 차단한다. 네트워크 결과가 불확실한 전송 후 타임아웃은 변환 기능이 있어도 재전송하지 않는다. 기존 단일 대체·동의·Kill Switch·장애 의존성 차단을 유지했다.

## 관리자 사용 위치

- 리뉴얼 화면 **서비스 설정(T05) → 입출력 변환 검토**: 현재 스키마 조회, 입력/출력 미리보기, 실제 전달 동의, 실제 검증·프로필 저장, 철회.
- 기존 private workflow canvas: 입력/출력 변환 노드 추가, 변환식과 업스트림 입력 편집, 에이전트의 검증된 프로필 ID 지정.
- 기존 폴백 정책 편집: 대체 에이전트의 검증된 입출력 프로필 ID 지정.

미리보기는 외부 호출 0회이며 실행 권한을 만들지 않는다. 실제 검증 동의는 기본 미선택이다. 로그아웃·화면 이동 시 비공개 팝업을 닫으며 브라우저 저장소에 규칙/입력 내용을 보관하지 않는다. 현재 코드 배포 후 사용할 수 있다. 별도의 직원/고객 typed workspace 편집기와 게시 권한 형식은 이번 변경으로 자동 확장하지 않았다.

활성화 준비 상태도 추가했다. 현재 유효한 Shadow와 Canary 정책이 없거나 계약·증거·정의·프로필이 바뀌면 전역 활성화를 거부하고 사유를 표시한다. 비활성화는 제공자가 고장 나거나 프로필이 만료돼도 가능하다. 스위치만 켜고 실제 대체 실행이 가능한 것처럼 표시하지 않는다.

## 검증 결과와 실제 범위

고유 검증 범위는 [수집 목록](transform-collected.txt)의 **296건**이다. 중복 재실행을 합산하지 않은 확인 결과 **295건 통과**, **1건은 환경 제약으로 미완료**다. 한 번에 295건을 모두 실행한 것으로 표시하지 않는다.

- 넓은 실행·권한·체크포인트·복원·폴백 묶음: [271건 통과·PG 환경 실패 1건](transform-final-backend.txt).
- 신규 변환·보안 경계 최종 묶음: [95건 통과](transform-security-final.txt). 변환/검증 구현 해시의 하위 경로 처리 오류를 추가 발견·수정한 뒤 [프로필 24건 재검증 통과](transform-profile-fixed.txt).
- 관리자·기존 폴백 브라우저/API 묶음의 18건 통과 후 신규 화면 2건을 수정·재확인했다. 실제 서비스 설정 경로(T05), fixture 등록, 기존 테스트의 폐기된 홈 제목 기대값을 바로잡았다. [신규 화면 2건의 통과와 요청 제한 기대값 보정 전 결과](transform-targeted-final.txt), [실제 JSON 헤더·유효 대용량 JSON으로 요청 제한 재확인 통과](transform-request-limits-final2.txt).
- 정수 경계 `2**53+1` 및 소수점 정수 변환의 정밀도 손실도 수정했다. 숫자를 먼저 float로 바꿔 반올림한 뒤 승인하지 않는다.
- [신규 코드 정적 검사](transform-new-lint.txt) 통과, 신규 관리자 모듈 JS 구문 검사 통과. 공유 runtime의 기존 미사용 예외 변수 경고 5개는 이 기능과 무관해 별도 보존했다.
- [공개 콘텐츠](transform-public-content.txt) 249개 파일 위반 0건. 공개 HTML/메타데이터 문구는 변경하지 않았다.

실제 TCP 검증은 주 서버 리스너를 종료한 뒤 네이티브 필드가 다른 대체 서버를 호출했다. 정규 입력 `query/language/limit`가 `term/count`로 변환되고, 네이티브 `records`가 공통 `items`로 변환돼 계약 검증을 통과했다. 주 서버 종료 후 비즈니스 호출은 0회, 대체 호출은 1회이며 성공 결과와 `fallback_used=true`를 확인했다. [TCP 증빙](transformed-tcp.json). 같은 시스템의 격리 서버·테스트 데이터이며 외부 제공자나 물리 장애 독립성의 합격 증빙은 아니다.

## PostgreSQL 18 및 운영 변경

신규 SQL 카탈로그는 **3,704문장·230테이블**로 동기화했다. PostgreSQL 18.6의 세션 전용 TEMP 테이블에서 컴파일된 신규 DDL·INSERT/조회·서명 본문 왕복·철회·목록·자동 제거를 확인했다. [증빙](transform-postgres18-temp.json). 영구 애플리케이션 행은 수정하지 않았다.

독립 PostgreSQL 18 클러스터 초기화는 OS 공유 메모리 ID/용량 한도로 실패했다. initdb의 `No space left on device`는 이 경우 디스크 용량 부족 판정이 아니다. 같은 환경으로 기존 PostgreSQL 14 전체 이전 리허설 1건도 완료하지 못했다. 다른 프로세스·공유 메모리 세그먼트·커널 설정을 임의로 정리하지 않았다. TEMP 테이블 검증을 전체 독립 클러스터/DR 리허설과 동일하다고 주장하지 않는다. [초기 실패](transform-postgres18.txt).

운영에는 검토된 빈 `workflow_io_profiles` 테이블 1개만 원자적으로 추가했다. 기존 행 수정 0건, 기존 승인·스케줄·크레딧·폴백 설정 변경 0건이다. [추가 결과](transform-operating-migration.txt). 실제 PostgreSQL Store로 230개 테이블 스키마 연결 검증도 통과했으며 당시 frontend/admin readiness는 정상이었다. [연결 확인](transform-operating-predeploy.json).

**운영 프로필 0개·정책 0개·폴백 disabled**다. 새 코드의 배포 여부와 현재 역할별 소스 비교는 [최종 상태](transform-final-source-state.json)에 기록한다. 서버를 재시작하거나 배포하지 않았다.

## 배포 후 실제 활성화 조건

사용자 터미널에서 동일 소스를 세 역할에 반영한다. jobs는 이번 대상이 아니다.

```bash
agentcon package generic-io-fallback-20261024-v1
agentcon deploy frontend generic-io-fallback-20261024-v1
agentcon deploy admin generic-io-fallback-20261024-v1
agentcon worker-deploy execution generic-io-fallback-20261024-v1
```

그 뒤 독립된 실제 제공자 조합을 정하고, 현재 네이티브 계약 승인과 변환 실검증 → Shadow → 제한 Canary → 전역 활성화를 진행해야 한다. 공통 Crossref 조합과 동일 주소/호스트 후보는 변환이 가능해도 계속 제외한다. 조사한 `search_arxiv`는 네이티브 스키마의 미지원 pattern 때문에 아직 호출 적격이 아니며, 변환 노드를 이유로 이 검사를 생략하지 않았다. [실제 사전 확인](activation-arxiv-native.json).

상세 규격과 API: [WORKFLOW_IO_TRANSFORMS.md](<저장소>/docs/WORKFLOW_IO_TRANSFORMS.md).

## 사용자 재시작 후 반영 확인

frontend와 execution은 `generic-io-fallback-20261024-v1`, admin은 `web-20261024-175438-589d`다. 이름은 다르지만 세 역할 모두 검증한 런타임·검증기·관리자 자산·SQL 카탈로그 **13/13개 파일 SHA-256이 일치**한다. 현재 작업 소스도 고정 기준과 일치한다. frontend/admin 서명 readiness와 execution heartbeat는 정상이다. 새 관리자 모듈은 200/no-store이며 제공 바이트가 검증 소스와 일치한다. 프로필 API는 비인증 403, 기계 토큰 401로 거부한다.

운영 프로필 0개·정책 0개·전역 disabled/revision 0을 읽기 확인했다. 이번 확인에서 운영 변경은 없으며, 코드 반영을 위한 추가 배포·재시작은 필요 없다. 위의 배포 명령은 반영 완료된 이력이다. 실제 운영 활성화는 독립된 동일 기능 제공자와 현재 네이티브/변환 검증·Shadow·Canary 확보 후 진행해야 한다. 현재 승인된 두 연구 연결은 Crossref를 공유하므로 그대로 대체 쌍으로 설정하지 않았다.

컴퓨터유즈 상태 조회가 2회 시간 초과돼 로그인된 운영 UI 조작·변환 미리보기는 이번 확인에 포함하지 못했다. 이를 서비스 오류로 판정하지 않으며 앞선 격리 Chromium 검증과 구분한다. 기존 295건을 다시 실행한 것으로 합산하지 않는다. 근거: [재시작 후 점검](generic-io-post-restart.json).
