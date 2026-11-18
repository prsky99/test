"""PM 16:55 and 17:0x (11-18, final): daily-fortune-brief and personality-fortune-brief count their approved
substitutes as members until 2026-12-18 (Asia/Seoul), one per role. The definition declares own_members {label,
counted, until} (the surface reads the same field); judge counts the approved substitutes itself and holds when the
declaration says more; the exception ends by itself and never reaches another necklace."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_market.necklaces import judge, model
from tests.test_necklaces_judge import BOTH, approval, summary
from tests.test_necklaces_model import base, own

KST = ZoneInfo("Asia/Seoul")
DURING = datetime(2026, 11, 20, 12, tzinfo=KST).timestamp()
LAST_DAY = datetime(2026, 12, 18, 23, 59, tzinfo=KST).timestamp()
AFTER = datetime(2026, 12, 19, 0, 0, tzinfo=KST).timestamp()
DECLARED = {"label": "Built with AgentValCon agents", "counted": 2, "until": "2026-12-18"}


def fortune(slug="daily-fortune-brief", declared=DECLARED):
    defn = base()
    defn["slug"], defn["status"] = slug, "live"
    defn["slots"] = [
        {"slot": "calendar", "contract": "calendar.lunar_convert.v1", "required": True, "fanout": 1,
         "chain": [own("avc:korean-lunar", agent_id="korean-lunar")]},
        {"slot": "western", "contract": "astro.western_sign.v1", "required": True, "fanout": 1,
         "chain": [own("avc:western-sign", agent_id="western-sign")]},
        {"slot": "synthesis", "contract": "fortune.daily.v1", "required": True, "fanout": 1,
         "chain": [own("avc:fortune-daily", agent_id="fortune-daily")]},
    ]
    if declared is not None:
        defn["own_members"] = dict(declared)
    return defn


APPROVED = {"korean-lunar|calendar.lunar_convert.v1": "approved", "western-sign|astro.western_sign.v1": "approved",
            "fortune-daily|fortune.daily.v1": "provisional"}


def entry(defn, tmp_path, now, states=APPROVED):
    summary(tmp_path, defn["slug"], quality={"delta_pp": 5, "tested_at": judge._iso(now - 3600)})
    return judge.build_entry(defn, approval(defn), judge.load_summary(tmp_path, defn["slug"]), now,
                             verified=BOTH, substitute_states=states)


def test_approved_substitutes_count_one_per_role_until_the_last_day(tmp_path):
    for now in (DURING, LAST_DAY):
        got = entry(fortune(), tmp_path / str(int(now)), now)
        assert got["own_members"] == {"counted": 2, "roles": ["calendar.lunar_convert.v1", "astro.western_sign.v1"],
                                      "until": "2026-12-18", "label": "Built with AgentValCon agents"}
        assert got["member_count"] == 2 and got["pearl_count"] == 0        # never a pearl
        assert got["held_reason"] is None and got["status"] == "live"


def test_a_declared_count_above_the_approved_roles_holds_the_necklace(tmp_path):
    """PM 17:0x: the definition's counted is only a declaration; judge never uses it above its own count."""
    got = entry(fortune(declared=dict(DECLARED, counted=3)), tmp_path / "three", DURING)
    assert got["status"] == "held" and got["held_reason"] == "own_members_unapproved" and "own_members" not in got
    only_one = {"korean-lunar|calendar.lunar_convert.v1": "approved", "western-sign|astro.western_sign.v1": "provisional"}
    got = entry(fortune(), tmp_path / "one", DURING, only_one)                # provisional does not count
    assert got["held_reason"] == "own_members_unapproved"
    defn = fortune(declared=dict(DECLARED, counted=1))
    defn["slots"][1]["contract"] = "calendar.lunar_convert.v1"              # the same role twice counts once
    states = {"korean-lunar|calendar.lunar_convert.v1": "approved", "western-sign|calendar.lunar_convert.v1": "approved"}
    assert judge.approved_own_roles(defn, states) == ["calendar.lunar_convert.v1"]
    assert entry(fortune(declared=dict(DECLARED, counted=1)), tmp_path / "decl1", DURING)["own_members"]["counted"] == 1


def test_the_exception_ends_by_itself_and_never_reaches_other_necklaces(tmp_path):
    after = entry(fortune(), tmp_path / "after", AFTER)
    assert "own_members" not in after and after["held_reason"] == "members_unqualified"
    other = entry(fortune("topic-evidence-brief"), tmp_path / "other", DURING)      # declares it, not on the list
    assert "own_members" not in other and other["held_reason"] == "members_unqualified"
    undeclared = entry(fortune(declared=None), tmp_path / "none", DURING)
    assert "own_members" not in undeclared and undeclared["held_reason"] == "members_unqualified"
    late = entry(fortune(declared=dict(DECLARED, until="2027-01-31")), tmp_path / "late", DURING)
    assert late["held_reason"] == "own_members_invalid"
    label = entry(fortune(declared=dict(DECLARED, label="Verified pearls")), tmp_path / "label", DURING)
    assert label["held_reason"] == "own_members_invalid"


def test_the_declaration_is_outside_the_digest_and_the_snapshot_reads_approvals(tmp_path):
    a, b = fortune(), fortune(declared=dict(DECLARED, counted=1))
    assert model.digest(a) == model.digest(b) == model.digest(fortune(declared=None))
    defn = fortune()
    summary(tmp_path, defn["slug"], quality={"delta_pp": 5, "tested_at": judge._iso(DURING - 3600)})
    subs = [{"agent_id": k.split("|")[0], "slot_role": k.split("|")[1], "state": v, "at": "2026-11-19T00:00:00Z"}
            for k, v in APPROVED.items()]
    (tmp_path / "approvals.json").write_text(json.dumps({"approvals": [approval(defn)], "substitutes": subs}))
    snap = judge.snapshot([defn], judge.load_approvals(tmp_path / "approvals.json"), tmp_path, DURING,
                          watch_state={"updated": judge._iso(DURING), "holds": {}}, judge_state={}, verified=BOTH)
    assert snap["necklaces"][0]["own_members"]["counted"] == 2
