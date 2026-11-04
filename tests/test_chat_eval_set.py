"""The generated 1k Chat evaluation set: deterministic, per-family holdout, valid judges (2026-11-04)."""
import json
import re

from scripts import build_chat_eval_set as b


def test_the_set_is_deterministic_and_matches_the_committed_file():
    first, second = b.build(), b.build()
    assert first == second
    committed = json.load(open(b.OUT, encoding='utf-8'))
    assert {k: committed[k] for k in ('tuning', 'holdout')} == first


def test_holdout_families_never_appear_in_tuning_and_ids_are_unique():
    split = b.build()
    family = lambda case: case['id'].rsplit('-', 1)[0]
    generated = {part: {family(c) for c in cases if c['group'].startswith('gen-')} for part, cases in split.items()}
    assert not generated['tuning'] & generated['holdout']
    ids = [c['id'] for cases in split.values() for c in cases]
    assert len(ids) == len(set(ids)) >= 1000


def test_every_judge_compiles_and_protocol_cases_expect_that_kind():
    for cases in b.build().values():
        for case in cases:
            for pattern in case['expect'].get('any', []):
                re.compile(pattern)
            protocol = (case.get('data') or {}).get('protocol')
            if case['group'].endswith('-protocol'):
                assert case['expect']['kind'] == protocol


def test_one_typo_swaps_two_inner_letters_of_the_longest_word():
    assert b.typo('get the weather forecast for Lisbon') == 'get the weather foercast for Lisbon'
    assert b.typo('a b c') is None
