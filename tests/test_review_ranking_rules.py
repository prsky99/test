"""Expert review ranking misses rv2, rv3 and rv10 (2026-11-04, reports/ expert re-evaluation)."""
import pytest

from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.selection import _regional_languages_cover, capability_terms


@pytest.mark.parametrize('task,terms', [
    ('summarize a pdf research paper', ['document', 'summarization']),          # rv2: not a paper search
    ('check the status of a website', ['website', 'uptime', 'monitoring']),     # rv10: not an order status
    ('is my site up or down right now', ['website', 'uptime', 'monitoring']),
    # Unchanged neighbours.
    ('find research papers about battery recycling', ['academic', 'paper', 'search']),
    ('track order status on my shop website', ['track', 'order', 'status']),
    ('summarize this meeting', ['summarize', 'meeting']),
])
def test_capability_of_review_requests(task, terms):
    assert capability_terms(normalize_task(task)) == terms


def test_a_listing_built_around_another_language_does_not_serve_the_pair():
    korean = {'translation', 'english', 'korean'}
    assert not _regional_languages_cover(korean, 'Arabic-first OCR, translation and document extraction. 13+ languages')
    assert _regional_languages_cover({'translation', 'english', 'arabic'}, 'Arabic-first OCR, translation')
    assert _regional_languages_cover(korean, 'Translate text between 100+ languages')
    assert _regional_languages_cover(korean, 'Korean-first translator')
