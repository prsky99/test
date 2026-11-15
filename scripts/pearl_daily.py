"""Daily pearl role tests (PM 11-14, charter 0), run by launchd biz.agentconcierge.opsauto.pearltests at 09:12.

Builds the day's queue (40 retests + 80 new candidates), runs it within the limits (120 a day, 60 after provider
refusals pass 5%, per-provider 3 a day / 60 s / stop after 429), then writes the ranking, role_groups.json and
the board line. A day runs once (exports/pearls/done-YYYY-MM-DD); nothing is written to any database.

    .venv/bin/python -m scripts.pearl_daily            # today, once
    .venv/bin/python -m scripts.pearl_daily --force    # again today (the provider limits still hold)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import report_v2 as V  # noqa: E402


RETRY_WAIT = 60        # seconds before the one retry of a failed stage (R15)


def alert(text):
    """R15 (precision review): a failed daily run is said on the board's handoff list and the desktop alert file, so
    the public tools do not keep answering yesterday's results unnoticed (11-14 09:12 failed silently)."""
    try:
        import ops_auto
        ops_auto.TEAM.setdefault('pearl_daily', '검색과 RAG')
        ops_auto.board_handoff('pearl_daily', text)
        ops_auto.prepend_desktop(f'{ops_auto.now()} [진주 매일 시험] {text}')
    except Exception as exc:
        print(f'alert failed: {type(exc).__name__}: {exc}', file=sys.stderr)


def stage(name, work, failures, retry=True):
    """Run one stage; on an exception wait RETRY_WAIT and try once more (when RETRY), else record the failure."""
    for attempt in (1, 2) if retry else (1,):
        try:
            return work()
        except Exception as exc:
            print(f'{name} failed ({attempt}): {type(exc).__name__}: {exc}', file=sys.stderr)
            if retry and attempt == 1:
                time.sleep(RETRY_WAIT)
                continue
            failures.append(f'{name} {type(exc).__name__}')
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    day = time.strftime('%Y-%m-%d')
    done = V.OUT / f'done-{day}'
    if done.exists() and '--force' not in argv:
        print(f'{day}: already run ({done})')
        return 0
    V.OUT.mkdir(parents=True, exist_ok=True)
    try:                                          # 11-14 grade-tiered health: bulk hosts and suspects, once a day
        import health_tiers
        health_tiers.main()
    except Exception as exc:
        print(f'health_tiers failed: {type(exc).__name__}: {exc}')
    failures = []
    imported = stage('import_fallbacks', V.import_fallbacks, failures)
    print(f'own fallback versions imported: {imported}')   # 에이전트 팀 avc-results files (PM plan A)
    queue = stage('build_queue', V.build_queue, failures) or []
    (V.OUT / f'queue-{day}.json').write_text(json.dumps(queue, indent=1))
    # Not retried as a whole: a second pass would test again what the first already tested. run() itself keeps
    # going past one candidate's error and retries each storage once.
    errors = stage('run', lambda: V.run(queue), failures, retry=False) or {}
    line = stage('publish', lambda: V.publish(board=True), failures)

    def snapshot():
        import verify_snapshot                   # PM 11-14 supplement 2: the Check-and-Route tools read this
        return verify_snapshot.main()
    stage('verify_snapshot', snapshot, failures)
    if errors.get('save_errors'):
        failures.append(f"stored 0 of {errors['save_errors']} results")
    if failures:
        alert(f'{day} 진주 매일 시험 일부 실패: ' + ', '.join(failures) +
              (' (공개 도구가 전날 결과를 답함)' if line is None else '') + ' — scripts/pearl_daily.py 로그 확인')
    if line is None:
        return 1                                  # no done file: a --force run or tomorrow's run publishes again
    done.write_text(line + '\n')
    print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
