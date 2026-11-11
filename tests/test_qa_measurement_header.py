"""11-11: every request from our own measurement scripts says so (X-Agentcon-QA), for the error ledger only."""
import ast
from pathlib import Path

import pytest

SCRIPTS = {'scripts/real_task_score.py': 'real_task_score', 'scripts/public_full_check.py': 'public_full_check',
           'scripts/user_slo.py': 'user_slo'}


@pytest.mark.parametrize('path,name', SCRIPTS.items())
def test_every_client_and_browser_context_carries_the_qa_header(path, name):
    tree = ast.parse(Path(path).read_text())
    header = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and any(getattr(t, 'id', None) == 'QA_HEADER' for t in node.targets))
    assert ast.literal_eval(header) == {'X-Agentcon-QA': name}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ('Client', 'AsyncClient', 'new_context', 'new_page', 'urlopen')]
    assert calls, 'the script makes no request we can see'
    for call in calls:
        text = ast.unparse(call)
        if call.func.attr == 'new_page' and ast.unparse(call.func.value) != 'browser':
            continue  # a page opened from a context inherits the context's extra_http_headers
        assert 'QA_HEADER' in text, f'{path}: {text[:80]} sends requests without X-Agentcon-QA'
