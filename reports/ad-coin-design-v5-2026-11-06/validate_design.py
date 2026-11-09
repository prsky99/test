"""Validate v5 documentation and a closed accounting model, never product code or real funds.

Uses only local files and integer arithmetic. No keys, network, databases or chain actions.
This does not implement or pass the 43 planned product acceptance checks.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SPEC = ROOT / 'docs/ad_coin_v5_spec.json'
KEYS = ('advertiser', 'user', 'provider', 'operator', 'direct', 'platform')
ATOM = 10 ** 6


class Rejected(ValueError):
    pass


class Model:
    def __init__(self):
        self.r = self.s = self.c = self.external = 0
        self.balances = dict.fromkeys(KEYS, 0)
        self.posted = {}

    def snapshot(self):
        return (self.r, self.s, self.c, self.external, tuple(self.balances.items()),
                json.dumps(self.posted, sort_keys=True))

    def invariant(self):
        assert self.r >= self.s
        assert self.c >= sum(self.balances.values())
        assert self.s == self.c + self.external
        assert min(self.r, self.s, self.c, self.external, *self.balances.values()) >= 0

    def apply(self, action, amount, key, *, asset='USDC', recipient='provider'):
        if type(amount) is not int or not 0 < amount <= 10 ** 18:
            raise Rejected('invalid amount')
        payload = [action, amount, asset, recipient]
        if key in self.posted:
            if self.posted[key] != payload:
                raise Rejected('idempotency conflict')
            return 'already_done'
        before = deepcopy(self.__dict__)
        try:
            if action == 'deposit':
                if asset != 'USDC':
                    raise Rejected('unsupported collateral')
                self.r += amount; self.s += amount; self.c += amount
                self.balances['advertiser'] += amount
            elif action == 'reward':
                if amount * 5000 // 10000 == 0:
                    raise Rejected('zero user reward')
                self.balances['advertiser'] -= amount
                shares = {'user': amount * 5000 // 10000, 'operator': amount * 1000 // 10000,
                          'direct': amount * 1500 // 10000}
                shares['platform'] = amount - sum(shares.values())
                for owner, value in shares.items():
                    self.balances[owner] += value
            elif action == 'pay':
                if recipient not in ('provider',):
                    raise Rejected('unknown provider')
                self.balances['user'] -= amount
                self.balances[recipient] += amount
            elif action == 'withdraw':
                self.balances['user'] -= amount; self.c -= amount; self.external += amount
            elif action == 'redeposit':
                self.external -= amount; self.c += amount; self.balances['user'] += amount
            elif action in ('redeem_provider', 'redeem_platform', 'refund_advertiser'):
                owner = {'redeem_provider': 'provider', 'redeem_platform': 'platform',
                         'refund_advertiser': 'advertiser'}[action]
                self.balances[owner] -= amount
                self.r -= amount; self.s -= amount; self.c -= amount
            elif action == 'redeem_external':
                self.external -= amount; self.r -= amount; self.s -= amount
            else:
                raise Rejected('unsupported action, including arbitrary mint/reserve spend')
            try:
                self.invariant()
            except AssertionError:
                raise Rejected('insufficient funds or conservation failure') from None
            self.posted[key] = payload
            return 'applied'
        except Exception:
            self.__dict__ = before
            raise


def run():
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)

    spec = json.loads(SPEC.read_text())
    check('design mode cannot enable real value', spec['status'] == 'design_only' and not spec['real_value_enabled'])
    check('initial supply zero', spec['reference_choices']['initial_supply_atoms'] == '0')
    check('policy count and unique IDs', len(set(spec['policy_ids'])) == 24)
    check('all policies trace to planned acceptance checks', set(spec['policy_ids']) == {
        p for scenario in spec['acceptance_checks'] for p in scenario['policy_ids']})
    check('invariant count and unique IDs', len(set(spec['invariant_ids'])) == 6)
    check('43 planned checks remain unimplemented/unverified', len(spec['acceptance_checks']) == 43 and all(
        c['status'] == 'not_implemented_or_not_verified_for_v5' for c in spec['acceptance_checks']))
    check('split sums to 100 percent', sum(spec['default_split_bps'].values()) == 10000)
    check('base exposure has no answer/click/purchase requirement', not any(
        spec['ad_products']['P1'][k] for k in ('answer_required', 'click_required', 'purchase_required')))
    check('policy version does not create duplicate token identity', spec['policy_version_is_separate_from_asset_identity'])

    documents = [ROOT / 'docs' / name for name in (
        'AD_COIN_POLICY.md', 'AD_COIN_ARCHITECTURE.md', 'AD_COIN_V5_IMPLEMENTATION_PLAN.md',
        'AD_COIN.md', 'AD_COIN_SALES_POLICY.md', 'AD_COIN_TARGETS.md')]
    for path in documents:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if not target.startswith(('https:', 'http:', '#', 'mailto:')):
                check('local link exists: ' + str(path.relative_to(ROOT)) + ':' + target,
                      (path.parent / target.split('#')[0]).exists())
    policy = documents[0].read_text()
    for pid in spec['policy_ids']:
        check('policy trace ' + pid, pid in policy)
    plan = documents[2].read_text()
    for scenario in spec['acceptance_checks']:
        check('planned scenario trace ' + scenario['id'], scenario['id'] + ':' in plan)

    m = Model()
    m.apply('deposit', 1000 * ATOM, 'deposit-1')
    m.apply('reward', 100 * ATOM, 'exposure-1')
    check('reward preserves reserve and supply', (m.r, m.s, m.c) == (1000 * ATOM,) * 3)
    check('reward allocation exact', [m.balances[k] for k in KEYS] == [900*ATOM,50*ATOM,0,10*ATOM,15*ATOM,25*ATOM])
    before = m.snapshot()
    check('replay returns original status', m.apply('reward', 100 * ATOM, 'exposure-1') == 'already_done')
    check('replay preserves all balances', before == m.snapshot())
    rejected_cases = [
        ('reward', 101 * ATOM, 'exposure-1', {}),
        ('mint', ATOM, 'unbacked-mint', {}),
        ('reserve_spend', ATOM, 'operating-cost', {}),
        ('pay', 51 * ATOM, 'overspend', {}),
        ('deposit', ATOM, 'fake-collateral', {'asset': 'FAKE_USDC'}),
        ('withdraw', 51 * ATOM, 'over-withdraw', {}),
        ('refund_advertiser', 901 * ATOM, 'double-refund', {}),
        ('reward', 1, 'zero-reward', {}),
        ('deposit', -1, 'negative', {}),
        ('deposit', True, 'boolean', {}),
        ('deposit', 1.5, 'float', {}),
    ]
    for action, amount, key, options in rejected_cases:
        before = m.snapshot()
        try:
            m.apply(action, amount, key, **options)
            raise AssertionError('expected rejection: ' + key)
        except Rejected:
            check('rejected request preserves state: ' + key, m.snapshot() == before)
    m.apply('pay', 20 * ATOM, 'work-1')
    m.apply('redeem_provider', 20 * ATOM, 'provider-redeem-1')
    m.apply('withdraw', 10 * ATOM, 'withdraw-1')
    check('withdraw changes custody only', (m.r,m.s,m.c,sum(m.balances.values()),m.external) ==
          (980*ATOM,980*ATOM,970*ATOM,970*ATOM,10*ATOM))
    m.apply('redeem_external', 10 * ATOM, 'external-redeem-1')
    check('example ends at 970 across R/S/C/B', (m.r,m.s,m.c,sum(m.balances.values())) == (970*ATOM,)*4)
    m.apply('refund_advertiser', 900 * ATOM, 'unspent-refund-1')
    m.apply('redeem_platform', 25 * ATOM, 'platform-revenue-1')
    check('unspent refund and platform revenue remain fully backed', m.r == m.s == m.c == 45 * ATOM)

    # Check one-sided integer rounding and the revised task sponsorship floor.
    rounding_cases = 0
    for user_bps in (4000, 5000, 6000, 10000):
        for task in (1, 3, 17, 999, 1000001, 10**12):
            charge = (task * 10000 + user_bps - 1) // user_bps
            assert charge * user_bps // 10000 >= task
            if charge > 0:
                assert (charge - 1) * user_bps // 10000 < task
            rounding_cases += 1
    check('sponsorship floor covers each task without underpayment', rounding_cases == 24)

    rng = random.Random(20261106)
    random_model = Model()
    random_stats = {'attempts': 12000, 'applied': 0, 'rejected_without_state_change': 0}
    actions = ('deposit','reward','pay','withdraw','redeposit','redeem_provider','redeem_platform',
               'refund_advertiser','redeem_external')
    for i in range(random_stats['attempts']):
        action = rng.choice(actions)
        amount = rng.randrange(1, 250 * ATOM)
        before = random_model.snapshot()
        try:
            random_model.apply(action, amount, 'random-' + str(i))
            random_stats['applied'] += 1
        except Rejected:
            assert before == random_model.snapshot()
            random_stats['rejected_without_state_change'] += 1
        random_model.invariant()
    check('all random attempts preserve accounting invariants',
          sum(v for k,v in random_stats.items() if k != 'attempts') == random_stats['attempts'])

    baseline = json.loads((ROOT/'reports/ad-coin-doc-refresh-2026-11-06/verification.json').read_text())
    changed = [f for f, digest in baseline['source_sha256'].items()
               if hashlib.sha256((ROOT/f).read_bytes()).hexdigest() != digest]
    check('existing product/test/script sources unchanged from v4', not changed)
    report = {'profile':'ai-ad-coin-v5-design-validation','date_kst':'2026-11-06','passed':True,
              'checks_count':len(checks),'checks':checks,'rounding_cases':rounding_cases,
              'random_accounting_sequences':random_stats,'final_example_atoms':{'R':str(m.r),'S':str(m.s),'C':str(m.c),'B':str(sum(m.balances.values()))},
              'source_diff_from_v4':changed,
              'scope':'Local documentation trace and simplified integer accounting model only. No contract, chain finality, human identity, API security, real reserve, legal or merchant verification.',
              'planned_v5_acceptance_checks_passed':0,
              'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [SPEC,*documents,Path(__file__)]}}
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','checks_count','rounding_cases','random_accounting_sequences','planned_v5_acceptance_checks_passed']},ensure_ascii=False))


if __name__ == '__main__':
    run()
