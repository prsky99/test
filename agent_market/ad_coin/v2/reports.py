"""Shared public report serialization; private source manifests are never exported."""

from datetime import datetime, timezone
import json
from .contracts import digest


def _date(value):
    return (
        datetime.fromtimestamp(value // 1000, timezone.utc)
        .replace(microsecond=value % 1000 * 1000)
        .isoformat()
        .replace("+00:00", "Z")
    )


def report_view(row):
    return {
        "id": row["id"],
        "obligation_id": row["obligation_id"],
        "revision": int(row["revision"]),
        "content_digest": row["content_digest"],
        "supersedes_revision": row["supersedes_revision"],
        "generated_at": _date(int(row["generated_ms"])),
        "data_through": _date(int(row["data_through_ms"])),
        "methodology_version": "aiac_p1_reporting_v1",
        "vendor_id": "ai-ad-coin/model",
        "vendor_relationship": "first_party",
        "complete": bool(row["complete"]),
        "timezone": "UTC",
        "metrics": json.loads(row["metrics_json"]),
    }


def report_digest(row):
    document = report_view(row)
    document.pop("content_digest")
    return digest(document)
