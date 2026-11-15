"""The ops launch gate's numbers, in one place (deploy/NECKLACE_GATE.md; owner 운영·SRE).

The methodology page (scripts/methodology.py) and the gate tools (scripts/substitute_gate.py, the necklace gate)
read these values; the document explains them. Change a number here, in the document and in its tests together.
The held-out answer sets themselves are never published.
"""

# Necklace launch gate (sections 1 and 3; PM 11-14 07:5x): 60 held-out cases in two rounds of 30, four hours apart.
TOTAL = 60                 # held-out cases per gate
TOTAL_PASS = 57            # at least 57 of 60 (95%)
ROUND = 30                 # cases per round
ROUND_PASS = 28            # at least 28 of 30 in each round
ROUND_GAP_HOURS = 4        # rounds at least four hours apart
COMPLETION = 0.95          # completion rate over the 60 runs
P95_MS = 5000              # p95 latency, public address, new connection, no samples dropped
DELTA = '> 0'              # necklace success minus the best single pearl, overall and same-role tasks

# Daily retest and hold (section 7). What runs today (workflow 11-15, checked against the code for the growth
# team's methodology page): necklaces.daily sets quality_low when a day's retest success is below
# IMMEDIATE_HOLD_BELOW and the judge holds the necklace at its next run (once a day, not the moment a retest ends);
# the judge also holds when the last retest is older than judge.STALE_HOURS or the delta is 0 or less.
# RETEST_PASS_RATE is the document's target; the "rerun a day under 95% once" step is not built, so it is not
# published as a retest rule.
RETEST_PASS_RATE = 0.95
IMMEDIATE_HOLD_BELOW = 0.80

# Self-made substitute agents (section 10): contract tests all, role tasks all, 29 of 30 held-out cases.
SUBSTITUTE_CASES = 30
SUBSTITUTE_PASS = 29

# Test report v2 for verified pearls and substitutes (deploy/PEARL_REPORT_GATE.md): 85 points plus the data-quality
# musts (accuracy against an answer set or public reference, clean answer).
REPORT_SCORE = 85

# The evaluator version the pearl reports are graded with now. It lives here, in code every release ships, so the
# judge of a deployed release compares the verify snapshot with its own version (PM 16:29, "production = git"; before
# this the judge read scripts/report_v2.py under AGENTCON_PROJECT_ROOT, the working tree). scripts/report_v2 takes
# it from here. Raising it is a change paired with a jobs deploy, and the snapshot is regenerated with it.
EVALUATOR_VERSION = 'dq-2026-11-15e'   # 11-15e: FX reference moved to frankfurter.dev, weather temp_max/min read


def _retest_rules() -> dict:
    """The retest rules as they run (daily summary, then the judge), read from the code that applies them."""
    from .daily import HOLD_SUCCESS
    from .judge import STALE_HOURS
    return {'hold_below_at_next_daily_check': HOLD_SUCCESS, 'hold_when_older_than_hours': STALE_HOURS,
            'hold_when_delta': '<= 0', 'checked': 'daily'}


def summary():
    """The public, numeric part of the gate (for the methodology page)."""
    return {'necklace': {'held_out_cases': TOTAL, 'pass_total': TOTAL_PASS, 'rounds': TOTAL // ROUND,
                         'cases_per_round': ROUND, 'pass_per_round': ROUND_PASS, 'round_gap_hours': ROUND_GAP_HOURS,
                         'completion': COMPLETION, 'p95_ms': P95_MS, 'delta': DELTA},
            'retest': _retest_rules(),
            'substitute': {'held_out_cases': SUBSTITUTE_CASES, 'pass': SUBSTITUTE_PASS},
            'report_v2': {'score': REPORT_SCORE, 'musts': ['accuracy_check', 'clean_answer']}}
