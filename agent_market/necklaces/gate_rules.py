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

# Daily retest and hold (section 7): a day under 95% is rerun once; immediate hold below this rate.
RETEST_PASS_RATE = 0.95
IMMEDIATE_HOLD_BELOW = 0.80

# Self-made substitute agents (section 10): contract tests all, role tasks all, 29 of 30 held-out cases.
SUBSTITUTE_CASES = 30
SUBSTITUTE_PASS = 29

# Test report v2 for verified pearls and substitutes (deploy/PEARL_REPORT_GATE.md): 85 points plus the data-quality
# musts (accuracy against an answer set or public reference, clean answer).
REPORT_SCORE = 85


def summary():
    """The public, numeric part of the gate (for the methodology page)."""
    return {'necklace': {'held_out_cases': TOTAL, 'pass_total': TOTAL_PASS, 'rounds': TOTAL // ROUND,
                         'cases_per_round': ROUND, 'pass_per_round': ROUND_PASS, 'round_gap_hours': ROUND_GAP_HOURS,
                         'completion': COMPLETION, 'p95_ms': P95_MS, 'delta': DELTA},
            'retest': {'pass_rate': RETEST_PASS_RATE, 'immediate_hold_below': IMMEDIATE_HOLD_BELOW},
            'substitute': {'held_out_cases': SUBSTITUTE_CASES, 'pass': SUBSTITUTE_PASS},
            'report_v2': {'score': REPORT_SCORE, 'musts': ['accuracy_check', 'clean_answer']}}
