"""Folders the storage inventory may pass over (11-15, PM). The exemptions cannot hide a Python file.

NON_PYTHON_DIRS: each exists, holds no Python and keeps a name an outside format fixes (a Claude Code plugin skill is
named by its folder). BUILD_OUTPUT_DIRS: forge build output (AI AD Coin); each is listed in the contracts .gitignore,
so it never reaches git or a release copy, and where a working tree has it, it holds no Python."""
from pathlib import Path

from agent_market.storage_inventory import BUILD_OUTPUT_DIRS, NAME, NON_PYTHON_DIRS

ROOT = Path(__file__).resolve().parents[1]


def test_exempt_folders_exist_hold_no_python_and_need_the_exemption():
    for rel in NON_PYTHON_DIRS:
        folder = ROOT / rel
        assert folder.is_dir(), rel
        assert not any(folder.rglob('*.py')), rel
        assert not NAME.fullmatch(folder.name), rel      # an identifier name would not need it


def test_build_output_is_git_ignored_and_holds_no_python():
    for rel in BUILD_OUTPUT_DIRS:
        folder = ROOT / rel
        ignored = (folder.parent / '.gitignore').read_text(encoding='utf-8').split()
        assert folder.name + '/' in ignored, rel
        if folder.exists():
            assert not any(folder.rglob('*.py')), rel
