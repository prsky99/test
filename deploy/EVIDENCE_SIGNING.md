# 증거 서명 설계 (운영·SRE, 2026-11-14 초안, 11-17 확정 예정)

- 근거: 초격차 전략(`reports/super-gap-strategy-2026-11-14/README.md`, 보완 3), PM 11-14 배정
- 우리는 등급이 아니라 **증거 자체**에 서명한다. 대상은 시험 판, 목걸이 관문 결과, 정지·교체 사건이다.
- 누구나 공개 키 문서로 검증할 수 있다.
- 코드
  - `agent_market/evidence_signing.py`: 서명·검증 라이브러리(2e8d0118, 시험 `tests/test_evidence_signing.py`)
  - `scripts/signing_keygen.py`: 키 생성

## 1. 형식
| 항목 | 정한 것 |
|---|---|
| 정규화 | RFC 8785 JCS. 키는 UTF-16 코드 단위 순, 최소 이스케이프, 숫자는 ECMAScript 표기다. 2^53을 넘는 정수와 NaN·무한대는 거부한다(조용히 반올림하지 않음) |
| 봉투 | DSSE v1. `{payloadType, payload(JCS 바이트의 base64), signatures:[{keyid, sig}]}`. 서명 대상은 PAE `"DSSEv1 <len> <type> <len> <payload>"`다 |
| payloadType | `application/vnd.agentvalcon.evidence+json` |
| 알고리즘 | Ed25519 |
| keyid | `avc-ed25519-` + sha256(공개 키 원본 32바이트) 앞 16자리(16진) |
| 서명 시각 | 내용 안의 `signed_at`(UTC, `YYYY-MM-DDTHH:MM:SSZ`). 서명 대상에 들어간다 |

**증거 내용(필수 칸)**
| 종류 `kind` | 칸 |
|---|---|
| `test_report` (검색과 RAG) | `resource_id`, `role`(계약 id), `tool`, `endpoint`(호스트·주소), `tool_fingerprint`(도구 정의 지문: 이 판이 어떤 정의에서 나왔는지 묶음), `report_version`, `input`(공개 가능한 과제 입력), `response_sha256`, `outcome`, `score_items`(항목별 점수), `total_score`, `status`(provisional·verified·none), `data_quality`(최신성 나이·빈 칸 비율·깨끗함 결과), `accuracy_source`(정답 세트 이름·해시 또는 공개 기준값과 그 시각), `data_as_of`, `methodology_version`, `tested_at`, `prev` |
| `gate_result` (워크플로우·운영·SRE) | `slug`, `version`, `definition_digest`, `members`(자리별 주 진주·외부 대체·자체 대체 id와 각자의 도구 지문), `answer_set`(이름·해시), `rounds`(회차별 성공 수와 **시각**: 4시간 간격 증명), `delta_pp`, `completion`, `p95_ms`, `security`, `verdict`, `methodology_version`, `gate_record`(판정 파일 경로·해시), `prev` |
| `necklace_event` (워크플로우) | `slug`, `stage`(1~4), `event`(held·retired·replaced·restored), `reason`, `replaced_by`, `notices`(공지가 나간 위치 주소 목록: 4단계 공지 증명), `at`, `evidence`(근거 판정 해시), `prev` |
| `transparency_root` (운영·SRE) | `day`, `count`, `root`(Merkle), `leaves`(그날 봉투 digest 전부), `prev`(전날 루트 봉투 digest) |

- 비공개 보류 정답 세트의 내용은 넣지 않는다. 이름과 해시만 넣는다.
- 원문 응답은 sha256만 넣는다. 응답 원문은 시험 보고서 페이지가 따로 보여 준다.

## 1-1. 기록을 고칠 수 없게 하기 (PM 11-14, 비용 0)
- **해시 사슬**
  - 같은 사슬의 봉투마다 `prev` = 앞 봉투의 digest를 서명 내용에 넣는다(`sign_chained`). digest는 봉투 전체를 JCS로 정규화한 sha256이다.
  - 사슬 단위는 판이면 (resource_id, role), 관문이면 slug, 사건이면 slug다.
  - 실패한 판을 몰래 빼거나 순서를 바꾸면 `verify_chain`이 끊긴 위치를 알려 준다. 첫 봉투의 `prev`는 null이다.
- **하루 투명성 기록**
  - 운영·SRE가 매일 00:10 KST에 전날의 모든 봉투 digest를 정렬한다.
  - 그 Merkle 루트(RFC 6962 방식: 잎 0x00, 마디 0x01)를 `transparency_root` 봉투로 서명한다(`daily_root`).
  - 날마다 앞날 루트를 `prev`로 이어 날짜끼리도 사슬이 된다.
  - 공개 주소는 `/signing/roots/<YYYY-MM-DD>.json`이다. 누구나 `verify_daily_root`로 그날 봉투 전부가 들어 있는지 확인할 수 있다. 빠진 봉투가 있으면 맞지 않는다.
- 이것으로 "좋은 결과만 골라 보여 준다"는 의심을 원천에서 막는다. 판·관문·사건을 지우거나 고치려면 사슬과 그날 루트를 함께 바꿔야 하는데, 루트는 이미 서명돼 공개된 뒤다.

## 2. 공개 키 문서 `/.well-known/agentvalcon-keys.json`
```json
{"keys": [{"keyid": "avc-ed25519-…", "alg": "ed25519", "public_key": "<base64 32 bytes>",
           "not_before": "2026-11-17T00:00:00Z", "not_after": "2027-11-17T00:00:00Z"}],
 "revoked": [{"keyid": "avc-ed25519-…", "revoked_at": "…Z", "reason": "suspected exposure"}]}
```
- 검증 규칙: 서명의 keyid가 목록에 있고, `signed_at`이 그 키의 유효 기간 안이고, 그 키가 `signed_at` 전에 폐기되지 않았으면 유효하다.
  - 키를 바꿔도 옛 키를 목록에 남겨 옛 서명을 계속 검증할 수 있다.
- 원본 파일은 `gateway-data/signing/agentvalcon-keys.json`이다(공개해도 되는 내용).
- frontend가 읽어 위 주소로 그대로 준다. 캐시는 `public, max-age=300`이다. 배포는 frontend가 맡는다(11-20 서명 적용 묶음).

## 3. 개인 키 (운영·SRE)
- **만들기(11-17)**: `.venv/bin/python -m scripts.signing_keygen --days 365`
  - `gateway-data/signing/<keyid>.pem`(PKCS#8, 권한 600, 폴더 700, git 제외)을 새로 만든다. 이미 있는 파일은 덮어쓰지 않는다.
  - 공개 키 문서에 한 줄을 더한다. 출력에는 공개 부분만 나온다.
  - 이 맥에서 키 만들기가 권한 검사에 막히면 우회하지 않고, 같은 명령을 사용자 실행용으로 PM에 보낸다.
- **값을 쓰지 않는 곳**: 코드, 로그, 보고서, 현황판, 세션 메시지, git. 서명하는 코드는 파일을 읽어 메모리에서만 쓴다(`load_private_key`가 소유자·권한 600/400을 검사).
- **백업**
  - 맥미니 SMB 백업에 **암호화 사본**만 둔다(PKCS#8 암호화 PEM, 암호 문구는 사용자 키체인).
  - 암호 문구는 Claude가 다루지 않는다. 사용자가 다음 명령을 실행한다.

```bash
cd /Users/kingstonelee/workspace/A2A_Discovery
.venv/bin/python -c "import sys,getpass;from cryptography.hazmat.primitives import serialization as s;k=s.load_pem_private_key(open(sys.argv[1],'rb').read(),None);open(sys.argv[2],'wb').write(k.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.BestAvailableEncryption(getpass.getpass('암호 문구: ').encode())))" gateway-data/signing/<keyid>.pem /Volumes/<맥미니 공유>/agentvalcon-signing/<keyid>.enc.pem
```

- **교체(1년마다, 또는 필요할 때)**
  1. 새 키를 만든다(공개 키 문서에 추가).
  2. 서명 코드가 새 keyid를 쓰게 한다.
  3. 옛 키는 `not_after`까지 목록에 남긴다(옛 서명 검증용).
  4. 옛 개인 키 파일은 백업 확인 뒤 지운다(사용자 승인, 데이터 삭제).
- **폐기(유출이 의심될 때)**
  1. 즉시 공개 키 문서 `revoked`에 `{keyid, revoked_at=지금, reason}`을 더해 배포한다.
  2. 새 키를 만든다.
  3. 폐기 시각 뒤에 그 키로 만든 서명은 무효다. 폐기 전 서명은 새 키로 다시 서명한다(판·관문·사건 원본이 남아 있으므로).
  4. 현황판에 사건을 적고 PM에 바로 보고한다.
- 이 키는 증거 서명 전용이다. 돈·지갑·USDC 수취와는 관계가 없다.

## 4. 공개 검증
- **명령 예제**(저장소 공개 코드):
  `python -m agent_market.evidence_signing verify envelope.json --keys agentvalcon-keys.json` → `{"valid": true, "evidence": {...}}`
- **`POST /api/verify-signature`**(frontend, 11-20)
  - 요청: `{"envelope": <DSSE 봉투>}`, 본문 64KB 이하
  - 응답 200: `{"valid": true|false, "reason": "…"(무효일 때), "keyid": "…", "kind": "…", "signed_at": "…", "evidence": {…}(유효할 때)}`
  - 서버의 공개 키 문서로 검증한다. 요청은 읽기만 하고 저장하지 않는다. 쿠키·인증이 필요 없다.
  - IP당 분당 30회 제한(기존 `security.allow_read`)을 둔다.
  - 400은 형식 오류(DSSE 아님, base64 오류, 크기 초과)일 때다. 서명이 틀린 것은 200 `valid: false`다.
- 검증은 다른 언어로도 할 수 있다. 서명 대상이 DSSE·JCS·Ed25519라는 공개 표준이기 때문이다. 방법론 페이지(성장·유통)에 위 형식과 예제를 싣는다.

## 5. 적용 일정
| 날짜 | 일 | 담당 |
|---|---|---|
| 11-17 | 이 설계 확정, 키 생성, 공개 키 문서 원본 | 운영·SRE |
| 11-18~19 | 판 서명(시험 보고서 v2 판마다 봉투 저장), 관문 결과·사건 서명 | 검색과 RAG, 워크플로우(라이브러리 사용), 운영·SRE(관문 판정 파일 서명) |
| 11-20 | `/.well-known/agentvalcon-keys.json`, `/api/verify-signature`, 배지 | 성장·유통(화면), 운영·SRE(사양·시험) |
| 11-21 | 첫 목걸이 공개: 관문 결과 봉투와 함께 | 전체 |

- 서명 대기(PM 동의): 11-21 전에는 서명 없는 판·결과를 "서명 대기"로 표시하고 공개를 막지 않는다. **11-21부터는 검증 진주와 목걸이 공개 조건에 서명을 넣는다.**
- 경보: 서명 실패(키 읽기 실패, 서명 오류, 그날 루트 미생성)가 **1시간 넘게** 이어지면 오류 감시(ops_auto watch)가 현황판에 경보를 올린다. 서명 코드는 실패를 `logs/ops/signing-failures.jsonl`에 남긴다.
- **봉투 저장과 공개 경로**(1단계 파일, 표는 2단계 DB 변경 절차)

| 무엇 | 저장(원본) | 공개 주소(frontend가 그대로 읽음) |
|---|---|---|
| 판 봉투 | `gateway-data/signing/envelopes/test_report/<resource_id>/<role>/<report_version>.json` | `/signing/envelopes/test_report/<resource_id>/<role>/<report_version>.json` |
| 관문 결과 | `gateway-data/signing/envelopes/gate_result/<slug>/<version>-<n>.json` | `/signing/envelopes/gate_result/<slug>/<version>-<n>.json` |
| 사건 | `gateway-data/signing/envelopes/necklace_event/<slug>/<at>.json` | `/signing/envelopes/necklace_event/<slug>/<at>.json` |
| 하루 루트 | `gateway-data/signing/roots/<day>.json` | `/signing/roots/<day>.json` |
| 사슬 목록 | `gateway-data/signing/chains/<kind>/<chain>.json`(봉투 digest 순서) | `/signing/chains/...` |
| 공개 키 | `gateway-data/signing/agentvalcon-keys.json` | `/.well-known/agentvalcon-keys.json` |

- 공개 주소는 읽기 전용 정적 응답이다(`public, max-age=300`, 하루 루트는 `max-age=86400`).
- 파일 이름의 각 부분은 숫자·소문자·하이픈·점만 허용하고, 경로를 벗어나는 이름은 거부한다.
- 개인 키 파일(`*.pem`)은 이 경로들 밖에 있어 공개 경로로 닿지 않는다.
