# 운영 작업이 커밋으로 만든 폴더의 코드를 실행하게 바꾸기 (정밀 검토 R05, 11-15 운영·SRE)

지금은 광고 원장 쓰기(`biz.agentconcierge.opsauto.housead`, 09:10)와 백업(`biz.agentconcierge.backup`, 04:30)이 여러 세션이 함께 고치는 작업본의 코드를 그대로 실행합니다. 누가 작업본을 고치는 중이면 그 코드가 원장과 백업에 쓰입니다.
- 바뀐 뒤: 두 작업은 `gateway-data/ops-code/current`의 코드를 실행합니다. 이 폴더는 `scripts.ops_code install <커밋>`이 한 커밋에서 만듭니다. 데이터(gateway-data, logs, exports, .venv)는 링크로 지금과 같은 곳을 씁니다.
- 코드를 바꾸려면 운영·SRE가 `.venv/bin/python -m scripts.ops_code install <커밋>`을 실행합니다. 다음 실행부터 새 코드를 씁니다. 되돌리기는 `.venv/bin/python -m scripts.ops_code rollback`입니다.
- 11-15 09:55에 첫 폴더를 설치했습니다(커밋 0dc4e0dc). 아래 plist를 바꾸기 전에는 아무 작업도 이 폴더를 쓰지 않습니다.
- 시험: `tests/test_ops_code.py`

## 사용자가 할 일 (터미널, 한 번, 09:10·04:30 실행 시각을 피해서)

1) 지금 plist 보관

```bash
mkdir -p ~/agentcon-plist-backup-20261115 && cp ~/Library/LaunchAgents/biz.agentconcierge.opsauto.housead.plist ~/Library/LaunchAgents/biz.agentconcierge.backup.plist ~/agentcon-plist-backup-20261115/
```

2) 광고 원장 작업 교체

```bash
launchctl bootout gui/$(id -u)/biz.agentconcierge.opsauto.housead
```

```bash
cp deploy/launchd/ops-pinned/biz.agentconcierge.opsauto.housead.plist ~/Library/LaunchAgents/
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.opsauto.housead.plist
```

3) 백업 작업 교체

```bash
launchctl bootout gui/$(id -u)/biz.agentconcierge.backup
```

```bash
cp deploy/launchd/ops-pinned/biz.agentconcierge.backup.plist ~/Library/LaunchAgents/
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.backup.plist
```

4) 확인: 두 줄 모두 `gateway-data/ops-code/current`가 보이면 됩니다.

```bash
launchctl print gui/$(id -u)/biz.agentconcierge.backup | grep "working directory"; launchctl print gui/$(id -u)/biz.agentconcierge.opsauto.housead | grep -E "working directory|arguments" -A2 | head -6
```

## 되돌리기

```bash
launchctl bootout gui/$(id -u)/biz.agentconcierge.opsauto.housead; launchctl bootout gui/$(id -u)/biz.agentconcierge.backup
```

```bash
cp ~/agentcon-plist-backup-20261115/*.plist ~/Library/LaunchAgents/
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.opsauto.housead.plist; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.backup.plist
```

## 다음 차례(이 문서 범위 밖)
- 10분 감시(watch), 시험 보고서(testreports), 진주 시험(pearltests), 경로 측정(netpath)도 같은 방식으로 옮깁니다. 위 두 작업이 하루 이상 문제없이 돈 뒤에 합니다.
