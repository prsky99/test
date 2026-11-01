"""Explicit host-only delivery controls; renewed admin API remains read-only."""
import argparse
import json
import os
from pathlib import Path

from .config import EdgeError
from .operator_store import open_operator_store
from .state import host_control, ready, rows, transaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', required=True)
    parser.add_argument('action', choices=('status', 'origin', 'auto', 'clear-runtime-block'))
    parser.add_argument('--revision', type=int)
    parser.add_argument('--reason')
    parser.add_argument('--validated-profile', action='store_true', help='Confirm that the corrected Worker profile has been validated before clearing its runtime block.')
    args = parser.parse_args()
    if os.environ.get('APPLICATION_STORE_BACKEND', 'sqlite') == 'sqlite' and not Path(args.sqlite).is_file():
        parser.error('Choose an existing application database.')
    if args.action != 'status' and (args.revision is None or args.reason is None):
        parser.error('Changes require the current revision and a short reason.')
    if args.action == 'clear-runtime-block' and not args.validated_profile:
        parser.error('Validate the corrected profile before clearing the runtime block.')
    with open_operator_store(args.sqlite) as store:
        if not ready(store):
            raise EdgeError('NOT_PROVISIONED')
        if args.action != 'status':
            host_control(store, args.action, args.revision, args.reason, actor='host-uid-' + str(os.getuid()))
        with transaction(store, readonly=True) as db:
            result = rows(db, 'policy')[0]
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
