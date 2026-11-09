# AI AD Coin v2 무상 활동 포인트 모드

- **결정:** 2026-11-09 운영 헌장 1절. 법률 의견 없이도 합법인 범위에서 성장한다.
- **구현:** 2026-11-10, AI AD Coin 팀
- **원칙:** v2는 실가치 스위치(`AD_COIN_REAL_VALUE_ENABLED`, 기본 꺼짐)가 꺼져 있으면 **활동 포인트 모드**로만 동작한다. 모드는 코드(`agent_market/ad_coin/v2/points.py`)가 정하며, 설정으로 고를 수 없다.

## 1. 규칙과 강제 위치

| 규칙 | 강제하는 곳 | 시험 |
|---|---|---|
| 돈 주고 살 수 없다 | 입금 경로(`RealValueGateway`, 웹훅)는 실가치 스위치가 꺼져 있으면 404/403 | `test_points_cannot_be_bought_or_cashed_out`, `test_ad_coin_v2_real_value_switch.py` |
| 현금화할 수 없다 | 체인 인출·상환도 실가치 스위치 뒤에 있다 | 같음 |
| 다른 사람에게 보낼 수 없다 | **원장 자체**(`ModelLedger.post`): 한 기록에 서로 다른 두 사람의 개인 계정(`user_available`, `user_locked`)이 함께 있으면 `points_not_transferable`로 거부한다. 기록 종류와 상관없다 | `test_points_cannot_move_between_people` |
| 플랫폼 혜택에만 쓴다 | `AgentPaymentGateway.hold_execution`: 받는 쪽이 플랫폼 혜택 목록(`points.BENEFITS`: 무료 실행 크레딧, 워크스페이스 혜택)이 아니면 `points_redeem_platform_benefits_only`로 거부한다. 외부 제공자에게 지급하지 않는다 | `test_points_pay_only_for_platform_benefits` |
| 활동이 없으면 만료된다 | 365일 동안 적립이나 사용이 없는 지갑은 잔액을 플랫폼의 만료 계정으로 옮긴다(`expire_inactive_points`, 원장 종류 `expiry`, 지갑·날짜별 멱등). 작업자 데몬이 1시간마다 실행한다 | `test_idle_points_expire_to_the_platform_and_active_ones_stay` |
| 한 사람 안의 이동은 된다 | 사용 보류(available → locked)와 되돌리기는 같은 사람 안이라 허용한다 | `test_one_person_can_still_lock_and_release_their_own_points` |

**실가치 모드에서는** 위 제한 가운데 이전, 혜택 전용, 만료가 풀린다. 이 모드는 법률 의견을 받기 전에는 켜지 않는다. 기존 원장 시험과 외부 제공자 결제 시험은 그 모드로 돌린다.

## 2. 광고주와 돈

- 광고주는 광고비를 **용역 대금**으로 낸다. 포인트를 사는 것이 아니다. 지금 비공개 시험에서는 예산이 시험 크레딧이다.
- 사람이 받는 포인트는 플랫폼이 혜택으로 주는 것이다. 광고주에게 팔지 않는다.

## 3. 화면 (영어 공개 화면, `v2/web`)

- 사람에게 보이는 단위는 "points"이고, 광고주 예산 단위는 "test credits"다.
- 잔액 카드와 바닥글에 규칙을 보인다: 살 수 없음, 현금화·이전 불가, 플랫폼 혜택에만 사용, 365일 동안 활동이 없으면 만료, 현금 가치 없음.
- 운영자용 보기(Platform Audit, Agent Relays와 위임 결제 개요)는 공개 화면에서 뺐다. 해당 API는 운영자 권한(`platform.operate`)이 있어야만 쓸 수 있다. 운영 화면(`/ad-coin/admin`, 한국어)에 붙이는 것은 다음 작업이다.
- 시험: `test_public_v2_page_has_no_internal_terms_and_states_the_points_rules`

## 4. 남은 일

- 혜택 목록의 실제 내용(무료 실행 크레딧 1회에 필요한 포인트 등)과 지급 흐름(혜택 사용 → 실제 실행 연결)
- 만료 30일 전 알림(동의한 사람에게만, 광고성 메시지가 아닌 서비스 안내로)
- 이용 조건 초안(`docs/AD_COIN_TERMS_DRAFT.md`)을 이 모드에 맞게 다시 쓰기
