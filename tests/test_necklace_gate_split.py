"""scripts.necklace_gate split: 60 held-out cases into two seeded rounds of 30, each stratum halved (gate 8.2, 9)."""
import hashlib
import json

import pytest

from scripts import necklace_gate as gate


def make_set(tmp_path, n=60, strata=('a', 'b')):
    folder = tmp_path / 'gold' / 'x'
    folder.mkdir(parents=True)
    lines = [json.dumps({'case_id': f'c{i}', 'stratum': strata[i % len(strata)]}) for i in range(n)]
    text = '\n'.join(lines) + '\n'
    (folder / 'holdout-r9.jsonl').write_text(text)
    (folder / 'manifest.json').write_text(json.dumps({'files': {'holdout-r9': {'cases': n, 'sha256': hashlib.sha256(text.encode()).hexdigest()}}}))
    return folder


def test_split_is_seeded_balanced_and_registered(tmp_path):
    folder = make_set(tmp_path)
    assert gate.split_rounds(tmp_path, 'x', 'holdout-r9', 'seed-1') == {'holdout-r9-g1': 30, 'holdout-r9-g2': 30}
    rounds = [[json.loads(l) for l in (folder / f'holdout-r9-g{n}.jsonl').read_text().splitlines()] for n in (1, 2)]
    ids = [{c['case_id'] for c in r} for r in rounds]
    assert not ids[0] & ids[1] and len(ids[0] | ids[1]) == 60
    assert [sum(c['stratum'] == 'a' for c in r) for r in rounds] == [15, 15]
    manifest = json.loads((folder / 'manifest.json').read_text())['files']
    assert manifest['holdout-r9-g2']['derived_from'] == 'holdout-r9' and manifest['holdout-r9-g2']['seed'] == 'seed-1'
    first = (folder / 'holdout-r9-g1.jsonl').read_text()
    gate.split_rounds(tmp_path, 'x', 'holdout-r9', 'seed-1')
    assert (folder / 'holdout-r9-g1.jsonl').read_text() == first              # same seed, same rounds
    gate.split_rounds(tmp_path, 'x', 'holdout-r9', 'seed-2')
    assert (folder / 'holdout-r9-g1.jsonl').read_text() != first


def test_split_refuses_a_changed_or_short_set(tmp_path):
    folder = make_set(tmp_path)
    with open(folder / 'holdout-r9.jsonl', 'a') as f:
        f.write('{"case_id": "extra"}\n')
    with pytest.raises(SystemExit):
        gate.split_rounds(tmp_path, 'x', 'holdout-r9', 's')
    with pytest.raises(OSError):
        gate.split_rounds(tmp_path / 'none', 'x', 'holdout-r9', 's')
    short = make_set(tmp_path / 'b', n=40)
    with pytest.raises(SystemExit):
        gate.split_rounds(tmp_path / 'b', 'x', 'holdout-r9', 's')
    assert short.exists()
