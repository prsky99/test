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
