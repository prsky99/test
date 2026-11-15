"""Folders the storage inventory may pass over by name (11-15, PM): each exists, holds no Python and keeps a name an
outside format fixes (a Claude Code plugin skill is named by its folder). The exemption cannot hide a Python file."""
from pathlib import Path

from agent_market.storage_inventory import NAME, NON_PYTHON_DIRS

ROOT = Path(__file__).resolve().parents[1]


def test_exempt_folders_exist_hold_no_python_and_need_the_exemption():
    for rel in NON_PYTHON_DIRS:
        folder = ROOT / rel
        assert folder.is_dir(), rel
        assert not any(folder.rglob('*.py')), rel
        assert not NAME.fullmatch(folder.name), rel      # an identifier name would not need it
