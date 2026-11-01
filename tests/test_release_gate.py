import pytest

from scripts import release_gate


def test_unknown_release_is_refused(tmp_path):
    with pytest.raises(SystemExit, match='release not found'):
        release_gate.copy_release('no-such-release', tmp_path)


def test_default_list_covers_the_opening_paths():
    assert all((release_gate.ROOT / test).is_file() for test in release_gate.TESTS)
    assert 'tests/test_customer_batch.py' in release_gate.TESTS
