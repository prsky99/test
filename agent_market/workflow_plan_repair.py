"""One bounded local repair of a constrained model search query, never execution.

Only an explicit English supported objective can supply a replacement. Agent
choices, graph links and input authorization are still compiled and checked.
"""
import re

from .workspace_access import WorkspaceInvalid


def compile_with_repair(context, value, *, attempts=0):
    from .workflow_model_proposer import compile_proposal
    from .workflow_goal_policy import GoalQueryMismatch, goal_sequence, search_topic
    if type(attempts) is not int or attempts not in (0, 1): raise WorkspaceInvalid()
    try:
        return compile_proposal(context, value), 0
    except GoalQueryMismatch:
        if (not attempts or type(value) is not dict or set(value) != {'query'}
                or goal_sequence(context) is None or re.search(r'[^\x20-\x7e]', context['objective'])):
            raise
        # The replacement comes solely from the approved public objective.
        # Malformed graphs, invented agents and unsupported goals are not repaired.
        query = search_topic(context['objective'])
        return compile_proposal(context, {'query': query}), 1
