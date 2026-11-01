"""Exact classifier equivalence and bounded synthetic runtime measurements."""
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import pytest

from agent_market.gateway import classify as classifier


def reference_infra_score(text):
    """The algorithm before the literal prefilter, including dynamic patterns."""
    for pattern in classifier._INFRA_BLOCK:
        text = pattern.sub(' ', text)
    hits = [keyword for keyword, pattern in zip(classifier.KEYWORDS['agent_infra'],
        classifier._PATTERNS['agent_infra']) if pattern.search(text)]
    weak = sum(1 for keyword in hits if keyword in classifier.INFRA_WEAK)
    strong = len(hits) - weak + sum(1 for pattern in classifier.INFRA_PATTERNS if pattern.search(text))
    return strong + weak if strong or weak >= 2 else 0


def reference_scores(text):
    def raw(value):
        result = {category: sum(1 for pattern in patterns if pattern.search(value))
            for category, patterns in classifier._PATTERNS.items() if category != 'agent_infra'}
        result['agent_infra'] = reference_infra_score(value)
        return result
    text = text.lower()
    # Billing sentences are ignored unless nothing else in the listing scores.
    without_billing = raw(classifier._BILLING.sub(' ', text))
    return without_billing if any(without_billing.values()) else raw(text)


def reference_classify(text):
    values = reference_scores(text)
    best = max(classifier.PRIORITY, key=lambda category: (values[category], -classifier.PRIORITY.index(category)))
    return best if values[best] > 0 else classifier.OTHER


MATRIX = (
    '', 'Lumen quartz amber horizon',
    'git git2 2git digit githubish codependent prefixing',
    '_git_ /git/ (code) "dns" xdns dnsx dns2 2dns',
    'GITHUB DNS WEATHER OPENAPI',
    '\u00e9code\u00e9 \u03b1dns\u03b2 \u4e2dstock\u4e2d',
    '\u0130P i\u0307p \u212aYA \uff44\uff4e\uff53',
    '\uc5d0\uc774\uc804\ud2b8 \uac80\uc0c9\uae30 \uba40\ud2f0 \uc5d0\uc774\uc804\ud2b8 \uc624\ucf00\uc2a4\ud2b8\ub808\uc774\uc158',
    'token tokens tokens stock stocks trading funds funding rates funding rate',
    'agent card agent cards agent identity multi-agent',
    'Multi-agent analysis of weather',
    'Multi-agent analysis with an MCP router',
    'MCP gateway for example.com and the site\'s own MCP server',
    'Official daily news MCP gateway for WhatsApp',
    'An A2A hub for cosmetics and an agent-to-agent hub for groceries',
    'AgentIndex: search 15K+ MCP services, A2A agents and x402 APIs',
    'Discover 20 MCP servers from one catalog',
    'Browse x402 services; find A2A agents across directories',
    'MCP gateway for AI agents: agent identity and reputation registry',
    'Football agent index and player agents directory',
    'Storefront product listings make products discoverable in agent discovery',
    'Sponsored listings and generative engine optimization for AI visibility',
    'Agent-readiness audit for a website; health checks for MCP servers',
    'perp perpetual funding rates order book volatility regime',
    'JSON schema validator compiler formatter parse normalization',
    'Research brief citation papers reports documentation',
    'DNS TLS certificate latency IPv6 IP address',
    'S&P crude oil gold spot open-interest macro nasdaq',
    'Weather\nagent identity\tsemantic search\x00MCP registry',
)


@pytest.mark.parametrize('text', MATRIX)
def test_score_and_category_matrix_matches_original_algorithm_exactly(text):
    assert classifier.scores(text) == reference_scores(text)
    assert classifier.classify(text) == reference_classify(text)


def test_every_declared_literal_and_boundary_matches_original_scores():
    for keywords in classifier.KEYWORDS.values():
        for keyword in keywords:
            for text in (keyword, 'x' + keyword + '2', '_' + keyword.upper() + '_', '\u00e9' + keyword + '\u00e9'):
                assert classifier.scores(text) == reference_scores(text), repr(text)


def test_infrastructure_dynamic_and_block_patterns_retain_original_semantics():
    for text in MATRIX:
        assert classifier._infra_score(text) == reference_infra_score(text)
    # This dynamic match has no literal agent-infrastructure keyword.
    text = 'search 15k mcp services and a2a agents'
    assert not any(keyword in text for keyword in classifier.KEYWORDS['agent_infra'])
    assert classifier._infra_score(text) == reference_infra_score(text) > 0


def test_existing_labeled_fixture_has_exactly_the_same_scores_and_categories():
    source = Path(__file__).parent / 'data' / 'agent_infra_labels.json'
    rows = json.loads(source.read_text())
    assert len(rows) == 535
    for row in rows:
        assert classifier.scores(row['text']) == reference_scores(row['text'])
        assert classifier.classify(row['text']) == reference_classify(row['text'])


def synthetic_long_corpus():
    neutral = 'lumen quartz amber distant horizon narrow passage. ' * 400
    return tuple(neutral + suffix for suffix in (
        'DNS certificate latency lookup',
        'documentation research citation',
        'forecast weather latitude longitude',
        'agent identity and agent reputation registry',
        'search 15k MCP services and A2A agents',
    ))


def benchmark_classifier():
    """Return observations only; timings are not an SLA or a pass threshold."""
    corpus = synthetic_long_corpus()
    expected = tuple(reference_scores(text) for text in corpus)
    assert tuple(classifier.scores(text) for text in corpus) == expected
    original, optimized = [], []
    for _ in range(3):
        started = perf_counter()
        assert tuple(reference_scores(text) for text in corpus) == expected
        original.append(perf_counter() - started)
        started = perf_counter()
        assert tuple(classifier.scores(text) for text in corpus) == expected
        optimized.append(perf_counter() - started)
    original_median, optimized_median = median(original), median(optimized)
    return {'profile': 'classifier-literal-prefilter-runtime-v1', 'classifier_version': classifier.VERSION,
        'synthetic_documents': len(corpus), 'total_characters': sum(map(len, corpus)), 'repetitions': 3,
        'scores_identical': True, 'original_median_ms': original_median * 1000,
        'optimized_median_ms': optimized_median * 1000,
        'observed_speedup': original_median / optimized_median if optimized_median else None,
        'measured_performance_only': True, 'establishes_startup_sla': False,
        'operating_database_actions': 0, 'server_operations': 0, 'model_calls': 0}


def test_long_synthetic_corpus_preserves_scores_without_wall_time_threshold():
    report = benchmark_classifier()
    assert report['scores_identical'] is True
    assert report['original_median_ms'] >= 0 and report['optimized_median_ms'] >= 0
