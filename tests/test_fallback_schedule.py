"""jobs steps for the fallback agents: the hourly watch and the daily airport index (PM 11-14)."""
from datetime import datetime

from agent_market.fallback_schedule import AirportIndexRefresh, FallbackWatchStep, OfacIndexRefresh, airport_window


class Watch:
    def __init__(self, due=True, fail=False):
        self.is_due, self.fail, self.runs = due, fail, 0

    def due(self):
        return self.is_due

    def run(self):
        self.runs += 1
        if self.fail:
            raise OSError('disk')
        return {'alerts': [], 'open_problems': 0, 'failing': []}


def test_watch_step_runs_only_when_due_and_never_raises():
    idle = Watch(due=False)
    assert FallbackWatchStep(idle).run_due() is None and idle.runs == 0
    ok = Watch()
    assert FallbackWatchStep(ok).run_due() == {'fallback_watch': {'alerts': [], 'open_problems': 0, 'failing': []}}
    assert FallbackWatchStep(Watch(fail=True)).run_due() == {'fallback_watch': 'failed'}


def test_airport_refresh_once_a_day_in_its_window_and_not_without_an_index(tmp_path):
    at = lambda h, m: datetime(2026, 11, 14, h, m).timestamp()
    assert airport_window(at(7, 20)) and not airport_window(at(7, 5)) and not airport_window(at(4, 30))
    calls = []
    clock = [at(7, 5)]
    step = AirportIndexRefresh(clock=lambda: clock[0], sync=lambda: calls.append(1) or {'airports': 1})
    assert step.run_due() is None                       # :05 is the measurement window
    clock[0] = at(7, 20)
    assert step.run_due() == {'airport_index': 'started'}
    step.thread.join(5)
    assert calls == [1] and step.last['ok']
    assert step.run_due() is None                       # once a day
    missing = AirportIndexRefresh(clock=lambda: at(7, 20), path=tmp_path / 'airports.json')
    assert missing.run_due() == {'airport_index': 'no_index'} and missing.thread is None



def test_ofac_index_refresh_is_scheduled_daily_and_waits_for_a_first_index(tmp_path):
    """ops 11-17: the jobs scheduler holds OfacIndexRefresh; it runs once a day in the airport window and does nothing
    before the first index exists."""
    from pathlib import Path
    at = lambda h, m: datetime(2026, 11, 14, h, m).timestamp()
    src = Path(__file__).resolve().parents[1].joinpath("agent_market/gateway/server.py").read_text()
    assert "OfacIndexRefresh()" in src
    calls = []
    step = OfacIndexRefresh(clock=lambda: at(7, 20), sync=lambda: calls.append(1) or {"entities": 1})
    assert step.run_due() == {"ofac_index": "started"}
    step.thread.join(5)
    assert calls == [1] and step.last["ok"] is True and step.run_due() is None          # once a day
    missing = OfacIndexRefresh(clock=lambda: at(7, 20), path=tmp_path / "ofac-sdn.json")
    assert missing.run_due() == {"ofac_index": "no_index"}


def test_ofac_host_is_capped_by_its_limiter_inside_the_ledger_total():
    """OFAC publishes no rate limit, so the ledger keeps its default total (DOMAIN_TOTAL needs a checked published
    limit); the fallback limiter is the tighter cap: six calls a day (SDN + ALT, refreshes and a first sync)."""
    from agent_market.fallback_agents.limits import limiters
    from agent_market.provider_budget import domain, domain_total
    host = limiters()["sanctionslistservice.ofac.treas.gov"]
    assert host.count == 6 and host.window == 86400.0
    assert domain_total(domain("https://sanctionslistservice.ofac.treas.gov/x")) >= 6


def test_ofac_refresh_reserves_in_the_ledger_and_fails_quietly(tmp_path):
    """ops 11-17: the daily sync runs under the ledger share fallback_watch (net.get reserves each download); a
    refusal or an error is recorded in .last and logged, never raised, and the old index file is left as it was."""
    from agent_market.fallback_agents import net
    from agent_market.fallback_agents.limits import SourceBusy
    seen = []
    ok = OfacIndexRefresh(sync=lambda: seen.append(net._BUDGET_SYSTEM.get()) or {"entities": 1})
    ok._work()
    assert seen == ["fallback_watch"] and ok.last["ok"] is True and net._BUDGET_SYSTEM.get() is None
    index = tmp_path / "ofac-sdn.json"
    index.write_text("old")

    def refused():
        raise SourceBusy("Shared test budget refused the call (share).")
    failing = OfacIndexRefresh(sync=refused, path=index)
    failing._work()
    assert failing.last == {"ok": False, "error": "SourceBusy"} and index.read_text() == "old"
