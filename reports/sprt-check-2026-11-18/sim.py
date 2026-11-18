"""Gate rules compared by exact enumeration (all 2^60 orders summarised by DP over (case index, round fails, total fails, LLR state))
and by Monte Carlo as a cross-check. A rule is a function step(state, outcome) -> state and decide(state) -> 'pass'|'fail'|None."""
import math, random, json, sys
from functools import lru_cache

R, N = 30, 60
P0, P1, ALPHA, BETA = 0.90, 0.98, 0.05, 0.10
LS, LF = math.log(P1 / P0), math.log((1 - P1) / (1 - P0))
A, B = math.log((1 - BETA) / ALPHA), math.log(BETA / (1 - ALPHA))

def current_decide(n, s, f, f1, f2, early):
    # current gate: >= 28/30 each round and >= 57/60 => fails <= 2 per round and <= 3 total
    if f1 > 2 or f2 > 2 or f > 3:
        return 'fail' if early or n == N else None
    if n == N:
        return 'pass'
    if early:
        r1_left = max(0, R - n); r2_left = N - max(n, R)
        # pass is certain if the worst remaining outcome still passes
        if f1 + r1_left <= 2 and f2 + r2_left <= 2 and f + r1_left + r2_left <= 3:
            return 'pass'
    return None

def sprt_decide(n, s, f, f1, f2, m, undecided, n2):
    llr = s * LS + f * LF
    n1 = min(n, R) if n2 is None else n - n2  # not used
    if llr <= B:
        return 'fail'
    if llr >= A and (m == 0 or (n2 is not None and n2 >= m)):
        return 'pass'
    if n == N:
        if undecided == 'fail':
            return 'fail'
        if undecided == 'llr':
            return 'pass' if llr > 0 else 'fail'
        if undecided == 'current':
            return 'pass' if (f1 <= 2 and f2 <= 2 and f <= 3) else 'fail'
    return None

def run(rule, p, rng=None, exact=True):
    """Exact: DP over states. Rounds: round 1 is cases 1..30 unless the SPRT rule moves to round 2 early (m>0 and
    llr >= A after >= m round-1 cases); round 2 then runs until a decision or until N total."""
    # state: (n, s, f, f1, f2, in_r2, n2)
    from collections import defaultdict
    dist = {(0, 0, 0, 0, 0, False, 0): 1.0}
    res = {'pass': 0.0, 'fail': 0.0}; ncases = 0.0
    while dist:
        nxt = defaultdict(float)
        for (n, s, f, f1, f2, r2, n2), pr in dist.items():
            for ok, q in ((True, p), (False, 1 - p)):
                if q == 0: continue
                ns, nf = s + ok, f + (not ok)
                nf1 = f1 + (0 if ok or r2 else 1); nf2 = f2 + (0 if ok or not r2 else 1)
                nn = n + 1; nn2 = n2 + (1 if r2 else 0)
                d, nr2 = rule(nn, ns, nf, nf1, nf2, r2, nn2)
                if d:
                    res[d] += pr * q; ncases += pr * q * nn
                else:
                    nxt[(nn, ns, nf, nf1, nf2, nr2, nn2)] += pr * q
        dist = nxt
    return res['pass'], ncases

def current(early):
    def rule(n, s, f, f1, f2, r2, n2):
        return current_decide(n, s, f, f1, f2, early), (n >= R)
    return rule

def sprt(m, undecided):
    def rule(n, s, f, f1, f2, r2, n2):
        llr = s * LS + f * LF
        if m == 0:
            return sprt_decide(n, s, f, f1, f2, 0, undecided, None), (n >= R)
        if not r2:
            # round 1: fail on B anytime; move to round 2 at A after >= m cases or at 30 cases
            if llr <= B: return 'fail', False
            if n == N: return sprt_decide(n, s, f, f1, f2, m, undecided, 0), False
            move = (llr >= A and n >= m) or n >= R
            return None, move
        d = sprt_decide(n, s, f, f1, f2, m, undecided, n2)
        if d is None and n2 >= R:   # round 2 also capped at 30
            d = sprt_decide(N, s, f, f1, f2, m, undecided, n2)
        return d, True
    return rule

def mc(rule, p, sims, seed=7):
    rng = random.Random(seed); passes = 0; total = 0
    for _ in range(sims):
        n = s = f = f1 = f2 = n2 = 0; r2 = False
        while True:
            ok = rng.random() < p
            s += ok; f += (not ok); f1 += (not ok and not r2); f2 += (not ok and r2)
            n += 1; n2 += 1 if r2 else 0
            d, r2n = rule(n, s, f, f1, f2, r2, n2)
            if d: passes += d == 'pass'; total += n; break
            r2 = r2n
    return passes / sims, total / sims

PS = [0.80, 0.85, 0.90, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99, 1.00]
RULES = {
    'current (all 60)': current(False),
    'current + stop when decided': current(True),
    'SPRT, max 60, undecided=fail': sprt(0, 'fail'),
    'SPRT, max 60, undecided=current rule': sprt(0, 'current'),
    'SPRT, rounds, >=10 per round, undecided=current': sprt(10, 'current'),
    'SPRT, rounds, >=15 per round, undecided=current': sprt(15, 'current'),
    'SPRT, rounds, >=10 per round, undecided=fail': sprt(10, 'fail'),
}
out = {'params': {'p0': P0, 'p1': P1, 'alpha': ALPHA, 'beta': BETA, 'A': A, 'B': B, 'llr_success': LS, 'llr_fail': LF,
                  'successes_to_pass_with_0_fails': math.ceil(A / LS), 'extra_successes_per_fail': -LF / LS}}
for name, rule in RULES.items():
    out[name] = {}
    for p in PS:
        ep, en = run(rule, p)
        out[name][p] = {'pass': round(ep, 4), 'mean_cases': round(en, 2)}
# Monte Carlo cross-check on three rules and three p
check = {}
for name in ('current + stop when decided', 'SPRT, max 60, undecided=fail', 'SPRT, rounds, >=10 per round, undecided=current'):
    for p in (0.90, 0.95, 0.98):
        mp, mn = mc(RULES[name], p, 200000)
        check[f'{name} @ {p}'] = {'mc_pass': round(mp, 4), 'mc_mean': round(mn, 2), 'exact': out[name][p]}
out['monte_carlo_check'] = check
json.dump(out, open(sys.argv[1], 'w'), indent=1)
