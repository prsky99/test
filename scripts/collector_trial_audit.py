"""R69 follow-up: which tools did the collector actually call in trials that the new judgment refuses?

This script never connects to a database. Someone with production access (PM-approved) runs the read-only query
below and saves its output; this script then judges each called tool with the new collector rule
(``agent_market.collector.trial_safety.is_trial_safe_tool``) on this machine.

Only the last trial of each resource is stored (``resources.trial_info``), so this counts resources whose most
recent trial would now be refused, not every call ever made.

Read-only query (PostgreSQL; one JSON object per line):

    BEGIN READ ONLY;
    SET LOCAL statement_timeout = '60s';
    SELECT json_build_object(
        'id', r.id, 'kind', r.kind, 'trial_ok', r.trial_ok,
        'tool', r.trial_info::jsonb ->> 'tool',
        'at', r.trial_info::jsonb ->> 'at',
        'spec', (SELECT t FROM jsonb_array_elements(
                     CASE WHEN r.usage_tools ~ '^\\s*\\[' THEN r.usage_tools::jsonb ELSE '[]'::jsonb END) AS t
                 WHERE t ->> 'name' = r.trial_info::jsonb ->> 'tool' LIMIT 1))
    FROM resources r
    WHERE r.trial_info ~ '^\\s*\\{' AND r.trial_info::jsonb ? 'tool';
    COMMIT;

    psql "$DSN" -At -f query.sql > trials.jsonl      # run by the approved operator, not by an agent
    .venv/bin/python -m scripts.collector_trial_audit trials.jsonl

Output: totals, how many the new rule refuses (and why, by the first failing check), and the refused tool names
most often seen, with no URLs or arguments (they can carry user text).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from agent_market.collector import trial_safety, usage


def reason(spec: dict) -> str | None:
    """None when the new rule allows the tool, else the first check it fails."""
    ann = spec.get("annotations") or {}
    name, desc = str(spec.get("name") or ""), str(spec.get("description") or "")
    if ann.get("destructiveHint") is True:
        return "destructive_hint"
    if ann.get("readOnlyHint") is False:
        return "read_only_false"
    if any(usage._PII_PARAM.search(p) for p in spec.get("required") or []):
        return "personal_data_parameter"
    if usage._DENY.search(name) or usage._DENY.search(desc):
        return "deny_word"  # passed before only through readOnlyHint=true or a deny word past 200 characters
    if trial_safety.denied(name, desc):
        return "deny_word_new"
    if ann.get("readOnlyHint") is True:
        return None
    return None if usage.relay_tool_name(name, desc) else "name_not_a_read_verb"


def audit(lines) -> dict:
    total, missing = 0, 0
    reasons, names = Counter(), Counter()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        total += 1
        spec = row.get("spec")
        if not isinstance(spec, dict):
            missing += 1  # the tool list changed since the trial; judge the name alone
            spec = {"name": row.get("tool") or "", "description": "", "annotations": {}, "required": []}
        why = reason(spec)
        if why:
            reasons[why] += 1
            names[str(spec.get("name"))[:100]] += 1
    return {"trials": total, "spec_missing": missing, "refused_now": sum(reasons.values()),
            "by_reason": dict(reasons.most_common()), "top_refused_names": names.most_common(40)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="JSON lines from the read-only query in this file's docstring")
    args = parser.parse_args(argv)
    with args.export.open(encoding="utf-8") as fh:
        print(json.dumps(audit(fh), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
