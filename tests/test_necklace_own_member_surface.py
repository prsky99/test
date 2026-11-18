"""PM 17:0x (11-18): judge and the surface reach the same answer from the same definition. The judge entry of a
fortune necklace goes into necklace_surface.offered(); runnable only when judge publishes it live with its own
members counted."""
from datetime import datetime, timezone

import pytest

from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_own_member_exception import AFTER, APPROVED, DECLARED, DURING, entry, fortune


def offered(got, now):
    return ns.offered(got, datetime.fromtimestamp(now, timezone.utc))


@pytest.mark.parametrize("name, declared, states, now, status, runnable", [
    ("two approved, two declared", DECLARED, APPROVED, DURING, "live", True),
    ("one approved, two declared", DECLARED, {"korean-lunar|calendar.lunar_convert.v1": "approved"}, DURING, "held", False),
    ("the day after the exception", DECLARED, APPROVED, AFTER, "held", False),
    ("nothing declared", None, APPROVED, DURING, "held", False),
])
def test_judge_and_surface_agree(tmp_path, name, declared, states, now, status, runnable):
    got = entry(fortune(declared=declared), tmp_path, now, states)
    assert got["status"] == status, name
    assert offered(got, now) is runnable, name
    if runnable:
        standing = sum(1 for p in got["pearls"] if p.get("standing") in ("verified_pearl", "provisional"))
        assert got["member_count"] == standing + got["own_members"]["counted"]     # the surface's sum


def test_a_judge_preview_is_runnable_on_the_surface_and_shows_no_figure(tmp_path):
    """PM 17:2x and 17:3x: tonight's website-trust preview (no measured round, no retest yet) is a preview to judge and
    must run on the surface; a held preview must not."""
    import json
    from agent_market.necklaces import judge
    from tests.test_necklace_preview import BOTH, NOW, preview_defn
    defn = preview_defn()
    got = judge.build_entry(defn, None, {}, NOW, None, verified=BOTH, preview_rows=[])
    assert got["status"] == "preview" and got["held_reason"] is None
    now = datetime.fromtimestamp(NOW, timezone.utc)
    assert ns.offered(got, now) is True
    assert [e["slug"] for e in ns.available({"necklaces": [got]}, now)] == [defn["slug"]]
    assert ns.live({"necklaces": [got]}, now) == []                       # never promoted as an answer
    view = json.dumps(ns.public_view(got))
    assert all(k not in ns.public_view(got) for k in ("quality", "cost", "completion", "comparison"))
    assert '"tests"' not in view
    held = dict(got, status="held", held_reason="stale_retest")
    assert ns.offered(held, now) is False
