import json
import time

from agent_market.necklaces import judge, model
from tests.test_necklaces_model import base

NOW = time.time()
BOTH = {(1, "x.v1"), (3, "y.v1")}      # both leads of base() are verified pearls for their slot roles


def live_defn():
    defn = base()
    defn["status"] = "live"
    return defn


def approval(defn, **kw):
    item = {"slug": defn["slug"], "version": defn["version"], "definition_digest": model.digest(defn),
            "gate_record": "logs/ops/necklace-gate/x.json", "state": "approved", "at": "2026-11-20T03:00:00Z"}
    item.update(kw)
    return item


def summary(tmp_path, slug, **kw):
    data = {"quality": {"answer_set": "a", "cases": 60, "success_rate": 0.97, "best_single_rate": 0.8,
                        "delta_pp": 17.0, "tested_at": judge._iso(NOW - 3600)},
            "completion": {"runs": 60, "completed": 59, "completed_external_only": 50}}
    data.update(kw)
    path = tmp_path / "results" / slug
    path.mkdir(parents=True)
    (path / "summary.json").write_text(json.dumps(data))


def entry(defn, appr, tmp_path):
    return judge.build_entry(defn, appr, judge.load_summary(tmp_path, defn["slug"]), NOW, verified=BOTH)


def test_live_needs_both_keys(tmp_path):
    defn = live_defn()
    summary(tmp_path, defn["slug"])
    got = entry(defn, approval(defn), tmp_path)
    assert got["status"] == "live" and got["held_reason"] is None
    assert got["gate_passed_at"] == "2026-11-20T03:00:00Z"
    assert entry(defn, None, tmp_path)["held_reason"] == "not_approved"


def test_approval_must_match_version_and_digest(tmp_path):
    defn = live_defn()
    summary(tmp_path, defn["slug"])
    assert entry(defn, approval(defn, version=2), tmp_path)["held_reason"] == "approval_mismatch"
    assert entry(defn, approval(defn, definition_digest="0" * 64), tmp_path)["held_reason"] == "approval_mismatch"


def test_revoked_or_held_approval_holds_the_necklace(tmp_path):
    defn = live_defn()
    summary(tmp_path, defn["slug"])
    assert entry(defn, approval(defn, state="revoked"), tmp_path)["status"] == "held"
    assert entry(defn, approval(defn, state="revoked"), tmp_path)["held_reason"] == "approval_revoked"
    assert entry(defn, approval(defn, state="held"), tmp_path)["held_reason"] == "gate_held"


def test_quality_holds(tmp_path):
    defn = live_defn()
    summary(tmp_path, defn["slug"], quality={"delta_pp": 0, "tested_at": judge._iso(NOW - 3600)})
    assert entry(defn, approval(defn), tmp_path)["held_reason"] == "delta_nonpositive"
    stale = tmp_path / "stale"
    summary(stale, defn["slug"], quality={"delta_pp": 5, "tested_at": judge._iso(NOW - 49 * 3600)})
    assert entry(defn, approval(defn), stale)["held_reason"] == "stale_retest"
    flagged = tmp_path / "flagged"
    summary(flagged, defn["slug"], held_reason="security")
    assert entry(defn, approval(defn), flagged)["held_reason"] == "security"


def test_candidates_are_not_published(tmp_path):
    defn = base()
    assert entry(defn, approval(defn), tmp_path) is None


def test_pearls_follow_the_surface_contract(tmp_path):
    defn = live_defn()
    defn["slots"][0]["fanout"] = 2
    defn["slots"][0]["chain"].insert(2, dict(defn["slots"][0]["chain"][0], resource_id=5, registrable_domain="e.com"))
    pearls = judge.pearls(defn)
    roles = [p["role"] for p in pearls]
    assert roles == ["papers", "papers", "news"]
    for pearl in pearls:
        kinds = [a["kind"] for a in pearl["alternates"]]
        assert kinds.count("agentcon") <= 2
        assert "external" not in kinds[kinds.index("agentcon"):] if "agentcon" in kinds else True


def test_planned_agentcon_members_are_not_listed(tmp_path):
    defn = live_defn()
    defn["slots"][0]["chain"][-1].update(resource_id=None, state="planned")
    assert all(a["kind"] == "external" for a in judge.pearls(defn)[0]["alternates"])


def test_snapshot_file_is_written_atomically_with_schema(tmp_path):
    defn = live_defn()
    summary(tmp_path, defn["slug"])
    (tmp_path / "approvals.json").write_text(json.dumps({"approvals": [
        approval(defn, at="2026-11-19T00:00:00Z", state="held"), approval(defn)]}))
    approvals = judge.load_approvals(tmp_path / "approvals.json")
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "state.json").write_text(json.dumps({"updated": judge._iso(NOW), "holds": {}}))
    payload = judge.snapshot([defn], approvals, tmp_path, now=NOW, judge_commit="abc1234", verified=BOTH)
    judge.write_atomic(tmp_path / "necklaces.json", payload)
    written = json.loads((tmp_path / "necklaces.json").read_text())
    assert written["schema"] == "agentcon-necklaces-v1"
    assert written["necklaces"][0]["status"] == "live"  # the later approval wins
    assert not list(tmp_path.glob(".necklaces-*"))


def test_unreadable_approvals_mean_no_approvals(tmp_path):
    (tmp_path / "approvals.json").write_text("{not json")
    assert judge.load_approvals(tmp_path / "approvals.json") == {}
    assert judge.load_approvals(tmp_path / "missing.json") == {}


def test_run_once_with_shipped_definitions_publishes_nothing_yet(tmp_path):
    result = judge.run_once(tmp_path)
    assert result["entries"] == {}
    assert json.loads((tmp_path / "necklaces.json").read_text())["necklaces"] == []
    members = json.loads((tmp_path / "members.json").read_text())
    assert members["schema"] == "agentcon-necklace-members-v1"
    assert {367249, 276982, 37259} <= set(members["resource_ids"])
    assert result["member_resources"] == len(members["resource_ids"])


def test_members_lists_every_chain_member_with_rank_and_skips_retired():
    defn = base()
    retired = dict(base(), slug="old-one", status="retired")
    out = judge.members([defn, retired], now=NOW)
    rows = out["members"]
    assert {r["slug"] for r in rows} == {"topic-brief"}
    papers = [r for r in rows if r["slot"] == "papers"]
    assert [r["rank"] for r in papers] == [1, 2, 3] and papers[-1]["kind"] == "agentcon"
    assert out["resource_ids"] == [1, 2, 3, 4, 10, 11]


def test_events_and_held_at_follow_status_changes():
    state = {}
    t0 = 1_800_000_000.0

    def step(status, t, reason=None):
        entry = {"slug": "s", "status": status, "held_reason": reason}
        judge.record_events([entry], state, t)
        return entry

    held_first = step("held", t0, "not_approved")
    assert state["events"] == [] and held_first["held_at"] == judge._iso(t0)  # never live: no public event
    step("live", t0 + 60)
    held = step("held", t0 + 120, "security")
    assert held["held_at"] == judge._iso(t0 + 120)
    again = step("held", t0 + 180, "security")
    assert again["held_at"] == judge._iso(t0 + 120)  # same pause keeps its start
    step("live", t0 + 240)
    assert [e["kind"] for e in state["events"]] == ["launched", "held", "resumed"]
    assert state["events"][1]["reason"] == "security"
    judge.record_events([{"slug": "s", "status": "live"}], state, t0 + 61 * 86400)
    assert state["events"] == []  # older than 60 days


def test_run_once_keeps_judge_state(tmp_path):
    judge.run_once(tmp_path)
    assert json.loads((tmp_path / "judge_state.json").read_text()) == {"status": {}, "events": [], "gate_passed": {}}
    assert json.loads((tmp_path / "necklaces.json").read_text())["events"] == []


def test_events_are_signed_when_a_key_exists(tmp_path):
    from tests.test_necklaces_evidence import make_key
    from agent_market import evidence_signing as signing
    doc = make_key(tmp_path / "signing")
    state = {}
    judge.record_events([{"slug": "s", "status": "live"}], state, 1_800_000_000, tmp_path / "signing")
    judge.record_events([{"slug": "s", "status": "held", "held_reason": "security"}], state, 1_800_000_060,
                        tmp_path / "signing")
    launched, held = state["events"]
    assert launched["signature"] is None                    # launch is covered by the signed gate result
    envelope = json.loads(open(held["signature"]["path"]).read())
    assert signing.verify(envelope, doc)["event"] == "held"


def test_snapshot_links_the_signed_gate_result(tmp_path):
    root = tmp_path / "necklaces"
    folder = tmp_path / "signing" / "envelopes" / "gate_result"
    folder.mkdir(parents=True)
    (folder / "topic-brief-v1-20261120.json").write_text("{}")
    defn = live_defn()
    payload = judge.snapshot([defn], {}, root, now=NOW)
    assert payload["necklaces"][0]["evidence"]["gate"].endswith("topic-brief-v1-20261120.json")


def test_necklaces_in_testing_are_listed_with_counts_only(tmp_path):
    trial = base()
    trial["status"], trial["template_id"] = "trial", 31
    fresh = dict(base(), slug="fresh-brief", status="qualifying")
    candidate = dict(base(), slug="idea-brief")
    summary(tmp_path, "topic-brief", quality={"cases_7d": 30, "success_7d": 28})
    summary(tmp_path, "idea-brief", quality={"cases_7d": 30, "success_7d": 30})
    state = {}
    snap = judge.snapshot([trial, fresh, candidate], {}, tmp_path, NOW, watch_state={}, judge_state=state)
    assert snap["necklaces"] == [{"slug": "topic-brief", "name": "Topic brief", "version": 1, "status": "testing",
                                  "tests": {"passed": 28, "total": 30}, "template_id": 31}]
    assert snap["events"] == [] and "topic-brief" not in state.get("status", {})


def test_testing_counts_must_be_sane():
    defn = dict(base(), status="trial")
    for quality in ({"cases_7d": 0, "success_7d": 0}, {"cases_7d": 3, "success_7d": 4}, {"cases_7d": "3", "success_7d": 1},
                    {"cases_7d": 3, "success_7d": True}, {}):
        assert judge.testing_entry(defn, {"quality": quality}) is None


def test_the_last_passed_gate_survives_hold_revoke_and_change(tmp_path):
    """PM R22: held, revoked or changed necklaces keep gate_passed_at so the surface shows the stop notice."""
    defn = live_defn()
    summary(tmp_path, "topic-brief")
    state = {}
    first = judge.snapshot([defn], {"topic-brief": approval(defn)}, tmp_path, NOW, watch_state={}, judge_state=state, verified=BOTH)
    assert first["necklaces"][0]["status"] == "live" and first["necklaces"][0]["gate_passed_at"] == "2026-11-20T03:00:00Z"
    for appr, reason in ((approval(defn, state="held"), "gate_held"), (approval(defn, state="revoked"), "approval_revoked"),
                         (approval(defn, version=2), "approval_mismatch")):
        entry = judge.snapshot([defn], {"topic-brief": appr}, tmp_path, NOW, watch_state={}, judge_state=state, verified=BOTH)["necklaces"][0]
        assert (entry["status"], entry["held_reason"], entry["gate_passed_at"]) == ("held", reason, "2026-11-20T03:00:00Z")
    never = dict(defn, slug="never-passed")
    entry = judge.snapshot([never], {}, tmp_path, NOW, watch_state={}, judge_state=state, verified=BOTH)["necklaces"][0]
    assert entry["gate_passed_at"] is None


def test_every_held_reason_has_public_wording():
    from agent_market.concierge import necklace_surface as ns
    for reason in ("not_approved", "approval_revoked", "gate_held", "approval_mismatch", "security", "fingerprint_changed",
                   "no_member", "quality_low", "stage4", "stale_retest", "delta_nonpositive", "manual", "pearls_unverified"):
        assert ns.REASONS[reason].endswith("."), reason


def test_pearls_are_counted_from_the_verify_snapshot(tmp_path):
    """PM R29: a member is a pearl only when the search team's verify snapshot says so for the slot's role."""
    snap = tmp_path / "verify.json"
    snap.write_text(json.dumps({"generated": judge._iso(NOW), "evaluator_version": "dq-test", "agents": {
        "1": {"roles": [{"role": "x.v1", "verified_pearl": True}]},
        "3": {"roles": [{"role": "other.v1", "verified_pearl": True}, {"role": "y.v1", "verified_pearl": False}]}}}))
    verified = judge.verified_pearls(snap, now=NOW, official="dq-test")
    assert verified == {(1, "x.v1"), (3, "other.v1")}
    defn = live_defn()
    summary(tmp_path, "topic-brief")
    entry = judge.snapshot([defn], {"topic-brief": approval(defn)}, tmp_path, NOW, watch_state={}, judge_state={},
                           verified=verified)["necklaces"][0]
    assert [p["pearl"] for p in entry["pearls"]] == [True, False] and entry["pearl_count"] == 1
    assert (entry["status"], entry["held_reason"]) == ("held", "pearls_unverified")
    both = verified | {(3, "y.v1")}
    entry = judge.snapshot([defn], {"topic-brief": approval(defn)}, tmp_path, NOW, watch_state={}, judge_state={},
                           verified=both)["necklaces"][0]
    assert entry["pearl_count"] == 2 and entry["status"] == "live"
    assert judge.verified_pearls(tmp_path / "missing.json") is None


def test_the_surface_offers_and_says_verified_pearl_only_from_the_judged_count(tmp_path):
    from agent_market.concierge import necklace_surface as ns
    defn = live_defn()
    summary(tmp_path, "topic-brief", quality={"cases_7d": 30, "success_rate": 0.97, "best_single_rate": 0.8,
                                              "delta_pp": 17.0, "tested_at": judge._iso(time.time() - 60)})
    snap = judge.snapshot([defn], {"topic-brief": approval(defn)}, tmp_path, time.time(), watch_state={},
                          judge_state={}, verified=BOTH)
    entry = snap["necklaces"][0]
    assert ns.offered(entry) is True
    one = dict(entry, pearls=[dict(entry["pearls"][0]), dict(entry["pearls"][1], pearl=False)], status="live")
    assert ns.offered(one) is False
    text, item = ns.details("topic-brief", snapshot=dict(snap, necklaces=[one]))
    assert "verified pearl 1" in text and "agent 3" in text
    assert [p["verified_pearl"] for p in item["pearls"]] == [True, False]


def test_snapshot_carries_example_input_and_help_for_the_surface():
    defn = live_defn()
    defn["probe_input"] = {"q": "lodash", "slot.papers.ticker": "X", "flag": True}
    defn["input_help"] = {"q": "A package name.", "other": "not a field"}
    entry = judge.build_entry(defn, approval(defn), {}, NOW, verified=BOTH)
    assert entry["example_input"] == {"q": "lodash"} and entry["input_help"] == {"q": "A package name."}
    plain = judge.build_entry(live_defn(), approval(live_defn()), {}, NOW, verified=BOTH)
    assert "example_input" not in plain and "input_help" not in plain


def test_every_entry_says_runs_are_free_for_now():
    entry = judge.build_entry(live_defn(), approval(live_defn()), {}, NOW, verified=BOTH)
    assert entry["pricing"] == {"mode": "free"}



def test_untrusted_inputs_hold_instead_of_passing(tmp_path):
    """PM 13:0x (11-15): a missing, broken or stale watch state holds every public necklace; a verify snapshot older
    than 72 hours or graded with another evaluator version counts no pearl."""
    defn = live_defn()
    summary(tmp_path, defn["slug"])
    approvals = {defn["slug"]: approval(defn)}
    entry = judge.snapshot([defn], approvals, tmp_path, NOW, judge_state={}, verified=BOTH)["necklaces"][0]
    assert (entry["status"], entry["held_reason"]) == ("held", "watch_state_missing")
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "state.json").write_text("{broken")
    assert judge.load_watch_state(tmp_path, NOW)[1] == "watch_state_missing"
    (tmp_path / "watch" / "state.json").write_text(json.dumps({"updated": judge._iso(NOW - 4 * 3600)}))
    assert judge.load_watch_state(tmp_path, NOW)[1] == "watch_state_stale"
    (tmp_path / "watch" / "state.json").write_text(json.dumps({"updated": judge._iso(NOW - 3600)}))
    entry = judge.snapshot([defn], approvals, tmp_path, NOW, judge_state={}, verified=BOTH)["necklaces"][0]
    assert entry["status"] == "live"
    snap = tmp_path / "verify.json"
    body = {"generated": judge._iso(NOW), "evaluator_version": "dq-test",
            "agents": {"1": {"roles": [{"role": "x.v1", "verified_pearl": True}]}}}
    snap.write_text(json.dumps(body))
    assert judge.verified_pearls(snap, now=NOW, official="dq-test") == {(1, "x.v1")}
    assert judge.verified_pearls(snap, now=NOW + 73 * 3600, official="dq-test") is None
    assert judge.verified_pearls(snap, now=NOW, official="dq-newer") is None
    snap.write_text(json.dumps(dict(body, evaluator_version=None)))
    assert judge.verified_pearls(snap, now=NOW, official="dq-test") is None
    snap.write_text(json.dumps(dict(body, generated="2026-11-15T10:22:09+0900")))       # the snapshot's own format
    assert judge.snapshot_problem(json.loads(snap.read_text()), judge._parse_time("2026-11-15T12:00:00+09:00"),
                                  "dq-test") is None


def test_official_evaluator_version_is_read_from_the_report_tool():
    assert judge.official_evaluator_version().startswith("dq-")
