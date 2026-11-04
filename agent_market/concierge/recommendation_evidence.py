"""Per-recommendation evidence an agent or a person can check, with unknown stated as unknown (2026-11-04).

Every recommendation carries the same small object in Chat (`recommendations[].evidence`) and in
`POST /api/agent/v1/discover` (`items[].evidence`):

- `health_checked_at`: the last time the endpoint answered an active check (ISO 8601 UTC), or null.
- `trial_call`: the latest recorded test call: `status` passed, failed or unknown, `report_id`, `at`.
- `selected_tool_check`: passed when the chosen tool itself was verified for this task, else unknown.
- `unknown`: the names of the facts above that have no record, so a reader never mistakes a missing
  record for a pass.
"""
from datetime import datetime, timezone

FIELDS = ('health_checked_at', 'trial_call', 'selected_tool_check')


def _iso(value):
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds')


def evidence(item):
    """The evidence object for one recommendation; reads only fields selection already returned."""
    checked = _iso(item.get('active_checked_at'))
    report = item.get('test_report') if isinstance(item.get('test_report'), dict) else None
    if report:
        at = _iso(report.get('executed_at')) or _iso(report.get('created_at'))
        trial = {'status': 'passed' if report.get('success') else 'failed', 'report_id': report.get('id'), 'at': at}
    else:
        trial = {'status': 'unknown', 'report_id': None, 'at': None}
    task_check = item.get('task_verification') if isinstance(item.get('task_verification'), dict) else {}
    tool = 'passed' if task_check.get('status') == 'verified' else 'unknown'
    unknown = [name for name, missing in (('health_checked_at', checked is None),
                                          ('trial_call', trial['status'] == 'unknown'),
                                          ('selected_tool_check', tool == 'unknown')) if missing]
    return {'health_checked_at': checked, 'trial_call': trial, 'selected_tool_check': tool, 'unknown': unknown}
