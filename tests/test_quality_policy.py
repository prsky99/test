"""품질 정책(evaluation.apply_quality_policy): 증거 수준에 따른 등급 상한, 7일 Wilson 가용성, 보안 통제 수단."""
import json
import time

from agent_market.collector import evaluation
from agent_market.collector.evaluation import apply_quality_policy, wilson_lower
from agent_market.gateway.store import Store

DIMS = {"availability": 0.97, "definitions": 0.95, "security": 1.0, "context": 1.0, "protocol": 1.0, "provenance": 0.95}


def raw(kind="mcp", coverage="full", findings=(), **stats):
    return {"version": 5, "kind": kind, "status": "scored", "coverage": coverage, "score": 97.0, "grade": "A",
            "security": "ok", "dimensions": dict(DIMS), "stats": dict(stats), "findings": list(findings), "at": 1.0}


def row(kind="mcp", trial=None, url="https://good.example/mcp", **extra):
    return {"id": 1, "kind": kind, "url": url, "health_n_24h": 2, "health_ok_24h": 2, "probe_latency_ms": 200,
            "trial_info": json.dumps(trial) if trial is not None else None, **extra}


def test_wilson_lower_trusts_more_checks():
    assert wilson_lower(0, 0) == 0.5
    assert round(wilson_lower(2, 2), 3) == 0.667
    assert round(wilson_lower(28, 28), 3) == 0.966
    assert wilson_lower(5, 6) < wilson_lower(6, 6) < wilson_lower(28, 28)


def test_only_a_passing_functional_test_with_a_stable_week_earns_a():
    ev = apply_quality_policy(row(trial={"ok": True, "latency_ms": 300}), raw(), (28, 28))
    assert ev["grade"] == "A" and ev["evidence"]["level"] == "verified"
    assert ev["quality_policy"] == evaluation.POLICY_VERSION and ev["raw_score"] == 97.0


def test_untested_servers_are_capped_at_b():
    ev = apply_quality_policy(row(), raw(coverage="definitions"), (28, 28))
    assert ev["evidence"]["level"] == "observed" and ev["grade"] == "B" and ev["score"] <= 84.9
    assert any(f["code"] == "unverified_function" for f in ev["findings"])


def test_auth_gated_trial_is_not_a_failure_but_not_verification():
    ev = apply_quality_policy(row(trial={"ok": False, "error": "401 Unauthorized: missing API key"}), raw(), (28, 28))
    assert ev["evidence"]["level"] == "observed" and ev["grade"] == "B"


def test_failed_trial_is_capped_at_c():
    ev = apply_quality_policy(row(trial={"ok": False, "error": "500 internal error"}), raw(), (28, 28))
    assert ev["evidence"]["level"] == "failed" and ev["score"] <= 69.9 and ev["grade"] == "C"


def test_few_checks_and_an_unstable_week_cap_at_b():
    limited = apply_quality_policy(row(trial={"ok": True}), raw(), (2, 2))
    assert limited["evidence"]["level"] == "limited" and limited["grade"] == "B"
    assert any(f["code"] == "insufficient_monitoring" for f in limited["findings"])
    unstable = apply_quality_policy(row(trial={"ok": True}), raw(), (20, 18))
    assert unstable["evidence"]["level"] == "observed"
    assert any(f["code"] == "unstable_week" for f in unstable["findings"])


def test_security_rewards_controls_not_just_missing_alarms():
    good = apply_quality_policy(row(trial={"ok": True}), raw(), (28, 28))
    plain = apply_quality_policy(row(trial={"ok": True}, url="http://good.example/mcp"),
                                 raw(findings=[{"severity": "low", "code": "def_safety_annotations", "tool": None,
                                                "message": "x"}]), (28, 28))
    assert good["dimensions"]["security"] == 1.0 and plain["dimensions"]["security"] == 0.85
    assert plain["stats"]["security_base"] == 1.0


def test_policy_is_idempotent_and_keeps_quarantine_and_unscored():
    once = apply_quality_policy(row(trial={"ok": True}), raw(), (28, 28))
    assert apply_quality_policy(row(trial={"ok": True}), once, (28, 28)) is once
    q = raw()
    q["security"] = "quarantine"
    assert apply_quality_policy(row(trial={"ok": True}), q, (28, 28))["score"] <= evaluation.QUARANTINE_CAP
    static = {"status": "auth_required", "score": None, "dimensions": {"provenance": 0.8}}
    assert apply_quality_policy(row(), static) is static


def test_a2a_and_x402_use_their_own_evidence():
    signed = apply_quality_policy(row("a2a", trial={"ok": True, "latency_ms": 900}), raw("a2a", signed=True), (10, 10))
    assert signed["grade"] == "A" and signed["dimensions"]["security"] == 1.0
    unreachable = apply_quality_policy(
        row("a2a"), raw("a2a", findings=[{"severity": "high", "code": "endpoint_unreachable", "tool": None, "message": "x"}]),
        (10, 10))
    assert unreachable["evidence"]["level"] == "failed"
    paid = apply_quality_policy(row("x402", health_status="healthy"), raw("x402", verified=True), (10, 10))
    assert paid["evidence"]["level"] == "verified" and paid["grade"] == "A"
    unpaid = apply_quality_policy(row("x402", health_status="healthy"), raw("x402", verified=False), (10, 10))
    assert unpaid["grade"] == "B"


def add_resource(store, key, kind, ev, trial=None):
    store.upsert_resource({"key": key, "source": "test", "kind": kind, "url": f"https://{key}.example/x", "name": key,
                           "description": "Returns weather for a city.", "category": "weather", "networks": [],
                           "price_usdc": 0, "details": {}})
    rid = store.query("SELECT id FROM resources WHERE key=?", (key,))[0]["id"]
    with store.tx() as db:
        db.execute("UPDATE resources SET eval_score=?, eval_grade=?, eval_info=?, trial_info=?, health_n_24h=2, "
                   "health_ok_24h=2 WHERE id=?", (ev["score"], ev["grade"], json.dumps(ev), json.dumps(trial), rid))
        for i in range(10):
            db.execute("INSERT INTO health_checks VALUES (?,?,?,?,?,?,?)", (rid, time.time() - i * 3600, "healthy", 200,
                                                                         150, None, None))
    return rid


def test_store_batch_applies_policy_once_and_finishes():
    store = Store()
    verified = add_resource(store, "a", "mcp", raw(), {"ok": True, "latency_ms": 200})
    untested = add_resource(store, "b", "mcp", raw(coverage="definitions"))
    assert store.health_counts([verified], time.time() - 86400 * 7) == {verified: (10, 10)}
    assert store.quality_policy_batch(limit=1) == 1
    assert store.quality_policy_batch(limit=10) == 1
    assert store.quality_policy_batch(limit=10) == 0
    assert store.get_meta("quality_policy_done") == evaluation.POLICY_VERSION
    assert store.quality_policy_batch(limit=10) == 0
    assert store.resource(verified)["eval_grade"] == "A"
    b = store.resource(untested)
    assert b["eval_grade"] == "B" and json.loads(b["eval_info"])["evidence"]["level"] == "observed"


def test_trial_outcomes_separate_server_faults_from_inconclusive_measurements():
    out = evaluation.trial_outcome
    assert out(None) is None and out({"ok": True}) == "pass"
    assert out({"ok": False, "error": '{"x402Version":1,"error":"Payment required to access this tool"}'}) == "gated"
    assert out({"ok": False, "error": "API 키가 필요합니다."}) == "gated"
    assert out({"ok": False, "error": "ReadTimeout: The read operation timed out"}) == "failed"
    assert out({"ok": False, "error": "no result (HTTP 502)"}) == "failed"
    assert out({"ok": False, "error": "Invalid tool execution protocol response."}) == "inconclusive"
    assert out({"ok": False, "error": "Provide exactly one of tool_name or topic"}) == "inconclusive"
    ev = apply_quality_policy(row(trial={"ok": False, "error": "Dataset 12 not found."}), raw(), (28, 28))
    assert ev["evidence"]["level"] == "observed" and ev["evidence"]["trial"] == "inconclusive"


def test_capped_scores_keep_their_order():
    high = apply_quality_policy(row(), raw(coverage="definitions"), (28, 28))
    lower = raw(coverage="definitions")
    lower["dimensions"] = {**DIMS, "definitions": 0.6}
    low = apply_quality_policy(row(), lower, (28, 28))
    assert 74.9 < low["score"] < high["score"] <= 84.9 and high["grade"] == low["grade"] == "B"


def test_postgres_health_counts_binds_at_most_256_values_per_statement():
    from agent_market.application_store_collector import PostgresCollectorMixin

    class Fake(PostgresCollectorMixin):
        def __init__(self):
            self.calls = []

        def _collector_rows(self, sql, params=()):
            assert len(params) <= 256
            self.calls.append(params)
            return [{"resource_id": i, "n": 3, "ok": 3} for i in params[1:]]

    fake = Fake()
    counts = fake.health_counts(list(range(1, 1001)), 0.0)
    assert len(counts) == 1000 and len(fake.calls) == 5
