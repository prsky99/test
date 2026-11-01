"""Run the disposable workflow storage rehearsal; no operating database input."""
from pathlib import Path
import sys


def main():
    root=str(Path(__file__).resolve().parents[1])
    if root not in sys.path:sys.path.insert(0,root)
    from agent_market.workflow_storage_rehearsal import main as run
    return run()


if __name__=='__main__':raise SystemExit(main())
