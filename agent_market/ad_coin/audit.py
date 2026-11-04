"""Sponsorship audit: does turning sponsorship on ever change organic recommendations?

For each query the organic top results are read with sponsorship off, then on
(sponsorship active: circuit closed and live sponsor holds created for that
query), then off again. A query counts as changed only when both "off" reads
agree and the "on" read differs from them; queries whose two "off" reads
already differ are unstable and reported separately, never counted as a pass
or a failure. Any change fails the audit and should open the circuit (plan v3,
section 10, stop condition 4).
"""
from .db import now

TOP = 3


def audit(queries, *, fetch, set_sponsorship, activate=None, top=TOP, clock=now):
    """`fetch(query)` -> ordered organic ids; `set_sponsorship(bool)`;
    `activate(query, ids)` creates live sponsorship for the query (optional).
    Returns a report dict; `passed` is False if any stable query changed."""
    if not queries:
        raise ValueError('Give at least one audit query.')
    rows, started = [], clock()
    for query in queries:
        row = {'query': query}
        try:
            set_sponsorship(False)
            before = list(fetch(query))[:top]
            set_sponsorship(True)
            if activate:
                row['sponsorship_created'] = bool(activate(query, before))
            during = list(fetch(query))[:top]
            set_sponsorship(False)
            after = list(fetch(query))[:top]
        except Exception as exc:  # a failed read is an error row, not a pass
            row.update(verdict='error', error=type(exc).__name__ + ': ' + str(exc)[:200])
            rows.append(row)
            continue
        row.update(off=before, on=during, off_again=after)
        if before != after:
            row['verdict'] = 'unstable'
        elif during != before:
            row['verdict'] = 'changed'
        else:
            row['verdict'] = 'same'
        rows.append(row)
    counts = {v: sum(r['verdict'] == v for r in rows) for v in ('same', 'changed', 'unstable', 'error')}
    checked = counts['same'] + counts['changed']
    return {'profile': 'ai-ad-coin-sponsorship-audit-v1', 'started_at': int(started), 'finished_at': int(clock()),
            'top': top, 'queries': len(rows), 'counts': counts, 'checked': checked,
            'passed': counts['changed'] == 0 and checked > 0,
            'inconclusive': checked == 0, 'rows': rows}
