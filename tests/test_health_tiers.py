"""11-14 사용자 결정 "등급별로 변경": health intervals by grade, necklace members every 15 minutes, bulk hosts sampled."""
import json

import pytest

from agent_market.collector import health as H
from scripts import health_tiers as T

DAY = 86400


@pytest.fixture
def checker(tmp_path, monkeypatch):
    tiers = tmp_path / 'tiers.json'
    members = tmp_path / 'members.json'
    tiers.write_text(json.dumps({'bulk_hosts': {'bulk.example.com': {'active': 200000, 'grade_a': 0}}}))
    members.write_text(json.dumps({'resource_ids': [77]}))
    monkeypatch.setattr(H, 'TIERS_FILE', str(tiers))
    monkeypatch.setattr(H, 'MEMBERS_FILE', str(members))
    return H.HealthChecker(store=None, per_host_delay=0.0)


def delay(checker, resource, host_size=1, failures=0, in_use=False):
    return checker.next_check_at(failures, in_use, 0.0, host_size, resource) / (1 + 0)


def test_grade_a_and_mcp_every_twelve_hours(checker):
    twelve = 12 * 3600
    assert checker.schedule.core_interval == twelve
    for r in ({'eval_grade': 'A', 'kind': 'a2a', 'host': 'x.com'}, {'eval_grade': 'B', 'kind': 'mcp', 'host': 'y.com'}):
        assert abs(delay(checker, r) - twelve) <= twelve * checker.schedule.jitter
    # the pearl rule needs 3+ health checks in 7 days: at 12 hours with +10% jitter that is at least 12 a week
    worst = twelve * (1 + checker.schedule.jitter)
    assert int(7 * DAY // worst) >= 3


def test_down_agents_keep_the_default_interval(checker):
    down = delay(checker, {'eval_grade': 'A', 'kind': 'mcp', 'host': 'x.com'}, failures=checker.schedule.down_after)
    assert abs(down - checker.schedule.interval) <= checker.schedule.interval * checker.schedule.jitter


def test_other_healthy_is_daily_and_bulk_is_sampled(checker):
    other = delay(checker, {'eval_grade': 'B', 'kind': 'a2a', 'host': 'z.com'})
    assert abs(other - DAY) <= DAY * 0.1
    bulk = [delay(checker, {'eval_grade': None, 'kind': 'a2a', 'host': 'bulk.example.com'}, host_size=200000) for _ in range(400)]
    weekly = [d for d in bulk if d > 3 * DAY]
    assert len(weekly) >= 390 and all(d >= 0.9 * 7 * DAY for d in weekly)       # ~100/200000 sampled daily


def test_failures_and_members_unchanged_or_fast(checker):
    assert delay(checker, {'eval_grade': 'B', 'kind': 'a2a', 'host': 'z.com'}, in_use=True) <= 900 * 1.1
    assert checker.necklace_members() == {77}
    assert delay(checker, {'kind': 'a2a', 'host': 'z.com'}, failures=1) <= 900 * 1.1       # failing: 15 minutes as before


def test_tiers_document():
    rows = [('a.com', 5000, 0), ('b.com', 5000, 3), ('c.com', 10, 0)]
    doc = T.compute(rows, {'a.com': (100, 100)})
    assert list(doc['bulk_hosts']) == ['a.com'] and doc['suspect'] == ['a.com']           # b has grade A: normal rules
    assert T.compute(rows, {'a.com': (100, 99)})['suspect'] == []



def test_necklace_members_every_fifteen_minutes_even_when_down(checker):
    """운영·SRE 11-14 review: a down member must not wait 12 hours (the watch needs 6 healthy hours to restore)."""
    member = {'id': 77, 'eval_grade': 'A', 'kind': 'mcp', 'host': 'x.com'}
    down_after = checker.schedule.down_after
    assert checker.next_check_at(down_after, False, 0.0, 1, member, member=True) <= 900 * 1.1
    # a customer's in-use agent keeps the old order (down -> the down interval)
    assert checker.next_check_at(down_after, True, 0.0, 1, member) > 3 * 3600



def test_down_follows_the_grade_rules(checker):
    after = checker.schedule.down_after
    six, day = checker.schedule.interval, checker.schedule.other_interval
    assert abs(checker.next_check_at(after, False, 0.0, 1, {'eval_grade': 'A', 'kind': 'a2a', 'host': 'a.com'}) - six) <= six * 0.1
    assert abs(checker.next_check_at(after, False, 0.0, 1, {'eval_grade': 'B', 'kind': 'mcp', 'host': 'm.com'}) - day) <= day * 0.1
    bulk = [checker.next_check_at(after, False, 0.0, 200000, {'kind': 'x402', 'host': 'bulk.example.com'}) for _ in range(200)]
    assert sum(d > 3 * DAY for d in bulk) >= 190                              # bulk: weekly unless sampled


def test_retire_still_happens_with_daily_checks(checker):
    """The retire rule needs 3+ failures and 7 days since failing_since; daily checks reach it by day 8."""
    s = checker.schedule
    resource = {'eval_grade': 'B', 'kind': 'a2a', 'host': 'z.com'}
    now, failures, failing_since = 0.0, 0, None
    while True:
        failures += 1
        failing_since = now if failing_since is None else failing_since
        if failures >= s.down_after and now - failing_since >= s.retire_after:
            break
        now = checker.next_check_at(failures, False, now, 1, resource)
        assert now < 30 * DAY
    assert now - failing_since <= s.retire_after + s.other_interval * 1.1     # retired within about 8 days
