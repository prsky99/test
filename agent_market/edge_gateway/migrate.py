"""Explicit operator migration; never invoked by serving or admin read paths."""
import argparse
import os
from pathlib import Path

from .operator_store import open_operator_store
from .state import migrate, ready


def main():
    parser = argparse.ArgumentParser(description='Add the isolated Edge Gateway state tables to an existing application database.')
    parser.add_argument('--sqlite', required=True, help='Existing application database path; the configured application backend still applies.')
    args = parser.parse_args()
    if os.environ.get('APPLICATION_STORE_BACKEND', 'sqlite') == 'sqlite' and (args.sqlite == ':memory:' or not Path(args.sqlite).is_file()):
        parser.error('Choose an existing operator-owned database file.')
    with open_operator_store(args.sqlite) as store:
        migrate(store)
        if not ready(store):
            raise RuntimeError('Edge schema verification failed')
        print('Edge Gateway additive migration verified. Serving configuration and Cloudflare routes were not changed.')


if __name__ == '__main__':
    main()
