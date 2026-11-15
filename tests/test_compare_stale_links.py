"""Old comparison links (PM 11-16 04:2x): a link kept on an edge-cached page may name a pair that is not neighbours in
today's snapshot, or whose agent has left it. It answers a temporary redirect to the agent still listed (404 only when neither is), and
no comparison page appears for a pair that is not listed."""
from agent_market.concierge import growth_catalog as gc


def snapshot(*ids):
    return {'catalog': {i: {'id': i, 'name': 'A' + str(i), 'kind': 'mcp'} for i in ids}, 'tasks': []}


def test_old_pairs_go_to_a_listed_agent_or_the_ranking():
    assert gc.stale_pair_target(10, 20, snapshot(10, 20)) == '/agent/10'
    assert gc.stale_pair_target(10, 20, snapshot(20)) == '/agent/20'       # the first one left the snapshot
    assert gc.stale_pair_target(10, 20, snapshot(10)) == '/agent/10'
    assert gc.stale_pair_target(10, 20, snapshot()) is None               # neither listed: stays 404 (bounded)
    assert gc.stale_pair_target(20, 10, snapshot(10, 20)) is None          # not the canonical order: stays 404
    assert gc.compare_page(10, 20, snapshot(10, 20)) is None               # no new page for an unlisted pair
