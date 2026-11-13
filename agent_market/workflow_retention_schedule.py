"""Scheduled workflow run retention (user approval 11-14 via PM; reports/retention-audit-2026-11-14 section 2).

Workflow.maintenance.run (14-day body compaction, 90-day metadata pruning) had no scheduled caller: only the
admin API and the CLI ran it. The jobs scheduler now calls it once an hour between :20 and :50 (never during the
hourly public measurement, :55-:10, nor during the night task scoring, 03:50-05:10), at most 20 runs and 0.5 s of
work a call, and nothing while a run or a delivery is in flight (the maintenance code's own guards).

WORKFLOW_RETENTION_SCHEDULE=1 applies it; anything else only counts the candidates (a dry run) and logs them.
"""
import logging
import os
import time
from datetime import datetime

log = logging.getLogger(__name__)
ENV = 'WORKFLOW_RETENTION_SCHEDULE'
EVERY = 3600
LIMIT = 20


def in_window(now):
    """Minute 20-50 of an hour, outside 03:50-05:10."""
    local = datetime.fromtimestamp(now)
    hm = local.hour * 100 + local.minute
    return 20 <= local.minute <= 50 and not 350 <= hm <= 510


class WorkflowRetention:
    def __init__(self, workflows, clock=time.time, env=os.environ):
        self.workflows, self.clock, self.env = workflows, clock, env
        self.next_run = 0.0

    def enabled(self):
        return self.env.get(ENV, '').strip() == '1'

    def run_due(self, force=False):
        now = self.clock()
        if not force and (now < self.next_run or not in_window(now)):
            return None
        self.next_run = now + EVERY
        maintenance = getattr(self.workflows, 'maintenance', None)
        if maintenance is None:
            return None
        apply = self.enabled()
        try:
            result = maintenance.run(apply=apply, limit=LIMIT, actor=0)
        except Exception:
            log.exception('workflow retention step failed')
            return {'workflow_retention': 'failed'}
        summary = {key: result.get(key) for key in ('dry_run', 'busy', 'body_candidates', 'metadata_candidates',
                                                   'bodies_compacted', 'metadata_pruned', 'held_invalid_evidence')}
        if apply or summary.get('body_candidates') or summary.get('metadata_candidates'):
            log.info('workflow retention: %s', summary)
        return {'workflow_retention': summary}
