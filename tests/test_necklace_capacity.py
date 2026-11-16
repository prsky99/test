"""PM 11-15 17:24: daily capacity per necklace, and live runs that move on when a provider's quota is used."""
import pytest

from agent_market.necklaces import capacity, runner


def ext(rid, domain):
    return {"kind": "external", "resource_id": rid, "tool": "t", "registrable_domain": domain, "state": "active"}


def defn(location, quakes, optional=None):
    slots = [{"slot": "location", "required": True, "chain": location}, {"slot": "quakes", "required": True, "chain": quakes}]
    if optional:
        slots.append({"slot": "extra", "required": False, "chain": optional})
    return {"slots": slots}


LIMITS = {"datakoot.com": 100, "dmvtransit.com": 1000}


def test_the_narrowest_required_step_is_the_bottleneck():
    out = capacity.capacity(defn([ext(1, "dmvtransit.com")], [ext(2, "datakoot.com")], [ext(3, "tiny.example")]),
                            published=LIMITS.get)                      # optional steps do not count
    assert (out["per_day"], out["bottleneck"]) == (80, "quakes")
    assert out["slots"]["location"]["per_day"] == 800 and "extra" not in out["slots"]
    assert out["line"].startswith("daily capacity 80 runs (bottleneck: step quakes")


def test_our_own_substitute_lifts_the_step_and_the_lead_limit_is_still_said():
    own = {"kind": "agentcon", "agent_id": "usgs-quakes", "tool": "t", "state": "active"}
    out = capacity.capacity(defn([ext(1, "dmvtransit.com")], [ext(2, "datakoot.com"), own]), published=LIMITS.get)
    assert out["slots"]["quakes"] == {"per_day": None, "why": "own substitute",
                                      "lead": {"domain": "datakoot.com", "per_day": 80}}
    assert (out["per_day"], out["bottleneck"]) == (800, "location")
    assert "quakes 80 a day on datakoot.com" in out["line"]


def test_no_published_number_counts_as_our_own_cap():
    out = capacity.capacity(defn([ext(1, "a.example")], [ext(2, "b.example"), ext(3, "c.example")]),
                            published=lambda d: None)
    assert (out["per_day"], out["bottleneck"]) == (240, "location")       # 80% of 300; quakes has two domains
    assert out["slots"]["quakes"]["per_day"] == 480 and "our own cap of 300" in out["line"]


class Ledger:
    def __init__(self, ok=True, why="ok", limited=("datakoot.com",)):
        self.ok, self.why, self.limited, self.calls = ok, why, limited, []

    def published_per_day(self, name):
        return 100 if name in self.limited else None

    def live_reserve(self, url, default_per_day=None):
        self.calls.append((url, default_per_day))
        return self.ok, self.why


def test_a_used_quota_moves_on_without_calling_and_is_not_a_failure():
    called = []
    inner = lambda member, args, timeout_s: called.append(member["registrable_domain"]) or {"ok": True}
    ledger = Ledger(ok=False, why="quota_exhausted")
    call = runner.live_quota_caller(inner, ledger)
    with pytest.raises(runner.QuotaExhausted) as raised:
        call(ext(2, "datakoot.com"), {}, 1)
    assert raised.value.error_code == "quota_exhausted" and called == []
    ledger.ok = True
    call(ext(1, "dmvtransit.com"), {}, 1)               # PM 17:32: every domain is counted, with our 300 as default
    assert called == ["dmvtransit.com"]
    assert ledger.calls == [("https://datakoot.com", 300), ("https://dmvtransit.com", 300)]
    from agent_market.necklaces import refusals, retest
    assert refusals.is_ours("quota_exhausted") and retest.not_measured({"s": [{"error_class": "quota_exhausted"}]})


def test_a_ledger_error_never_stops_the_answer():
    class Broken(Ledger):
        def live_reserve(self, url, default_per_day=None):
            raise OSError("disk")
    called = []
    call = runner.live_quota_caller(lambda m, a, t: called.append(1) or {}, Broken())
    call(ext(2, "datakoot.com"), {}, 1)
    assert called == [1]


def test_a_step_with_no_runnable_member_means_no_runs():
    out = capacity.capacity(defn([], [ext(2, "datakoot.com")]), published=LIMITS.get)
    assert out["per_day"] == 0 and out["line"].startswith("no runs: required step location")
