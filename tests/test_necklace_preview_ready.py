"""Which definitions can take the connection gate (user decision 11-18 via PM 19:4x): a table without calls."""

from agent_market.necklaces import preview_ready as pr
from tests.test_necklace_connect_gate import FRESH, STATES, VERIFIED, defn3
from tests.test_necklaces_model import base



def check(defn, **kw):
    args = dict(states=STATES, watch_state=FRESH, watch_problem=None, verified=VERIFIED)
    args.update(kw)
    return pr.check(defn, **args)


def test_a_three_role_definition_with_pearls_and_outside_fallbacks_is_ready():
    got = check(defn3())
    assert got["ready"] and got["blocked"] == [] and len(got["roles"]) == 3


def test_two_roles_missing_members_terms_and_watch_are_named():
    assert "roles 2 < 3" in check(base())["blocked"]
    no_fallback = defn3()
    no_fallback["slots"][2]["chain"] = no_fallback["slots"][2]["chain"][:1] + no_fallback["slots"][2]["chain"][2:]
    assert check(no_fallback)["blocked"] == ["members:extra: no outside fallback member"]
    own_step = defn3()
    own_step["slots"][2]["own_fallback"] = True
    assert check(own_step, states={"owned|x.v1": "approved"})["blocked"] == [
        "members:extra: own_fallback step without a substitute that passed its gate"]
    defn = defn3()
    defn["slots"][0]["chain"][0]["terms"]["status"] = "prohibits"
    assert check(defn)["blocked"] == ["members:papers: no representative pearl"]     # dropped from the running chain
    assert check(defn3(), watch_problem="watch_state_stale")["blocked"] == ["watch: watch_state_stale"]


def test_the_table_shows_the_connection_gate_state():
    rows = [check(defn3(), connect={"passed_at": "2026-11-19T01:00:00Z", "hold": None}),
            check(defn3(), connect={"passed_at": None, "hold": "connect_not_passed"}), check(base())]
    text = pr.table(rows)
    assert "passed 2026-11-19T01:00:00Z" in text and "not passed (connect_not_passed)" in text and "roles 2 < 3" in text
