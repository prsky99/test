"""First line of an agent from its role-task results (PM 11-16 21:13, value review ①, due 11-24).

The verified-pearl snapshot gains four fields per agent role (search and RAG, 11-18; names shared with the agent
team's machine-readable test evidence v1): tasks_run, tasks_correct, success_days, last_checked. This module only
reads them. When any of them is missing or not a plain count, it returns None and the caller keeps what it shows
today: no value is made up or derived here.
"""
from __future__ import annotations

import re

FIELDS = ('tasks_run', 'tasks_correct', 'success_days', 'last_checked')
_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def facts(role: dict | None) -> dict | None:
    """The four fields of one snapshot role, checked, or None when they are not all there and consistent."""
    if not isinstance(role, dict) or any(k not in role for k in FIELDS):
        return None
    run, correct, days = (_count(role.get(k)) for k in FIELDS[:3])
    found = _DATE.match(str(role.get('last_checked') or ''))
    if run is None or correct is None or days is None or not found or run == 0 or correct > run:
        return None
    return {'role': role.get('role'), 'tasks_run': run, 'tasks_correct': correct, 'success_days': days,
            'last_checked': found.group(1)}


def line(role: dict | None) -> str | None:
    """'Correct on M of N role tasks · checked on K different days · last checked YYYY-MM-DD', or None."""
    f = facts(role)
    if not f:
        return None
    days = f['success_days']
    when = 'checked on 1 day' if days == 1 else f'checked on {days} different days'
    return (f"Correct on {f['tasks_correct']} of {f['tasks_run']} role task{'s' if f['tasks_run'] != 1 else ''}"
            f' · {when} · last checked {f["last_checked"]}')


def best(roles) -> dict | None:
    """The role an agent's first line speaks for: most correct tasks, then most days, then the latest check."""
    usable = [f for f in (facts(r) for r in roles or ()) if f]
    if not usable:
        return None
    return max(usable, key=lambda f: (f['tasks_correct'], f['success_days'], f['last_checked']))


def agent_line(agent: dict | None) -> str | None:
    """First line for one snapshot agent (its best role, with the role named), or None to keep today's display."""
    f = best((agent or {}).get('roles'))
    if not f:
        return None
    text = line(f)
    return f"{f['role']}: {text}" if f.get('role') else text
