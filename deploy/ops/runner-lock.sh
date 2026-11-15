# Deploy runner board helpers (운영·SRE, PM 11-14 18:2x; in the repository since 11-15, precision review R55).
# Source it from a runner:  . deploy/ops/runner-lock.sh   (RL_ROOT defaults to the project this file is in)
#   RL_TEAM=운영·SRE RL_WHAT="frontend <release> (...)"   set before use
#   rl_reserve   while waiting: one "예약" line under ## 배포 대기 (not the lock section)
#   rl_take      at the deploy moment only: lock line stamped with the current time; exit 3 if held
#   rl_release   remove the lock line (empty section -> (비어 있음))
#   rl_unreserve remove the 예약 line
# 11-14: evening.sh built its lock line at start (13:18) and took the lock at 18:10, so the line looked
# 301 minutes old to ops_watch and stale to other teams' deploy tools.
RL_ROOT=${RL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
export RL_ROOT
RL_TEAM=${RL_TEAM:-운영·SRE}
_rl() { "$RL_ROOT/.venv/bin/python" - "$@" <<'PY'
import os, sys, time
sys.path.insert(0, os.environ["RL_ROOT"] + "/scripts")
from heavy_slot import board_lock
mode, team, what, pid, key = sys.argv[1:6]
p = os.environ.get("RL_BOARD", os.environ["RL_ROOT"] + "/logs/ops/status-board.md")
stamp = time.strftime('%m-%d %H:%M')
with board_lock():
    t = open(p, encoding='utf-8').read()
    def section(head):
        i = t.index(head) + len(head); return i, t.index('\n## ', i)
    if mode in ('take', 'release'):
        i, j = section('## 배포 잠금\n'); sec = t[i:j]
        mine = [l for l in sec.split('\n') if f'pid={pid} ' in l and l.startswith(f'- {team} ')]
        if mode == 'take':
            if sec.strip() != '(비어 있음)':
                print('lock held:', sec.strip()[:200]); sys.exit(3)
            sec = sec.replace('(비어 있음)', f'- {team} {stamp} pid={pid} {what}', 1)
        else:
            for l in mine:
                sec = sec.replace(l + '\n', '', 1) if l + '\n' in sec else sec.replace(l, '', 1)
            if not sec.strip():
                sec = '\n(비어 있음)\n'
    else:
        i, j = section('## 배포 대기\n'); sec = t[i:j]
        tag = f'[예약 {key}]'
        lines = [l for l in sec.split('\n') if tag not in l]
        if mode == 'reserve':
            lines.insert(1 if lines and lines[0] == '' else 0,
                         f'- **{tag} {team} 실행기 pid={pid} {stamp}부터 대기: {what}** — 잠금이 아님. 배포 순간에만 ## 배포 잠금에 그 시각으로 줄을 씀')
        sec = '\n'.join(lines)
    open(p, 'w', encoding='utf-8').write(t[:i] + sec + t[j:])
PY
}
rl_reserve()   { _rl reserve "$RL_TEAM" "$RL_WHAT" "$$" "$RL_KEY"; }
rl_unreserve() { _rl unreserve "$RL_TEAM" "$RL_WHAT" "$$" "$RL_KEY"; }
rl_take()      { _rl take "$RL_TEAM" "$RL_WHAT" "$$" "$RL_KEY"; }
rl_release()   { _rl release "$RL_TEAM" "$RL_WHAT" "$$" "$RL_KEY"; }
