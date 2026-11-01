from types import SimpleNamespace

from agent_market.concierge import front


def test_prefetched_report_rows_keep_the_same_kind_and_subject_checks(monkeypatch):
    # The has_report filter now reads report rows in batches; the batch may hold another
    # kind's rows for the same id, which the single-row query never returned.
    monkeypatch.setattr("agent_market.concierge.report_evidence.report_subject_matches", lambda row, resource: row["agent_name"] == resource["name"])
    resource = {"id": 7, "kind": "mcp", "name": "Weather"}
    rows = [{"id": 1, "kind": "mcp", "agent_name": "Weather"}, {"id": 2, "kind": "a2a", "agent_name": "Weather"},
            {"id": 3, "kind": "mcp", "agent_name": "Other"}]
    assert [row["id"] for row in front._trusted_report_rows(None, resource, rows)] == [1]
    assert front._trusted_report_rows(None, {**resource, "eval_security": "quarantine"}, rows) == []


def test_prefetch_is_postgres_only():
    assert front._report_prefetch(SimpleNamespace(backend="sqlite"), [1, 2]) == (None, None)
    assert front._report_prefetch(SimpleNamespace(backend="postgresql"), []) == (None, None)
