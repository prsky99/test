"""Recheck this local UI/performance evidence without rerunning the measured load."""

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main():
    root = ET.parse(OUT / "final.xml").getroot()
    suites = list(root.iter("testsuite"))
    tests = {key: sum(int(s.get(key, "0")) for s in suites)
             for key in ("tests", "failures", "errors", "skipped")}
    assert tests == {"tests": 169, "failures": 0, "errors": 0, "skipped": 0}, tests
    perf = json.loads((OUT / "postgres-performance.json").read_text())
    assert perf["connection_pool_warmed"]
    assert perf["ledger_conservation"] and perf["temporary_cluster_removed"]
    assert not any(perf[key] for key in ("checks_disabled", "production_access", "global_capacity_claim"))
    for name in ("before", "after"):
        phase = perf[name]
        assert phase["requested"] == phase["successful"] == phase["committed_economic_events"] == 1000
        assert phase["failed"] == 0 and not phase["errors"]
    assert perf["before"]["db_calls_p50"] == perf["after"]["db_calls_p50"] == 21
    assert json.loads((OUT / "secure-coding.json").read_text()) == []
    assert "335 public frontend files checked; 0 content policy violations." in (OUT / "content-final.log").read_text()
    contract = ROOT / "docs/ad_coin_platform_p1_v6_2.openapi.json"
    assert contract.read_bytes() == (ROOT / "agent_market/ad_coin/v2/p1_contract.json").read_bytes()
    count = sum(len([key for key in item if key in {"get", "post", "put", "delete", "patch"}])
                for item in json.loads(contract.read_text())["paths"].values())
    assert count == 29
    registry = json.loads((ROOT / "agent_market/ad_coin/sql_registry.json").read_text())["statements"]
    legacy = json.loads(subprocess.check_output(
        ["git", "show", "HEAD:agent_market/ad_coin/sql_registry.json"], cwd=ROOT))["statements"]
    assert len(registry) == 412 and len(legacy) == 174
    assert {item["sql"] for item in legacy} <= {item["sql"] for item in registry}
    for item in registry:
        assert hashlib.sha256(item["sql"].encode()).hexdigest() == item["sha256"]
    paths = [*sorted((ROOT / "agent_market/ad_coin/v2").rglob("*.py")),
             *sorted((ROOT / "agent_market/ad_coin/v2/web").glob("*")),
             ROOT / "scripts/ad_coin_v2_performance.py", ROOT / "scripts/check_front_content.py",
             ROOT / "agent_market/ad_coin/sql_registry.json", contract,
             ROOT / "tests/test_ad_coin_v2_workspace.py", ROOT / "tests/test_ad_coin_v2_workspace_browser.py",
             ROOT / "tests/test_ad_coin_v2_commercial.py", ROOT / "tests/test_ad_coin_v2_review.py",
             ROOT / "docs/AD_COIN.md", ROOT / "docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md",
             ROOT / "docs/ad_coin_v6_2_detail/02-storage-transactions.md",
             ROOT / "docs/ad_coin_v6_2_detail/05-ui-operations-tests.md",
             *sorted(OUT.glob("*.png")), OUT / "README.md", OUT / "verify.py",
             OUT / "final.xml", OUT / "browser-performance.json", OUT / "postgres-performance.json"]
    result = {
        "date_kst": "2026-11-09", "scope": "isolated PostgreSQL model and localhost Chromium",
        "tests": tests, "openapi_operations_unchanged": count,
        "sql_statements": len(registry), "legacy_statements_preserved": len(legacy),
        "postgres_only": True, "workspace_default_mounted": False,
        "live_identity_integrated": False, "production_release_changed": False,
        "global_performance_proven": False, "all_accessibility_certified": False,
        "source_and_evidence_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                       for path in paths},
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "source_and_evidence_sha256"}))


if __name__ == "__main__":
    main()
