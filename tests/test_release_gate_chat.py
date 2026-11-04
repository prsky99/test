"""The release gate compares Chat answers when a release changes how Chat recommends (2nd review A-3)."""
from scripts import release_gate as gate


def fake(verdicts):
    calls = []

    def evaluate(release, cases, out, only=None):
        calls.append((release, tuple(only or ())))
        table = verdicts[release] if not only else verdicts.get(release + ':again', verdicts[release])
        return {i: ok for i, ok in table.items() if not only or i in only}
    return evaluate, calls


def test_releases_with_the_same_chat_files_skip_the_comparison(monkeypatch):
    monkeypatch.setattr(gate, 'chat_changed', lambda release, active: [])
    evaluate, calls = fake({})
    assert gate.chat_check('new', 'old', evaluate=evaluate) == 0 and calls == []


def test_more_new_failures_than_passes_refuse_the_release(monkeypatch):
    monkeypatch.setattr(gate, 'chat_changed', lambda release, active: ['agent_market/concierge/selection.py'])
    evaluate, calls = fake({'old': {'a': True, 'b': True, 'c': True, 'd': False},
                            'new': {'a': False, 'b': False, 'c': True, 'd': False}})
    assert gate.chat_check('new', 'old', evaluate=evaluate) == 1
    # New failures are measured once more on both releases before refusing.
    assert calls[-2:] == [('new', ('a', 'b')), ('old', ('a', 'b'))]


def test_a_case_the_active_release_now_fails_too_is_data_not_a_regression(monkeypatch):
    monkeypatch.setattr(gate, 'chat_changed', lambda release, active: ['agent_market/concierge/fast_chat.py'])
    evaluate, _ = fake({'old': {'a': True, 'b': True}, 'new': {'a': False, 'b': False},
                        'old:again': {'a': False, 'b': False}})
    assert gate.chat_check('new', 'old', evaluate=evaluate) == 0


def test_a_failure_that_passes_on_the_second_run_is_noise(monkeypatch):
    monkeypatch.setattr(gate, 'chat_changed', lambda release, active: ['agent_market/concierge/fast_chat.py'])
    evaluate, _ = fake({'old': {'a': True, 'b': True}, 'new': {'a': False, 'b': False},
                        'new:again': {'a': True, 'b': False}})
    assert gate.chat_check('new', 'old', evaluate=evaluate) == 0


def test_fixes_offset_failures():
    assert gate.compare({'a': True, 'b': False}, {'a': False, 'b': True}) == (['a'], ['b'])


def test_the_sample_is_fixed_and_includes_the_review_cases():
    first, second = gate.chat_sample(), gate.chat_sample()
    assert first == second and len(first) >= gate.CHAT_SAMPLE
    assert {'rv1', 'rv2', 'rv3', 'rv10'} <= {case['id'] for case in first}


def test_chat_files_cover_every_policy_hash_file():
    from agent_market import explore_documents
    import inspect
    source = inspect.getsource(explore_documents.policy_hash)
    for name in ('selection.py', 'task_requirements.py', 'explore_search.py', 'execution_policy.py',
                 'capability_registry.py', 'usage.py', 'postgres_capability_text.py'):
        assert name in source and any(path.endswith(name) for path in gate.CHAT_FILES)
