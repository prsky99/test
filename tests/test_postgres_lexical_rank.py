"""PostgreSQL Explore ranking keeps text relevance comparable to quality boosts."""
import json
from pathlib import Path

from agent_market.postgres_lexical import COUNT_PREFIX, MATCH_PREFIX


def test_lexical_rank_is_not_scaled_away():
    # A 1e-6 factor made eval_score/trial_ok decide the order on their own.
    assert '0.000001' not in MATCH_PREFIX
    assert '*2' in MATCH_PREFIX and '*4' in MATCH_PREFIX


def test_name_outweighs_description_and_scores_are_bounded():
    assert "COALESCE(f.name,''))),'A')" in MATCH_PREFIX
    assert "COALESCE(f.description,''))),'D')" in MATCH_PREFIX
    assert 'q.terms,2|32)' in MATCH_PREFIX and 'q.terms,32)' in MATCH_PREFIX


def test_catalog_statements_use_the_current_prefix():
    catalog = json.loads(Path('agent_market/application_store_sql.json').read_text())
    lexical = [item for item in catalog['statements'] if isinstance(item, dict) and item.get('postgres_lexical')]
    counts = [item['postgres_lexical'] for item in lexical if item['adapter'] == 'explore-fts5-count-v1']
    ranked = [item['postgres_lexical'] for item in lexical if item['adapter'] != 'explore-fts5-count-v1']
    assert counts and ranked and all(sql.startswith(COUNT_PREFIX) for sql in counts)
    assert all(sql.startswith(MATCH_PREFIX) for sql in ranked)


def test_count_prefix_matches_through_the_index_and_reads_no_rank():
    # Same membership as the ranked prefix; a count statement never reads m.rank.
    catalog = json.loads(Path('agent_market/application_store_sql.json').read_text())
    counts = [item['postgres_lexical'] for item in catalog['statements']
              if isinstance(item, dict) and item.get('adapter') == 'explore-fts5-count-v1']
    assert 'ts_rank' not in COUNT_PREFIX and 'MATERIALIZED' in COUNT_PREFIX
    assert 'agentcon_search.lexical_document(f.name,f.description) @@ q.terms' in COUNT_PREFIX
    assert all('rank' not in sql[len(COUNT_PREFIX):] for sql in counts)
