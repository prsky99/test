"""mcp-registry gate answer set: a re-judgement split leaves out the servers of earlier splits (ops 11-17)."""
import json

import pytest

from scripts import gold_mcp_registry as G


def rows(n):
    return [({"server": {"name": f"io.github.o{i:03d}/s", "version": "1.0.0"}}, {"publishedAt": "2026-11-01"})
            for i in range(n)]


def test_exclude_split_leaves_out_servers_already_used(tmp_path):
    first = G.build(rows(100), listed=24, absent=6, seed="substitute-r1")
    (tmp_path / "substitute-r1.jsonl").write_text("".join(json.dumps(c) + "\n" for c in first))
    seen = G.seen_names(tmp_path, ["substitute-r1", ""])
    assert len(seen) == 30
    second = G.build(rows(100), listed=24, absent=6, seed="substitute-r2", exclude=seen)
    assert len(second) == 30 and not {c["input"]["name"] for c in second} & seen
    with pytest.raises(SystemExit):
        G.seen_names(tmp_path, ["substitute-r9"])           # a missing split stops the build, never ignored
