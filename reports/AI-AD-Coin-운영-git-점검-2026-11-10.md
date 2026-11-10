# AI AD Coin "운영 = git" 1단계 점검 (2026-11-10 18시대)

- **요청:** 총괄 PM(사용자 결정 17:5x, 새 기능 중지·바탕부터)
- **범위:** `agent_market/ad_coin/**`와 `scripts/ad_coin_*`(git 추적 97개)
- **방법:** 역할별 활성 버전의 파일을 `git show HEAD:<경로>`와 바이트 단위로 비교했다. 미커밋 변경은 `git status`로 봤다. 시험 전용 경로는 운영 코드를 grep으로 찾았다. 운영 DB와 원장에는 아무것도 쓰지 않았다.

## 1. 운영 활성 버전과 HEAD의 차이

| 역할 | 활성 버전 | HEAD와 다른 파일 | 버전에 없는 파일 | 판단 |
|---|---|---|---|---|
| frontend | `usage-frontend-20261110-r1`(base crawler-verify-frontend-20261110-r1) | `ad_coin/v2/live_service.py`, `scripts/ad_coin_sql_registry.py` | 운영 도구 스크립트 5개(reconcile, rehearsal, v2_migrate, v2 perf 2개) | live_service.py의 차이는 **배포 대기 중인 보안 수정 d60b8d18**이다(아래 3절 ①). sql_registry.py는 개발 도구이고 실행 경로가 아니다. 나머지 v2 파일은 HEAD와 같다 |
| admin | `config-admin-20261110-r1` | v1 `api.py`, `config.py`, `receipts.py`, `service.py`, `sql_registry.json`, `scripts/ad_coin_sql_registry.py` | v2 전체(72개) | admin은 v2를 싣지 않는다. v1 파일은 v1 보안 수정(e346295d) 전 판이다. 다만 v1은 `AD_COIN_ENABLED`가 꺼져 있어 라우트가 없다 |
| jobs | `due-pick-jobs-20261110-r1` | 없음 | AD Coin 전체(97개) | jobs는 AD Coin을 싣지 않는다(분리 규칙대로) |
| execution | `rebuild-execution-20261110-r1` | v2 파일 12개(옛 판) | v2 새 파일 6개와 스크립트 | execution은 AD Coin을 import하지 않는다(customer_credits.py는 주석과 문자열만). 옛 사본이 실려 있을 뿐이다 |
| AD Coin 작업자 데몬(launchd `biz.agentconcierge.498590e0b3.adcoin-worker`) | `site-signin-frontend-20261110-r1` 폴더 코드 | 데몬이 쓰는 파일은 HEAD와 같다. live_service.py만 d60b8d18 전 판이고, 데몬은 그중 `store_from_application`만 쓴다 | — | 사용자가 재설치를 마쳤다. 예약 정산과 교환 지급 코드가 들어 있다 |

## 2. 미커밋 변경

- `agent_market/ad_coin/**`, `scripts/ad_coin_*`: **없음**(`git status` 비어 있음)
- 로컬 커밋이 원격보다 앞서 있다. 푸시는 사용자 맥 푸시 흐름에 맡긴다.

## 3. 시험 전용 경로가 운영에 노출됐는지

| # | 무엇 | 지금 운영 | 위험 | 상태 |
|---|---|---|---|---|
| ① | `PersistentCredentialResolver` 기본 mTLS 검증기가 시험용 헤더 `x-mock-tls: verified`를 믿는다 | **활성 frontend에 남아 있음**(d60b8d18 미배포) | 심사자 토큰이 있으면 mTLS 없이 심사할 수 있다. 지금은 심사자 토큰을 발급할 운영 경로가 없어서 악용할 수 없다 | 수정됨, 배포 대기 |
| ② | **단계 보상**(`POST /api/ad-coin/v2/stages/claim`, `advertiser_platform.py:147`)이 캠페인별 `external_clearing` 계정에서 `model_seed`로 코인을 만들어 사람 지갑에 넣는다 | 라우트가 열려 있음. 활성 캠페인과 제안이 없어서 지금은 호출해도 거부된다 | **발행 상한(월 10만)과 성장 예산을 거치지 않는 코인 생성.** 캠페인이 생기면 단계마다(기본 20 atoms) 무한정 생성된다. 코인 경제 원칙(발행은 issuance만)과 어긋난다 | **보고만(PM 지시: 새 코드 중지)**. 제안: 보안 수정으로 라우트를 끄거나, 캠페인 예산에서 지급하게 바꾼다 |
| ③ | **중계 수수료 정산**(`ad_relay.py:391`)이 파트너별 `external_clearing`에서 `model_seed`로 파트너 운영 계정에 코인을 만든다 | 정산은 운영자 권한이 필요하다. 운영자를 만들 경로가 없어서 지금은 호출할 수 없다 | ②와 같은 발행 우회 | 보고만. 제안은 ②와 같다 |
| ④ | `real_value.py:100` 입금이 `model_seed` | 실가치 스위치가 꺼져 있어 라우트가 마운트되지 않는다 | 실가치를 켜면 생긴다 | 문제 없음(꺼짐 유지) |
| ⑤ | `Access.set_model_activation`, `provision_advertiser`, `grant`, `register_human_session` | 운영 라우트에서 부르지 않는다(시험만) | 없음. 노출되지 않았다 | 문제 없음 |
| ⑥ | `KeyVault()` 무작위 키 폴백 | 운영은 키 폴더를 쓴다. 사이트 연결은 무작위 링크 키면 시작을 거부한다 | 없음 | 문제 없음 |

## 4. 운영·SRE에 넘길 것

1. d60b8d18(①, frontend `agent_market/ad_coin/v2/live_service.py` 1개)
   - 활성 frontend의 live_service.py가 7b726f0a 판과 같으면 HEAD 파일로 겹친다.
2. admin과 execution 버전에 실린 AD Coin 사본은 HEAD와 다르다. 실행 경로는 아니다.
   - "운영 = git"을 맞추려면 다음 재구성 때 HEAD 판으로 맞추거나, 실지 않도록 패키징에서 빼는 것을 검토한다(운영·SRE 판단).
3. ②③은 보안 수정 대상이다.
   - PM·사용자가 허용하면 AD Coin이 다음을 바로 만들 수 있다: 라우트 끄기, 또는 `model_seed` 대신 캠페인 예산에서 지급
   - 시험과 배포 대기까지 맡는다.
