import json

from agent_market.necklaces import model, service
from tests.test_necklaces_runner import Fail, caller_from, necklace


def setup(tmp_path):
    defs = tmp_path / "defs"
    defs.mkdir(parents=True, exist_ok=True)
    defn = necklace()
    defn["input_schema"] = {"type": "object", "properties": {"q": {"type": "string", "maxLength": 120}},
                            "required": ["q"], "additionalProperties": False}
    (defs / "topic-brief.json").write_text(json.dumps(defn))
    entry = {"slug": "topic-brief", "version": 1, "definition_digest": model.digest(defn)}
    return defs, entry


def call(tmp_path, args, source="mcp", meta=None, answers=None, entry=None, sensitive=lambda v: False):
    defs, default_entry = setup(tmp_path)
    return service.run_for_surface(None, entry or default_entry, args, source, meta, root=tmp_path,
                                   definitions_dir=defs, sensitive=sensitive,
                                   caller=caller_from(answers or {1: "CVE-2020-28500", 3: "kev"}))


def events(tmp_path):
    return [json.loads(line) for path in (tmp_path / "runs").glob("*.jsonl") for line in path.read_text().splitlines()]


def test_mcp_run_answers_and_records_a_body_free_event(tmp_path):
    meta = {"ip": "203.0.113.9", "ua": "Mozilla/5.0 (Macintosh) Chrome/120 Safari/537"}
    out = call(tmp_path, {"q": "lodash"}, meta=meta)
    assert out["ok"] and out["error_code"] is None and out["stages"] == {"papers": 1, "news": 1}
    [event] = events(tmp_path)
    assert event["source"] == "external" and event["surface"] == "mcp" and "lodash" not in json.dumps(event)


def test_web_run_needs_the_consent_notice(tmp_path):
    assert call(tmp_path, {"q": "x"}, source="web")["error_code"] == "consent_required"
    assert call(tmp_path, {"q": "x", "necklace_notice": "necklace-v1"}, source="web")["ok"]


def test_input_checks_and_sensitive_values_are_refused_before_any_call(tmp_path):
    assert call(tmp_path, {"q": "x", "extra": 1})["error_code"] == "invalid_input"
    assert call(tmp_path, {})["error_code"] == "invalid_input"
    assert call(tmp_path, ["q"])["error_code"] == "invalid_input"
    assert call(tmp_path, {"q": "x" * 121})["error_code"] == "invalid_input"
    assert call(tmp_path, {"q": "sk-live"}, sensitive=lambda v: True)["error_code"] == "sensitive_input"
    assert not events(tmp_path)


def test_entry_must_match_the_approved_definition(tmp_path):
    _, entry = setup(tmp_path / "x")
    assert call(tmp_path, {"q": "x"}, entry=dict(entry, definition_digest="0" * 64))["error_code"] == "definition_changed"
    assert call(tmp_path, {"q": "x"}, entry=dict(entry, slug="other"))["error_code"] == "not_found"


def test_without_request_metadata_a_run_is_never_external(tmp_path):
    call(tmp_path, {"q": "x"})
    assert events(tmp_path)[0]["source"] == "internal"


def test_failed_slot_is_reported(tmp_path):
    out = call(tmp_path, {"q": "x"}, answers={1: "CVE-2020-28500", 3: Fail(), 4: Fail(), 11: Fail()})
    assert not out["ok"] and out["error_code"] == "slot_failed:news" and out["stages"]["news"] == 4


def test_credential_values_are_refused_with_the_default_checks(tmp_path):
    defs, entry = setup(tmp_path)
    for value in ("ghp_" + "a" * 36, "sk-" + "b" * 30, "AKIA" + "C" * 16, "Bearer abc.def",
                  "0x" + "f" * 64, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"):
        out = service.run_for_surface(None, entry, {"q": value}, "mcp", None, root=tmp_path,
                                      definitions_dir=defs, caller=caller_from({1: "x", 3: "y"}))
        assert out["error_code"] == "sensitive_input", value
    ok = service.run_for_surface(None, entry, {"q": "lodash"}, "mcp", None, root=tmp_path,
                                 definitions_dir=defs, caller=caller_from({1: "CVE-2020-28500", 3: "kev"}))
    assert ok["ok"]
