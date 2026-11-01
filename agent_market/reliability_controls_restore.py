"""Permanent restore tombstones for old reliability authority, separate from signatures."""
from .workspace_access import WorkspaceInvalid

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_controls_restore_blocks (
       authority_id TEXT PRIMARY KEY)''',
)


def authority_id(kind, identity, revision=None):
    if kind == 'eval_job' and revision is None:
        return 'eval_job:'+identity
    if kind not in ('eval_control', 'eval_plan', 'routing_policy') or type(revision) is not int or revision < 0:
        raise WorkspaceInvalid()
    return kind+':'+identity+':'+str(revision)


def blocked(db, kind, identity, revision=None):
    return bool(db.execute('SELECT 1 FROM reliability_controls_restore_blocks WHERE authority_id=?',
                           (authority_id(kind, identity, revision),)).fetchone())
