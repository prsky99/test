# 감시가 멈추면 알리는 작업 설치 (정밀 검토 R53, 11-15 운영·SRE)

10분 감시(`biz.agentconcierge.opsauto.watch`)가 멈추면 지금은 아무도 모릅니다. 5분마다 `logs/ops/watch.jsonl`이 25분 넘게 그대로인지 보고, 그러면 바탕화면 알림 파일과 `logs/ops/pm-escalations.md`에 한 줄 적습니다(1시간에 한 번). 파일만 읽고, 네트워크와 DB는 쓰지 않습니다.
- 실행: `deploy/ops/watch-stale-check.sh`, 시험: `tests/test_ops_watch_r53.py`

## 사용자가 할 일 (터미널, 한 번)

```bash
cp deploy/launchd/ops/biz.agentconcierge.opsauto.watchstale.plist ~/Library/LaunchAgents/
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.opsauto.watchstale.plist
```

```bash
launchctl list | grep watchstale
```

## 되돌리기

```bash
launchctl bootout gui/$(id -u)/biz.agentconcierge.opsauto.watchstale
```

```bash
rm ~/Library/LaunchAgents/biz.agentconcierge.opsauto.watchstale.plist
```

## 함께 바뀐 것 (설치 없이 다음 10분 감시부터 적용)
- 10분 감시가 새로 보는 것: launchd 작업(biz.agentconcierge.*)의 종료 코드·PID, 백업 나이(26시간)·복사 결과, PostgreSQL·Redis·OpenSearch·cloudflared·jobs·execution 생존. 사이트 점검은 맨 앞에서 45초 안에 끝냄.
- 같은 경보가 6번 넘게 닫히지 않으면 바탕화면 알림 파일과 `logs/ops/pm-escalations.md`로 격상. launchd는 세션에 메시지를 보낼 수 없어, PM 자율 점검(2시간)이 이 파일을 읽게 해야 함(PM 작업).
