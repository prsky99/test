"""PM 11-16 16:1x: the input object (document, file, read) leaves the capability words only when another word names
what is done with it; judged on a separate label set, not on the two queries that showed the regression."""
import json
from pathlib import Path

import pytest

from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.selection import capability_terms

LABELS = json.loads((Path(__file__).parent / 'data' / 'selection_input_object_labels.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', LABELS['cases'], ids=lambda case: case['id'])
def test_capability_terms_match_the_reviewed_labels(case):
    assert capability_terms(normalize_task(case['task'])) == case['terms']


def test_the_two_regressions_keep_their_object_and_the_original_cases_still_drop_it():
    by_id = {case['id']: case for case in LABELS['cases']}
    assert 'document' in by_id['d4']['terms'] and 'document' in by_id['text_diff-en1']['terms']
    assert by_id['d4']['regression'] and by_id['text_diff-en1']['regression']
    embed = [case for case in LABELS['cases'] if case['task'].startswith('embed documents')]
    assert embed and all(case['terms'] == ['embed'] for case in embed)        # Chat gate embeddings-en2 (11-13)
