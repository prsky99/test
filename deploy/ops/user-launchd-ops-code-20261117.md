# 운영 작업 7개를 커밋으로 만든 폴더의 코드로 옮기기 (소스 검토 4절 1번, 11-17 PM 실행)

11-16 운영·SRE가 썼습니다. 실행은 PM이 11-17 topic 공개 뒤 오후에 합니다.

## 무엇이 바뀌나

아래 7개 launchd 작업은 지금 여러 세션이 함께 고치는 작업본의 코드를 그대로 실행합니다. 그래서 누가 파일을 저장하는 순간 운영에 적용됩니다. 11-15에 광고 원장·백업 두 작업을 옮긴 것과 같은 방식으로 `gateway-data/ops-code/current`(한 커밋에서 만든 폴더)를 실행하게 바꿉니다.

| 작업 | 도는 때 | 하는 일 |
|---|---|---|
| `opsauto.watch` | 10분마다 | 운영 감시(현황판 자동 점검, 밤 시험·real_task 시작) |
| `opsauto.watchstale` | 5분마다 | 감시가 멈췄는지 확인 |
| `opsauto.netpath` | 1분마다 | 네트워크 경로 기록 |
| `opensearch-sync` | 늘 떠 있음(10분 주기) | 탐색 색인 동기화 |
| `opsauto.ofac` | 06:20 | 제재 주소 목록 갱신 |
| `opsauto.pearltests` | 09:12 | 진주 시험 |
| `opsauto.paidreconcile` | 09:20 | USDC 결제 대사 |

- plist는 `deploy/launchd/ops-pinned/`에 있습니다. 지금 plist와 다른 곳은 실행 파일 경로와 작업 폴더뿐입니다(`check`로 확인할 수 있습니다).
- 데이터 위치는 그대로입니다. `gateway-data`, `logs`, `exports`, `.venv`, `.venv-tests`, `tests`, `reports`는 링크로 지금과 같은 곳을 씁니다.
  - `tests`와 `reports` 링크는 11-16에 새로 더했습니다. 감시가 시작하는 real_task_score, 결제 흐름 시험, 안정성 관문이 이 두 폴더를 쓰기 때문입니다.
- 밤 전체 시험은 이 폴더에서 시작돼도 진짜 작업본에서 돕니다(`night_tests.repo_root`).
- 코드를 바꾸려면 운영·SRE가 `.venv/bin/python -m scripts.ops_code install <커밋>`을 실행합니다. 다음 실행부터 새 코드를 씁니다.

## 실행 순서 (PM, 터미널)

시각 조건: 매시 :55~:10, 06:00~07:00·10:00~11:00 관문 회차, 09:05~09:30 진주 시험·대사는 피합니다. 스크립트가 이 시간이면 종료 75로 멈춥니다.

1) 운영·SRE가 미리 할 일: 이 변경이 든 커밋으로 폴더를 설치합니다(launchd는 건드리지 않습니다).

```bash
.venv/bin/python -m scripts.ops_code install origin/claude/hopeful-darwin-i3qj6n
```

2) 바뀔 내용을 확인합니다(아무것도 바꾸지 않음). `link tests ok`, `link reports ok`가 나와야 합니다.

```bash
bash deploy/ops/launchd-ops-code-switch-20261117.sh check
```

3) 교체합니다. 지금 plist를 `~/agentcon-plist-backup-20261117/`에 보관합니다. 작업마다 bootout 뒤 내려갈 때까지(최대 60초) 기다렸다가 bootstrap합니다. 11-15 터널 전환 때처럼 bootout 직후 bootstrap하면 실패하기 때문입니다.

```bash
bash deploy/ops/launchd-ops-code-switch-20261117.sh switch
```

4) 확인: 7줄 모두 `working directory = .../gateway-data/ops-code/current`이고, 마지막에 `all seven switched`가 나오면 됩니다. 10분 안에 `logs/ops/watch-actions.md`에 새 줄이 생기는지도 봅니다.

## 되돌리기

보관한 plist로 같은 방식(기다린 뒤 bootstrap)으로 되돌립니다.

```bash
bash deploy/ops/launchd-ops-code-switch-20261117.sh rollback
```

## 남는 것

`agentcon` 22행도 작업본을 씁니다(보고서 4절 1번). 이것은 배포 도구라 따로 다룹니다.
