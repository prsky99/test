"""Deterministic meaning checks shared by every reviewed model proposal."""
import re

from .concierge.query_intent import missing_subjects


def topic_preserved(objective, proposed):
    return not missing_subjects(objective, proposed)


def title_dependency_preserved(objective, nodes):
    """An explicitly requested returned-title search needs a real typed binding."""
    requested = re.search(
        r'\b(?:using|use|with|search(?:\s+for)?)\s+(?:the\s+)?(?:first\s+)?(?:returned\s+|result(?:ing)?\s+)?title\b'
        r'|\b(?:first|returned|resulting)\s+(?:result[\x27\u2019]s?\s+)?title\b'
        r'|\uac80\uc0c9(?:\ud55c|\ub41c)?\s*(?:\uacb0\uacfc\uc758?\s*)?\uc81c\ubaa9', objective, re.I)
    if not requested:
        return True
    if len(nodes) < 2:
        return False
    for index, node in enumerate(nodes[1:], 1):
        binding = node.get('bindings', {}).get('query', {})
        previous = nodes[index-1].get('id')
        if (binding.get('node_id') != previous or binding.get('path') != ['items', 0, 'title']
                or previous not in node.get('after', []) or 'query' in node.get('input', {})):
            return False
    return True
