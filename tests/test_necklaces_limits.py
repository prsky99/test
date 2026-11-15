"""PM R21: run limits, provider-domain caps and the short result cache of public necklace runs."""
import json

import pytest

from agent_market.necklaces import limits, model, runner, service
from tests.test_necklaces_runner import caller_from, necklace


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def setup(tmp_path):
    defs = tmp_path / "defs"
    defs.mkdir(exist_ok=True)
    defn = necklace()
    defn["input_schema"] = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"],
                            "additionalProperties": False}
    (defs / "topic-brief.json").write_text(json.dumps(defn))
    return defs, {"slug": "topic-brief", "version": 1, "definition_digest": model.digest(defn)}


def test_run_limits_per_client_necklace_and_total():
    clock = Clock()
    lim = limits.RunLimiter(clock=clock, per_client=2, per_necklace=3, total=4)
    lim.admit("a", "1.1.1.1")
    lim.admit("a", "1.1.1.1")
    with pytest.raises(limits.Refused):
        lim.admit("a", "1.1.1.1")                      # client
    lim.admit("a", "2.2.2.2")
    with pytest.raises(limits.Refused):
        lim.admit("a", "3.3.3.3")                      # necklace
    lim.admit("b", "3.3.3.3")
    with pytest.raises(limits.Refused):
        lim.admit("c", "4.4.4.4")                      # total
    clock.t += 61
    lim.admit("a", "1.1.1.1")


def test_a_refused_run_calls_nobody(tmp_path):
    defs, entry = setup(tmp_path)
    calls = []
    lim = limits.RunLimiter(per_client=1)
    kwargs = dict(root=tmp_path, definitions_dir=defs, sensitive=lambda v: False, limiter=lim,
                  cache=limits.ResultCache(), domains=limits.DomainCap(),
                  caller=caller_from({1: "CVE-2020-28500", 3: "listed in CISA KEV"}, calls))
    meta = {"ip": "203.0.113.9", "ua": "x"}
    assert service.run_for_surface(None, entry, {"q": "a"}, "mcp", meta, **kwargs)["ok"]
    before = len(calls)
    out = service.run_for_surface(None, entry, {"q": "b"}, "mcp", meta, **kwargs)
    assert out["error_code"] == "rate_limited" and len(calls) == before


def test_a_provider_over_its_cap_is_skipped_and_the_next_member_answers():
    caps = limits.DomainCap(clock=Clock(), per_minute=1, per_day=100)
    calls = []
    caller = caps.wrap(caller_from({1: "CVE-2020-28500", 2: "CVE-2020-28500", 3: "listed in CISA KEV",
                                    4: "listed in CISA KEV"}, calls))
    first = runner.Runner(caller).run(necklace(), {"q": "x"})
    assert first["slots"]["papers"]["rank"] == 1
    second = runner.Runner(caller).run(necklace(), {"q": "y"})
    assert second["slots"]["papers"]["rank"] == 2 and second["ok"]
    assert [a["error_class"] for a in second["attempts"]["papers"]][0] == "provider_cap"


def test_the_day_cap_resets_on_a_new_day():
    clock = Clock(1_800_000_000.0)
    caps = limits.DomainCap(clock=clock, per_minute=100, per_day=2)
    assert caps.take("a.com") and caps.take("a.com") and not caps.take("a.com")
    clock.t += 86400
    assert caps.take("a.com")


def test_cache_serves_completed_runs_only_and_expires():
    clock = Clock()
    cache = limits.ResultCache(clock=clock, seconds=600)
    key = cache.key("s", 1, "d", {"q": "x"})
    cache.put(key, {"ok": False})
    assert cache.get(key) is None
    cache.put(key, {"ok": True, "output": 1})
    assert cache.get(key)["output"] == 1
    assert cache.get(cache.key("s", 2, "d", {"q": "x"})) is None        # another version is another answer
    clock.t += 601
    assert cache.get(key) is None
