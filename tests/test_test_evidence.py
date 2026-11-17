"""Machine-readable test evidence v1 (scripts/test_evidence.py, PM 11-16)."""
import json

from scripts import report_v2 as V
from scripts import test_evidence as E

NOW = 1_800_000_000.0


def version(tmp, rid, role, name, **kw):
    folder = tmp / "reports" / str(rid) / role
    folder.mkdir(parents=True, exist_ok=True)
    v = {"resource_id": rid, "role": role, "tool": "current_time", "arguments": {"timezone": "Asia/Seoul"},
         "outcome": "succeeded", "tested": NOW - 3600, "attempt_id": name, "source": "role tool call",
         "endpoint": "https://example.com/mcp", "tool_fingerprint": "ab" * 32, "fingerprint_version": "fingerprint-v1",
         "evaluator_version": "dq-test", "answer_set": "rag:role-tasks-rag-v1", "case_id": "time-seoul",
         "response_hash": "cd" * 32, "answer_sha256": "ef" * 32, "content_verdict": "accurate",
         "quality": {"score": 95.0}, "data_quality": {"accuracy": {"points": 30}}}
    v.update(kw)
    v = {k: x for k, x in v.items() if x is not ...}
    (folder / f"{name}.json").write_text(json.dumps(v))
    return v


def build(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "OUT", tmp_path)
    out = tmp_path / "evidence"
    return E.build(out, now=NOW), out


def test_records_match_the_shared_summary(tmp_path, monkeypatch):
    """Records of a role tool = tasks_run, correct ones = tasks_correct (one function with the verify snapshot)."""
    version(tmp_path, 7, "timezone.time.v1", "20261116-090000-a", tested=NOW - 86400)
    version(tmp_path, 7, "timezone.time.v1", "20261117-090000-b")
    version(tmp_path, 7, "timezone.time.v1", "20261117-100000-c", outcome="failed", tested=NOW - 60)
    counts, out = build(tmp_path, monkeypatch)
    data = json.loads((out / "agents" / "7.json").read_text())
    (role,) = data["roles"]
    assert counts == {"agents": 1, "records": 3, "incomplete_in_files": 0}
    assert role["summary"]["tasks_run"] == len(data["records"]) == 3
    assert role["summary"]["tasks_correct"] == sum(r["result"]["correct"] for r in data["records"]) == 2
    first = data["records"][0]                                   # newest first
    assert first["run"]["attempt_id"] == "20261117-100000-c" and first["signature"] is None
    assert first["schema"] == "avc.test-evidence.v1" and first["run"]["at"].endswith("+09:00")
    assert first["subject"]["tool_fingerprint"] == "sha256:" + "ab" * 32


def test_a_private_set_shows_only_hashes(tmp_path, monkeypatch):
    """PM 11-16: a holdout case's input and truth never reach the public evidence, only hashes."""
    version(tmp_path, 8, "package.releases.v1", "20261117-090000-a", answer_set="package-risk-audit/holdout-r2",
            case_id="pkg:left-pad", arguments={"package": "left-pad"})
    version(tmp_path, 8, "package.releases.v1", "20261117-090001-b", answer_set=..., case_id="pkg:secret")
    _, out = build(tmp_path, monkeypatch)
    text = (out / "agents" / "8.json").read_text()
    assert "left-pad" not in text and "pkg:" not in text
    records = json.loads(text)["records"]
    assert all("input" not in r["task"] and "case_id" not in r["task"] and "case_id_sha256" in r["task"] for r in records)


def test_public_role_tasks_may_show_their_input(tmp_path, monkeypatch):
    version(tmp_path, 9, "timezone.time.v1", "20261117-090000-a")
    _, out = build(tmp_path, monkeypatch)
    (record,) = json.loads((out / "agents" / "9.json").read_text())["records"]
    assert record["task"] == {"answer_set": "rag:role-tasks-rag-v1", "case_id": "time-seoul",
                              "input": {"timezone": "Asia/Seoul"}}


def test_missing_keys_never_qualify(tmp_path, monkeypatch):
    """Source review C04: a record without its fingerprint, endpoint or response hash is kept, marked incomplete,
    and never qualifies, even when the answer passed."""
    version(tmp_path, 10, "timezone.time.v1", "20261117-090000-a", tool_fingerprint=..., response_hash="")
    counts, out = build(tmp_path, monkeypatch)
    (record,) = json.loads((out / "agents" / "10.json").read_text())["records"]
    assert record["result"]["correct"] is True and record["complete"] is False and record["qualifies"] is False
    assert record["missing"] == ["tool_fingerprint", "response_hash"] and counts["incomplete_in_files"] == 1


def test_no_stored_tests_writes_nothing(tmp_path, monkeypatch):
    counts, out = build(tmp_path, monkeypatch)
    assert counts == {"agents": 0, "records": 0, "incomplete_in_files": 0} and not (out / "agents").exists()
