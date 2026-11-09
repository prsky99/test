# AI AD Coin v6.2 개선 코드 재검수

2026-11-08 한국 시간. PostgreSQL 전용 모델 코드 검토·결함 수정과 후속 검증 기반 보강이다. 운영 서버/DB·실자금·체인에는 접근하지 않았다.

현재 작업 트리에 추가된 WP-04의 ‘전체 완료’ 기록을 재검토했다. 최초 P1 시험 8개와 기록의 119개 통과만으로 새 구현의 보안·운영 인수가 완료됐다고 볼 수 없어 완료 표기를 정정했다. 고정 계약에 없는 `recordHumanConsent`/`reviseCampaign`을 29개 HTTP operation처럼 설명한 내용도 바로잡았다.

## 재현과 수정

- **서버 경과 0에서 시청 시간 누적:** 기존 분기의 `min(3000, client_delta)`가 실제 서버 경과 없이 보상 시간을 만들 수 있었다. `evidence.py`가 원본 prefix·nonce chain·서버/클라이언트 단조 시각을 재검증하고 양 끝이 visible/foreground인 0~3초 구간의 보수적인 최소 시간만 계산한다. 0 경과는 0ms다.
- **백그라운드 경계 시간 포함:** 직전 부정 신호 뒤 긍정 신호까지의 구간을 세던 문제를 수정했다. 첫 긍정 전·부정 신호와 접한 구간·과도한 gap은 보상 시간에서 제외한다.
- **정지 후 시작 허용:** 이미 consented인 offer가 모델 switch off·광고주 suspended 상태에서 시작할 수 있었다. 정렬한 현재 authority guard·owner 단위 delivery lock과 최신 campaign/revision·승인/회원 epoch·기간·안전 상태를 시작/소재 조회 전에 확인한다. 기존 attention 창에도 축소된 일 한도를 적용한다.
- **재시도 nonce 불일치:** 과거 next_sequence와 현재 next_nonce를 섞어 반환하던 응답을 고정된 원래 snapshot으로 수정했다. fresh human proof는 계속 snapshot에 저장하지 않는다.
- **잘못된 mTLS 증거 허용:** callback의 문자열 `false`도 참으로 판정하던 변환을 제거했다. 실제 boolean True만 인정한다. 인증서 검증 자체는 여전히 외부 검증 callback/운영 인프라 연결이 필요하다.
- **반복·지연 보고 오류:** 다음 revision 번호가 매번 달라져 같은 집계를 계속 발행하던 문제를 수정했다. qualification 시각과 실제 P1 소비 journal을 집계하여 지연 보상을 원래 기간에 귀속한다. 단일 SQL snapshot의 award/pending 사실 manifest를 비공개로 보존하고 미결 증거는 complete=false다. 공개 digest는 반환 DTO에서 digest 자체만 제외한 canonical hash다. 이전 잘못된 보고는 수정하지 않고 새 revision으로 정정한다.
- **보상 cache 신뢰:** 보상 worker가 원본 증거를 독립 재계산한다. 합계/qualification cache 불일치나 prefix 이상은 review_pending이며 지급·반환을 하지 않는다. 자격 충족 후 중지/만료된 경우의 보상 권리는 보존한다. expiry는 owner별 TX에서 startup/active 기한을 재확인한다.
- **추가 보강:** 실제 경과를 반영한 lease row 검사·완료 검사를 같은 효과 TX에서 수행하고 만료되면 롤백한다. 미지원 event는 ACK하지 않는다. Ed25519 verifier의 canonical 표현·purpose/issuer/audience/stage/asset/버전과 원자량을 검사한다. 승인/배정 후 campaign revision은 변경하지 못하게 막고 내부 revise 입력도 고정 schema로 검증한다. 비동기 응답은 계약대로 202다.
- **기존 DB migration 누락:** CREATE IF NOT EXISTS로는 WP-03의 principal kind/owner 제약이 바뀌지 않았다. schema 3에서 실제 제약을 갱신하고 manifest 열을 명시적으로 추가한다. 기존 version 2 제약을 만든 DB에서 agent provision이 가능한지 시험했다.

## 증거

- `reproduced.xml/log`: 수정 전 유효한 재현 8/8 실패. `before.xml/log`는 worker 재현 요청의 last_sequence를 보정하기 전 초안이며 최종 재현 근거로 사용하지 않는다.
- `accepted.xml/log`: 단일 실행 **151/151 통과**, 실패/skip 0. 새 재검수 23·P1 8·commercial 42·저장 38·계약 31·기존 PG 9개다. SQLite 이전 시험 1개는 명시적으로 수집 제외했다.
- 실제 localhost HTTP에서도 서버 경과 없이 16개 신호를 보낸 공격이 보상·영수증을 만들지 못함을 확인했다. 정상 15초 노출·무클릭/무퀴즈 보상과 qualified cancel/expiry 권리 보존도 검증했다.
- `legacy-http-security/dynamic-security.json`: 기존 v1 실제 HTTP 보안 219/219 통과. 이를 새 v2 검증 개수로 합산하지 않는다.
- `secure-coding.json`: 변경 v2 및 기존 API의 Ruff S 0건. 일반 Ruff 검사 통과. 기존 Starlette/httpx deprecation warning은 1건이다.
- 현재 구현은 schema 3·38개 표·계약과 일치하는 29개 operation, 등록 SQL 403개(기존 174 보존+v2 229)다. `verification.json`에 파일 hash와 범위를 기록한다. 이전 보고는 덮어쓰지 않았다.

## 남은 범위

이 결과는 전체 보안·품질·성능 인증이 아니다. 실제 IdP/지속 credential 저장·mTLS handshake, owner UI와 브라우저 renderer·접근성·철회 알림, 운영 rate-limit/DB role·RLS·키 회전·백업/복구/부하 인수는 남아 있다. in-process CredentialResolver와 인증 fixture를 운영 인증으로 표시하지 않는다. 신호를 검증했다고 실제 사람의 집중을 완전히 증명하지 않는다. 모델 서버도 공개 운영 앱에 mount하지 않았고 실제 코인 발행·상환·외부 송금은 열지 않았다.
