# OFAC 갱신을 launchd로 옮기기 (정밀 검토 R06, 11-15 운영·SRE)

지금은 OFAC 제재 주소 갱신(매일 06:20)을 Claude 예약 작업이 합니다. 모델 사용 한도에 걸리면 멈춥니다. 같은 일을 모델 없이 launchd가 하게 합니다.
- 실행: `deploy/ops/ofac-refresh-daily.sh` → `scripts.ad_coin_ofac_refresh`(DB 접속 없음, 공개 자료만)
- 실패하면 5분 뒤 한 번 더 합니다. 결과는 지금과 같은 형식으로 `logs/ops/ofac-refresh.md`에 한 줄 남깁니다.
- 실패했는데 목록 파일이 6일보다 오래되면 현황판 '넘기는 일'에 AI AD Coin 앞으로 한 줄 적습니다.
- 시험: `tests/test_ofac_refresh_daily.py`(가짜 실행으로 성공·실패 세 경우)

## 사용자가 할 일 (터미널, 한 번)

1) launchd 작업 설치

```bash
cp deploy/launchd/ops/biz.agentconcierge.opsauto.ofac.plist ~/Library/LaunchAgents/
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.opsauto.ofac.plist
```

```bash
launchctl print gui/$(id -u)/biz.agentconcierge.opsauto.ofac | grep -E "state|path"
```

2) Claude 앱의 예약 작업 두 개 끄기(앱의 예약 작업 화면에서)
- `agentconcierge-ofac-daily-refresh` (OFAC 갱신, 1)의 launchd가 대신함)
- `agentconcierge-daily-test-reports` (설명은 "11-10 꺼짐"인데 실제로 켜져 있음. launchd `biz.agentconcierge.opsauto.testreports`가 02:30에 같은 일을 함 — 중복)

3) 다음 날 06:21 이후 확인: `tail -1 logs/ops/ofac-refresh.md`가 그날 날짜로 한 줄 늘었는지. 운영·SRE가 확인해 보고합니다.

## 되돌리기

```bash
launchctl bootout gui/$(id -u)/biz.agentconcierge.opsauto.ofac
```

```bash
rm ~/Library/LaunchAgents/biz.agentconcierge.opsauto.ofac.plist
```

그리고 Claude 앱에서 `agentconcierge-ofac-daily-refresh`를 다시 켭니다.

## 참고
- 배포 도구(`service_deploy.persist()`)는 83a023d2부터 자기 이름(역할×칸)의 plist만 지웁니다. 이 작업(`biz.agentconcierge.opsauto.*`)은 원래 다른 접두사라 영향이 없습니다.
- 백업 점검은 따로 작업을 만들지 않고 10분 감시(ops_watch)에 백업 나이·복사 결과로 넣습니다(R53).
- R05(운영 작업이 작업본 대신 커밋으로 만든 폴더의 코드를 실행)가 끝나면 이 plist의 실행 경로도 함께 바뀝니다.
