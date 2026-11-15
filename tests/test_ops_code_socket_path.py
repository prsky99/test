"""Scripts the 02:30 report batch runs from gateway-data/ops-code/<commit> resolve the gateway-data link before
joining the socket path: the joined path under that folder passed the 103 byte Unix socket limit and the 11-16 02:30
batch failed at step 1 ("Unix-domain socket path ... is too long")."""
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BATCH_SCRIPTS = ('classify_and_quarantine_agents.py', 'remediate_all_test_reports.py', 'ops_auto.py')


def test_batch_scripts_do_not_join_the_socket_path_onto_their_own_folder():
    for name in BATCH_SCRIPTS:
        source = (ROOT / 'scripts' / name).read_text()
        assert not re.search(r"(parents\[1\]|ROOT) / 'gateway-data/postgres18/run'", source), name
        assert "os.path.realpath(" in source and "'/postgres18/run'" in source, name


def test_the_resolved_socket_path_fits_the_limit_from_a_long_ops_code_folder(tmp_path):
    folder = tmp_path / ('ops-code-' + 'x' * 120)
    folder.mkdir()
    (folder / 'gateway-data').symlink_to(tmp_path)
    host = os.path.realpath(folder / 'gateway-data') + '/postgres18/run'
    assert len(str(folder / 'gateway-data/postgres18/run/.s.PGSQL.55432').encode()) > 103
    assert host == os.path.realpath(tmp_path) + '/postgres18/run'
