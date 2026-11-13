"""PM 11-13 23:5x B1 and B2: word families the admission matched too strictly, and words that are not the
capability (Chat answer-quality gate token_holders-en2, embeddings-en2, figma-ko0, crypto_price-en2)."""
import pytest

from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.fast_chat import QUALIFIERS, retrieval_text
from agent_market.concierge.selection import QUALIFIER_PHRASES, _term_in, capability_terms


@pytest.mark.parametrize('term, text', [('analyze', 'competitor analysis'), ('analysis', 'analyze a csv'),
                                        ('embed', 'vector embeddings router'), ('holding', 'token holders'),
                                        ('scan', 'package scanner'), ('format', 'json formatter')])
def test_families_match(term, text):
    assert _term_in(term, text)


@pytest.mark.parametrize('term, text', [('booking', 'books and novels'), ('server', 'serving size'),
                                        ('openings', 'bottle openers'), ('driving', 'printer drivers'),
                                        ('analysis', 'web analytics'), ('working', 'remote workers'),
                                        ('earnings', 'top earners')])
def test_false_families_do_not(term, text):
    assert not _term_in(term, text)


@pytest.mark.parametrize('task, core', [
    ('track solana price changes over 24 hours', ['track', 'solana', 'changes', 'price']),
    ('list the largest wallets holding USDC', ['wallets', 'holding', 'usdc']),
    ('embed documents for a vector database', ['embed']),
    # "of a/an" is not a subject boundary: "the abstract of an arXiv paper" and "the transcript of a YouTube
    # video" lost what the abstract and the transcript are of (real tasks a06, p15, 11-14 00:4x).
    ('get the abstract of an arxiv paper by its id', ['abstract', 'arxiv', 'paper', 'id']),
    ('history of the roman empire', ['history', 'roman', 'empire']),
    ('price of bitcoin', ['bitcoin', 'price']),
])
def test_required_words(task, core):
    assert capability_terms(normalize_task(retrieval_text(task))) == core


def test_one_qualifier_list():
    assert QUALIFIERS is QUALIFIER_PHRASES


@pytest.mark.parametrize('task, text', [
    ('post to a Discord channel', 'send Discord message'),
    ('send a message to my Slack channel', 'send Slack message'),
    ('look up details for a CVE', 'look up CVE vulnerability'),
    ('post a tweet', 'post a tweet'),
])
def test_channel_and_cve_rewrites(task, text):
    """PM 11-14 02:3x: gate telegram-en1 lost "Discord" at "to", cve_scan-en1 lost "CVE" at "for"."""
    assert retrieval_text(task) == text
