# Mac mini LLM 전환 준비 결과

2026-10-23, 사용자 확인 주소 `192.168.0.25`의 단일 vllm-mlx 서버로 생성 모델 연결을 변경했다. 처음 전달된 `192.128.0.25`는 연결 시간 초과였고 사용자가 `192.168.0.25`로 정정했다.

## 설정과 구현

- 엔드포인트: `http://192.168.0.25:8000/v1`.
- 서빙 모델: `gemma4-e4b-mlx`.
- 모든 OpenAI 호환 생성 요청에 `chat_template_kwargs: {enable_thinking: false}` 적용.
- 워크플로우 제안, 지원 문서 기반 안내, 어드민 플래너, RAG 텍스트 생성, 컨시어지 생성 어댑터를 연결했다. 기존 모델 호출 동의·공개 목적만 전송·출력 검증·별도 저장/실행 권한은 유지했다.
- 모델 추가 실행, 여러 복사본 생성, 원격 모델 서버 재시작은 수행하지 않았다. 서버의 단일 인스턴스/16슬롯 설정을 변경하지 않았다. 이번 연결 검사에서는 16동시 부하를 재측정하지 않았다.
- 로컬 Ollama로 자동 복귀하지 않는다. 리다이렉트·환경 프록시를 사용하지 않고, 잘못된 모델·미완료 응답·도구 실행·추론 채널을 거부한다. JSON 스키마를 지원하는 요청은 기존 선언 스키마를 전달한다.

운영 설정은 소유자 전용 0600의 `gateway-data/local-model.env`에 저장했다. 새 서비스 배포본은 이 파일을 기존 `agentcon.env` 다음에 읽는다. 허용된 모델 설정만 덮어쓸 수 있다. 이전 배포본의 설정 파서가 새 키를 몰라 재기동에 실패하지 않도록 기존 기본 설정 파일은 보존했다. 예시는 `deploy/local-model.env.example`이다.

## 로컬 Ollama 중지

사용자 요청에 따라 `LOCAL_OLLAMA_ENABLED=0`으로 구성했다. 새 배포본에서는 로컬 임베딩 HTTP 호출과 자동 벡터 갱신도 중지한다. 기존 벡터 데이터는 삭제하거나 다른 임베딩으로 덮어쓰지 않는다. 키워드 검색은 계속 제공한다.

맥미니의 Gemma 생성 모델을 기존 임베딩 모델로 간주하지 않는다. 별도 호환 임베딩 제공자를 마련하기 전까지 신규 벡터 생성과 질의 벡터 기반 검색은 중지된다. Ollama OS 프로세스 자체를 종료한 것은 아니다.

현재 실행 중인 이전 배포본은 아직 이 설정을 읽지 않는다. **운영 적용 전까지 기존 jobs의 Ollama 호출이 중지됐다고 볼 수 없다.** 최초 적용 시 frontend/admin과 자동 임베딩을 소유한 jobs의 교체가 필요하다. execution worker는 생성 모델을 호출하지 않으므로 이번 교체 대상에서 제외한다.

## 검증

맥미니 실제 응답:
- `/health`: healthy, model_loaded=true, engine_type=batched.
- `/v1/models`: `gemma4-e4b-mlx` 확인.
- 일반 생성: HTTP 200, `OK`, 약 262ms.
- JSON 스키마 생성: HTTP 200, `{"status":"OK"}`, 약 1952ms.
- 실제 워크플로우 제안 어댑터: 두 단계 생성과 앞 단계 결과 연결 확인, 약 2965ms. 합성 공개 계약만 사용했고 에이전트 실행과 DB 저장은 0건이다.

회귀 195개와 모델 동의/검토/저장 경계를 확인하는 브라우저 검사 1개가 통과했다. 공개 콘텐츠 검사 248파일 위반 0개, 런타임 프로필 읽기 전용 검사도 통과했다. 최초 회귀에서 새 HTTP 정책이 기존 테스트 엔진을 과하게 제한한 부분을 발견해 기존 Ollama 동작을 보존하도록 고쳤다. 격리 PostgreSQL fixture는 샌드박스 밖의 임시 클러스터 권한으로 다시 실행해 통과했다.

증적은 `live-inference.json`, `live-workflow-proposal.json`에 보존했다. 실제 고객 목적·초안·인증 정보는 맥미니 연결 시험에 사용하지 않았다.

## 배포 준비 상태

고정 배포본 `macmini-llm-20261023-r1`을 준비했다(소스 manifest 1137개 파일). 운영 교체는 아직 실행하지 않았으며 명시적인 실행 지시를 요청했다.

```bash
./agentcon deploy frontend macmini-llm-20261023-r1
./agentcon deploy admin macmini-llm-20261023-r1
./agentcon worker-deploy jobs macmini-llm-20261023-r1
./agentcon status
```

웹은 A/B로 순차 전환한다. jobs는 기존 작업을 정리한 후 해당 역할만 교체하므로 신규 자동 작업 처리가 잠시 멈출 수 있다. 실행 worker와 공개 프록시는 교체하지 않는다. 옛 배포본으로 rollback하면 예전 Ollama 설정으로 돌아갈 수 있으므로 복귀 시 모델 정책도 확인한다.

참고: [vllm-mlx 공식 서버 안내](https://github.com/waybarrios/vllm-mlx/blob/main/docs/guides/server.md)의 OpenAI 호환 채팅·구조화 출력·chat template 설정을 확인하고 실제 서버 응답으로 검증했다.

## 사용자 웹 반영 후 확인

사용자가 frontend `web-20261023-134313-c3a5`, admin `web-20261023-134343-9e17`로 교체했다. 두 배포본에서 새 비공개 모델 프로필 로더·OpenAI 호출 코드·임베딩 중지 기능을 확인했다. 공개 홈페이지와 어드민 화면이 HTTP 200, 맥미니는 healthy로 응답했다. 증적은 `production-web-verification.json`이다.

jobs는 여전히 `services-20261022-r1`이므로 다음 명령이 남아 있다. 준비된 배포본 manifest를 다시 검증했다. 이 상태에서 jobs의 Ollama 호출까지 중지됐다고 보고하지 않는다.

```bash
agentcon worker-deploy jobs macmini-llm-20261023-r1
agentcon status
```

## jobs 반영 완료

사용자가 `agentcon worker-deploy jobs macmini-llm-20261023-r1`을 실행했고, jobs PID 96661의 새 배포본과 정상 heartbeat를 확인했다. 수집 스레드 8개가 살아 있으며 전체 수집은 일시 정지 상태가 아니다. 웹·execution·프록시 PID는 유지됐다. 공개 홈·어드민·맥미니 health 모두 HTTP 200이다.

배포된 프로필은 `LOCAL_OLLAMA_ENABLED=0`이다. jobs의 로컬 11434 포트 연결은 확인 시점에 없었고, 배포 전 격리 회귀에서 임베딩·벡터 적재 경로가 네트워크와 DB 인덱스에 접근하지 않는 것을 확인했다. 현재 자동 임베딩은 비활성이고 일반 수집·헬스는 계속 운영된다. 증적은 `production-jobs-verification.json`이다.

표시된 `/dev/null` 경고는 상속된 PostgreSQL 비밀번호 파일을 사용하지 않도록 지정한 `passfile=os.devnull`에 대한 libpq의 파일 종류 경고다. 실제 DB 접속과 작업 heartbeat는 성공했다. 이번 모델 전환 실패를 의미하지 않는다. 경고를 없애기 위해 기존 DB 인증/신뢰 설정을 임의로 변경하지 않았다.

세 역할의 운영 반영과 최종 확인을 완료했으며 추가 재기동은 필요 없다. 기존 벡터는 보존되고, 별도 임베딩 제공자를 마련하기 전까지 벡터 기반 검색·신규 벡터 생성은 비활성 상태다.
