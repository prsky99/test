"""Source review 11-16, the fixes that change no verdict: the ledger gives back a call that never left us, a gate
check never overwrites another, and a retest keeps the lines of the cases it ran when a later case raises."""
import json

import pytest

from agent_market import provider_budget as pb
from agent_market.necklaces import retest, runner
from tests.test_necklaces_retest import no_real_standing, package_defn, pkg_case  # noqa: F401 - fixture
from tests.test_necklaces_runner import Fail, caller_from


def test_release_gives_back_only_what_the_system_took(tmp_path):
    url = "https://example.org/mcp"
    for _ in range(3):
        assert pb.reserve(url, "gate", directory=tmp_path)[0]
    assert pb.reserve(url, "necklace_retest", directory=tmp_path)[0]
    assert pb.release(url, "gate", 1, directory=tmp_path) == 1
    assert pb.release(url, "gate", 5, directory=tmp_path) == 2          # never more than gate took
    assert pb.release(url, "adhoc", 1, directory=tmp_path) == 0
    assert pb.release("https://never.example/x", "gate", 1, directory=tmp_path) == 0
    data = json.loads((tmp_path / f"{pb.today()}.json").read_text())["domains"]["example.org"]
    assert data["total"] == 1 and data["by"] == {"gate": 0, "necklace_retest": 1} and data["released"] == 3


class Budget:
    def __init__(self):
        self.released = []

    def reserve(self, url, system):
        return True, "ok"

    def note(self, *a, **k):
        return False

    def today(self):
        return "2026-11-16"

    def release(self, url, system, n=1, day=None):
        self.released.append((system, n, day))
        return n


@pytest.mark.parametrize("code,given_back", [("relay_throttled", True), ("our_capacity", True), ("capacity", True),
                                             ("timeout", False), ("UPSTREAM_TOOL_ERROR", False),
                                             ("PROVIDER_429", False)])
def test_a_call_that_never_left_us_is_given_back(code, given_back):
    budget = Budget()
    call = runner.budgeted_caller(caller_from({7: Fail(code)}), "gate", lambda m: "https://example.org/mcp", budget)
    with pytest.raises(Fail):
        call({"kind": "external", "resource_id": 7, "tool": "t"}, {}, 5)
    assert budget.released == ([("gate", 1, "2026-11-16")] if given_back else [])


def test_a_gate_check_never_overwrites_another(tmp_path):
    from scripts import necklace_gate
    first = necklace_gate.write_check(tmp_path, "topic", 1, {"ok": True}, stamp="20261116-1500")
    second = necklace_gate.write_check(tmp_path, "topic", 1, {"ok": False}, stamp="20261116-1500")
    assert first != second and json.loads(first.read_text())["ok"] is True
    assert json.loads(second.read_text())["ok"] is False and second.name.endswith("-2.json")


def test_a_retest_keeps_the_lines_of_cases_already_run(tmp_path, monkeypatch):
    defn = package_defn()
    cases = [pkg_case("c1", ["CVE-2021-23337"]), pkg_case("c2", [])]
    answers = {367249: "CVE-2021-23337", 286623: "CVE-2021-23337", 130453: "CVE-2021-23337", 47161: "nothing",
               "package-registry": {"latest_version": "4.17.21"}}
    real = retest.grade
    seen = []

    def grade(defn, case, output):
        seen.append(case["case_id"])
        if case["case_id"] == "c2":
            raise RuntimeError("a grader bug on the second case")
        return real(defn, case, output)
    monkeypatch.setattr(retest, "grade", grade)
    with pytest.raises(RuntimeError):
        retest.run_set(defn, cases, caller_from(answers), root=tmp_path, now=lambda: 1_800_000_000)
    lines = [json.loads(l) for l in (tmp_path / "retest" / "20270115.jsonl").read_text().splitlines()]
    assert [l["case_id"] for l in lines if l["type"] == "case"] == ["c1"]
    assert (tmp_path / "results" / "package-risk-audit" / "selftest-20270115.jsonl").exists()
