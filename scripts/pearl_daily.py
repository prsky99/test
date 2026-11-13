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
    queue = V.build_queue()
    (V.OUT / f'queue-{day}.json').write_text(json.dumps(queue, indent=1))
    V.run(queue)
    line = V.publish(board=True)
    import verify_snapshot                       # PM 11-14 supplement 2: the Check-and-Route tools read this
    verify_snapshot.main()
    done.write_text(line + '\n')
    print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
