"""Bounded GET and optional read-only SQL timings; never an authenticated SLA claim."""

import argparse
import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def stats(values):
    ordered = sorted(values)
    return {
        "samples": len(values),
        "first_ms": round(values[0], 3),
        "p50_ms": round(ordered[math.ceil(len(values) * 0.5) - 1], 3),
        "p95_ms": round(ordered[math.ceil(len(values) * 0.95) - 1], 3),
        "max_ms": round(max(values), 3),
    }


def measure(origin, samples, dsn_file=None):
    url = urlsplit(origin)
    if (
        url.scheme not in ("http", "https")
        or url.hostname not in ("127.0.0.1", "localhost")
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("Use the existing loopback admin origin.")
    if not 5 <= samples <= 30:
        raise ValueError("Use 5 to 30 bounded samples.")
    result = {
        "scope": "Existing loopback GET and optional operating PostgreSQL read-only SQL; no writes/provider calls.",
        "http": {},
        "sql": {},
        "physical_cold_cache_tested": False,
        "authenticated_api_sla_tested": False,
        "limitations": [
            "First request is not a flushed physical DB/cache cold run.",
            "SQL timings exclude authentication/projection/HTTP overhead.",
            "No operating cache flush, workload injection or concurrent load.",
        ],
    }
    with httpx.Client(trust_env=False, timeout=5, follow_redirects=False) as client:
        for path in (
            "/admin/next",
            "/admin/next/assets/areas/catalog.js",
            "/admin/next/assets/areas/gateway.js",
        ):
            values = []
            statuses = []
            for _ in range(samples):
                start = time.perf_counter()
                response = client.get(origin.rstrip("/") + path)
                values.append((time.perf_counter() - start) * 1000)
                statuses.append(response.status_code)
            result["http"][path] = {
                **stats(values),
                "statuses": sorted(set(statuses)),
                "bytes": len(response.content),
            }
    if dsn_file:
        from agent_market.application_runtime import _connect
        from agent_market.admin_next import _CATALOG_PG
        from agent_market import workspace_admin_insights  # noqa: F401 - registers fixed SQL
        from agent_market.workspace_admin_events import Q

        connection = _connect(Path(dsn_file).read_text().strip())
        try:
            queries = {
                "catalog_first_page": (
                    _CATALOG_PG,
                    (None, None, None, None, None, None, None, None, None, 51),
                ),
                "gateway_attempt_sample": (
                    Q["insight_attempts"].replace("?", "%s"),
                    (time.time() - 86400,),
                ),
                "catalog_overview_counts": (
                    "SELECT kind,health_status,COUNT(*) FROM resources GROUP BY kind,health_status",
                    (),
                ),
            }
            for label, (sql, params) in queries.items():
                values = []
                count = 0
                for _ in range(samples):
                    start = time.perf_counter()
                    with connection.transaction():
                        connection.execute("SET TRANSACTION READ ONLY")
                        connection.execute("SET LOCAL statement_timeout='3s'")
                        connection.execute("SET LOCAL lock_timeout='200ms'")
                        count = len(connection.execute(sql, params).fetchall())
                    values.append((time.perf_counter() - start) * 1000)
                result["sql"][label] = {
                    **stats(values),
                    "rows": count,
                    "read_only": True,
                    "statement_timeout_ms": 3000,
                }
        finally:
            connection.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8200")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--dsn-file")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = measure(args.origin, args.samples, args.dsn_file)
    except Exception as exc:
        args.output.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "sqlstate": getattr(exc, "sqlstate", None),
                }
            )
            + "\n"
        )
        raise SystemExit(
            "Read-only timing failed; no credentials or server errors are printed."
        ) from None
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "http_checks": len(report["http"]),
                "sql_checks": len(report["sql"]),
                "authenticated_api_sla_tested": False,
            }
        )
    )
