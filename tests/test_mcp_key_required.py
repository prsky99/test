"""An MCP tool that answers "API key required" as an ordinary result is not a working call (PM 11-13 20:5x).

Twelve production MCP servers were recorded as needing no key while their trial answer, sent without isError, asked
for one (e.g. 'API Error: Status 403 (Forbidden). Response: {"message":"API Key is required"}'). The trial now fails
with the tool's own words and the existing tool-level auth survey records the key.
"""
import json
import time

import httpx

from agent_market.collector.auth_discovery import AuthDiscoverer
from tests.test_usage import WEATHER, setup

KEYED = {"content": [{"type": "text", "text": 'API Error: Status 403 (Forbidden). Response: {"message":"API Key is required"}'}]}


def test_a_key_asking_result_fails_the_trial_and_the_auth_survey_records_a_key():
    store, rid, server, prober = setup([WEATHER], tool_result=KEYED)
    prober.run_due()
    r = store.resource(rid)
    trial = json.loads(r["trial_info"])
    assert trial["ok"] is False and trial["key_required"] is True and "API Key is required" in trial["error"]
    assert r["auth_scope"] == "tool" and r["auth_checked_at"] is None
    AuthDiscoverer(store, http=httpx.Client(transport=server), allow_private=True, per_host_delay=0).run_due()
    r = store.resource(rid)
    assert r["auth_method"] == "api_key" and r["auth_observed"] == 1


def test_a_recorded_trial_that_asked_for_a_key_is_sent_to_the_auth_survey_without_calling_again():
    store, rid, server, prober = setup([WEATHER])
    prober.run_due()                                   # a normal answer: open
    r = store.resource(rid)
    assert json.loads(r["trial_info"])["ok"] is True and r["auth_scope"] != "tool"
    old = {**json.loads(r["trial_info"]), "ok": True, "at": time.time(),
           "sample_output": '{"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}'}
    with store.tx() as db:   # as recorded before this check, then the tools are surveyed again without a new trial
        db.execute("UPDATE resources SET trial_info=?, cap_checked_at=NULL WHERE id=?", (json.dumps(old), rid))
    before = len([c for c in server.calls if isinstance(c, tuple)])
    prober.run_due()
    assert len([c for c in server.calls if isinstance(c, tuple)]) == before
    assert store.resource(rid)["auth_scope"] == "tool"


def test_an_open_answer_that_merely_mentions_keys_stays_open():
    store, rid, server, prober = setup([WEATHER], tool_result={"content": [
        {"type": "text", "text": "Seoul: 18C. No account or API key required for public data."}]})
    prober.run_due()
    r = store.resource(rid)
    assert json.loads(r["trial_info"])["ok"] is True and r["auth_scope"] != "tool"
