"""R69 (precision review, PM 11-15): the collector's own read-only judgment for live trial calls."""
import json

import httpx

from agent_market.collector import a2a, trial_safety, usage
from agent_market.collector.health import USER_AGENT, HealthChecker


def tool(name, description="", read_only=None, required=(), **extra):
    ann = {} if read_only is None else {"readOnlyHint": read_only}
    return {"name": name, "description": description, "annotations": ann, "required": list(required),
            "params": {}, **extra}


def test_read_only_hint_no_longer_skips_the_deny_words():
    assert usage.is_safe_tool(tool("send_invoice", read_only=True))  # the old hole
    assert not trial_safety.is_trial_safe_tool(tool("send_invoice", read_only=True))
    assert not trial_safety.is_trial_safe_tool(tool("lookup", "Looks up a record and then deletes it", read_only=True))
    assert trial_safety.is_trial_safe_tool(tool("get_weather", "Returns the forecast", read_only=True))


def test_prefix_matches_and_new_words_are_refused():
    for name in ("checkpoint_put", "list_clear", "kv.put", "toggleFeature", "search_and_replace", "import_file",
                 "add_note", "save_draft", "store_value", "enable_flag", "disable_alerts", "generate_image",
                 "trigger_job"):
        assert not trial_safety.is_trial_safe_tool(tool(name)), name
    assert usage.is_safe_tool(tool("checkpoint_put")) and usage.is_safe_tool(tool("list_clear"))  # the old hole


def test_the_whole_description_is_read_and_words_are_whole_words():
    late = "Returns the profile. " + "x" * 300 + " Also updates the stored record."
    assert usage.is_safe_tool(tool("get_profile", late))
    assert not trial_safety.is_trial_safe_tool(tool("get_profile", late))
    # Whole words only: address, input, output, compute and important are not add, put or import.
    assert trial_safety.is_trial_safe_tool(tool("get_address", "Returns the address for an input id; "
                                                               "output is computed; important fields only"))


def test_read_only_false_destructive_and_personal_data_are_refused():
    assert not trial_safety.is_trial_safe_tool(tool("get_item", read_only=False))
    assert not trial_safety.is_trial_safe_tool(tool("get_item", annotations={"destructiveHint": True}))
    assert not trial_safety.is_trial_safe_tool(tool("get_user", required=["email"]))


def test_pick_trial_uses_the_trial_judgment():
    tools = [tool("list_clear", read_only=True), tool("get_status", "Returns the service status")]
    picked = trial_safety.pick_trial(tools)
    assert picked and picked[0]["name"] == "get_status"
    assert usage.pick_trial(tools)[0]["name"] == "list_clear"  # the old picker took the clearing tool


def test_a2a_examples_that_create_or_change_things_are_not_asked():
    for text in ("Create a new project", "add a task", "write a poem to my drive", "update the record",
                 "start the job", "open a ticket"):
        assert a2a._ACTION.search(text), text
    assert not a2a._ACTION.search("What is the weather in Paris?")


def test_x402_health_never_sends_put_or_patch():
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(405)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    checker = HealthChecker.__new__(HealthChecker)
    for method in ("PUT", "PATCH", "DELETE"):
        result = checker._check_x402(http, {"url": "https://example.net/pay", "method": method})
        assert result.outcome == "reachable"
    assert seen == ["GET", "GET", "GET"]


def test_collector_user_agent_names_the_site_and_contact():
    from agent_market.collector import auth_discovery, capabilities
    for ua in (USER_AGENT, a2a.USER_AGENT, auth_discovery.USER_AGENT, capabilities.USER_AGENT):
        assert ua.startswith("AgentValCon-collector/1.0 (+https://agentconcierge.biz/; contact@agentconcierge.biz;")
        assert ua.isascii()


def test_trial_audit_judges_an_export_without_a_database():
    from scripts.collector_trial_audit import audit
    lines = [json.dumps(row) for row in (
        {"id": 1, "tool": "get_status", "spec": tool("get_status", "Returns the status")},
        {"id": 2, "tool": "send_invoice", "spec": tool("send_invoice", read_only=True)},
        {"id": 3, "tool": "list_clear", "spec": tool("list_clear")},
        {"id": 4, "tool": "kv_put", "spec": None},
    )]
    out = audit(lines)
    assert out["trials"] == 4 and out["spec_missing"] == 1 and out["refused_now"] == 3
    assert out["by_reason"] == {"deny_word": 1, "deny_word_new": 2}
