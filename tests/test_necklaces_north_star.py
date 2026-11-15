"""F09 (PM 11-14/15): one counting rule for the necklace north star in the daily summary and on the board."""
import json

from agent_market.necklaces import north_star


def ev(i, **kw):
    base = {"at": "2026-11-20T03:00:00Z", "slug": "topic-brief", "version": 1, "source": "external", "origin": "public",
            "outcome": "succeeded", "surface": "mcp", "latency_ms": 100 + i, "run_id": f"r{i}"}
    base.update(kw)
    return base


def test_an_outside_run_counts_once_and_ours_never():
    events = [ev(1), ev(1), ev(2, outcome="failed"), ev(3, source="internal", origin="public"),
              ev(4, origin="retest"), ev(5, source="crawler"), ev(6, cached=True), ev(7, outcome="failed", our_capacity=True)]
    c = north_star.count(events)
    assert (c["succeeded"], c["external_runs"], c["failed"], c["duplicates"]) == (1, 3, 1, 1)
    assert (c["internal"], c["crawler"], c["cached"], c["our_capacity"]) == (2, 1, 1, 1)
    assert c["by_slug"] == {"topic-brief": {"external_runs": 3, "succeeded": 1}}


def test_events_without_run_id_are_not_counted_twice_when_a_file_is_read_again():
    old = {k: v for k, v in ev(1).items() if k != "run_id"}
    assert north_star.count([old, dict(old)])["succeeded"] == 1


def test_a_kst_day_reads_two_utc_files(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "20261119.jsonl").write_text(json.dumps(ev(1, at="2026-11-19T16:30:00Z")) + "\n"     # 11-20 01:30 KST
                                          + json.dumps(ev(2, at="2026-11-19T10:00:00Z")) + "\n")  # 11-19 KST
    (runs / "20261120.jsonl").write_text(json.dumps(ev(3, at="2026-11-20T14:59:00Z")) + "\n"     # 11-20 23:59 KST
                                          + json.dumps(ev(4, at="2026-11-20T15:00:00Z")) + "\n")  # 11-21 KST
    metric = north_star.day_metric(tmp_path, "2026-11-20")
    assert metric["value"] == 2 and metric["metric_id"] == "necklace_external_successes"
    assert metric["definition_version"] == 1


def test_the_board_script_carries_the_necklace_metric_beside_the_pairs():
    from scripts import north_star as board
    edge = {"external": {"pairs": 0}}
    files = [{"funnel": {}}]
    record = board.build("2026-11-20", files=files, edge=edge,
                         necklaces={"value": 3, "metric_id": "necklace_external_successes"})
    assert record["north_star_v2"] == 3 and record["necklace"]["metric_id"] == "necklace_external_successes"
