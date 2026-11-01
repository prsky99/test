"""Legacy gateway report tools are explicit, bounded, read-only inventories."""
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.migrate_all_to_gateway import audit_database


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "migrate_all_to_gateway", "apply_gateway_endpoints_all",
    "audit_reports", "test_gateway_transform",
)


@pytest.fixture
def report_database(tmp_path):
    path = tmp_path / "private-fixture?with#uri.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,url TEXT);
            CREATE TABLE agent_test_reports(id INTEGER PRIMARY KEY,resource_id INTEGER,
                kind TEXT,agent_url TEXT,content_md TEXT,input_wire TEXT,output_wire TEXT);
        ''')
        db.executemany("INSERT INTO resources VALUES (?,?,?)", [
            (1, "mcp", "https://upstream.example/project/mcp?api_key=fixture-secret"),
            (2, "mcp", "https://agentconcierge.biz/api/gateway/mcp/2"),
        ])
        db.executemany("INSERT INTO agent_test_reports VALUES (?,?,?,?,?,?,?)", [
            (1, 1, "mcp", "https://upstream.example/project/mcp?api_key=fixture-secret",
             "Upstream Provider Target https://upstream.example/project/mcp?api_key=fixture-secret; "
             "source https://upstream.example/docs/citation", '{"Authorization":"Bearer fixture-secret"}', "{}"),
            (2, 1, "a2a", "https://different-provider.example/card", "Other protocol", "{}", "{}"),
            (3, 99, "mcp", "https://agentconcierge.biz/api/gateway/mcp/99", "Orphan", "{}", "{}"),
            (4, 2, "mcp", "https://agentconcierge.biz/api/gateway/mcp/2", "Stored self-target", "{}", "{}"),
        ])
    return path


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def invoke(name, cwd, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / (name + ".py")), *args],
                          cwd=cwd, text=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_argument_invocation_refuses_implicit_live_database_paths(tmp_path, name):
    before = set(tmp_path.iterdir())
    result = invoke(name, tmp_path)
    assert result.returncode == 2
    assert "--db" in result.stderr
    assert set(tmp_path.iterdir()) == before
    assert not (tmp_path / "gateway-data").exists()


@pytest.mark.parametrize("name", SCRIPTS)
def test_missing_database_is_not_created_or_exposed(tmp_path, name):
    path = tmp_path / "private-fixture-secret.sqlite3"
    result = invoke(name, tmp_path, "--db", str(path))
    assert result.returncode == 1
    parsed = json.loads(result.stdout)
    assert parsed["database_writes"] == parsed["provider_calls"] == 0
    assert parsed["databases"] == [{"database_index": 1, "status": "unavailable",
                                     "error_code": "database_unavailable"}]
    assert str(path) not in result.stdout + result.stderr
    assert not path.exists()


@pytest.mark.parametrize("name", SCRIPTS)
def test_importing_compatibility_tools_never_connects_to_sqlite(monkeypatch, name):
    def reject_connection(*args, **kwargs):
        raise AssertionError("Import must not open any database")
    monkeypatch.setattr(sqlite3, "connect", reject_connection)
    module = importlib.import_module("scripts." + name)
    importlib.reload(module)


def test_readonly_inventory_preserves_evidence_bindings_and_citations(report_database):
    before = fingerprint(report_database)
    result = audit_database(report_database)
    assert result["status"] == "complete"
    assert result["counts"]["reports_scanned"] == 4
    assert result["counts"]["matched_resource_and_protocol"] == 2
    assert result["counts"]["missing_resource"] == 1
    assert result["counts"]["protocol_mismatch"] == 1
    assert result["counts"]["reports_with_managed_catalog_binding"] == 1
    assert result["counts"]["stored_raw_binding_mentions"] >= 1
    assert result["counts"]["stored_sensitive_pattern_candidates"] == 1
    assert fingerprint(report_database) == before
    with sqlite3.connect(report_database.as_uri() + "?mode=ro", uri=True) as db:
        url, content = db.execute("SELECT agent_url,content_md FROM agent_test_reports WHERE id=1").fetchone()
        assert "fixture-secret" in url
        assert "https://upstream.example/docs/citation" in content
        assert db.execute("SELECT url FROM resources WHERE id=1").fetchone()[0] == url


def test_cli_emits_only_fixed_aggregate_results_and_accepts_repeated_databases(report_database, tmp_path):
    before = fingerprint(report_database)
    result = invoke("migrate_all_to_gateway", tmp_path,
                    "--db", str(report_database), "--db", str(report_database))
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["mode"] == "read-only-stored-report-inventory"
    assert len(parsed["databases"]) == 2
    for private in ("fixture-secret", "upstream.example", "different-provider.example", str(report_database)):
        assert private not in result.stdout + result.stderr
    assert fingerprint(report_database) == before


def test_inventory_bound_is_explicit_and_does_not_claim_complete_coverage(report_database, tmp_path):
    result = invoke("migrate_all_to_gateway", tmp_path, "--db", str(report_database), "--max-reports", "2")
    assert result.returncode == 1
    scanned = json.loads(result.stdout)["databases"][0]
    assert scanned["status"] == "partial" and scanned["truncated"] is True
    assert scanned["counts"]["reports_scanned"] == 2


@pytest.mark.parametrize("option", ["--apply", "--mutate", "--rewrite"])
def test_cli_has_no_mutating_flag(report_database, tmp_path, option):
    before = fingerprint(report_database)
    result = invoke("migrate_all_to_gateway", tmp_path, "--db", str(report_database), option)
    assert result.returncode == 2
    assert fingerprint(report_database) == before


def test_invalid_schema_returns_fixed_error_without_initializing_tables(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE preserved(value TEXT)")
    before = fingerprint(path)
    result = invoke("migrate_all_to_gateway", tmp_path, "--db", str(path))
    assert result.returncode == 1
    assert json.loads(result.stdout)["databases"][0]["error_code"] == "required_schema_unavailable"
    assert fingerprint(path) == before


def test_oversized_report_body_is_bounded_and_disclosed(report_database):
    with sqlite3.connect(report_database) as db:
        db.execute("UPDATE agent_test_reports SET content_md=? WHERE id=1", ("x" * 300000,))
    before = fingerprint(report_database)
    result = audit_database(report_database)
    assert result["status"] == "partial"
    assert result["content_truncated"] is True
    assert result["counts"]["bounded_field_overflow_candidates"] == 1
    assert fingerprint(report_database) == before
