#!/usr/bin/env python3
"""Inspect fixed catalog query indexes; --apply installs them without row changes."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from agent_market.catalog_query_indexes import IndexSetupError,inspect_front_query_indexes,ensure_front_query_indexes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args(argv)
    db = None
    try:
        if args.db.is_symlink():raise IndexSetupError('regular_owned_database_required')
        path = args.db.resolve(strict=True)
        info = path.stat()
        if not path.is_file() or info.st_uid!=os.getuid():
            raise IndexSetupError('regular_owned_database_required')
        db = sqlite3.connect(path.as_uri()+('?mode=rw' if args.apply else '?mode=ro'),uri=True,timeout=2)
        if args.apply:
            db.execute('BEGIN IMMEDIATE')
            result = ensure_front_query_indexes(db)
            db.commit()
        else:
            db.execute('PRAGMA query_only=ON')
            inspected = inspect_front_query_indexes(db)
            result = {'created':0,'existing':len(inspected['present']),'missing':len(inspected['missing'])}
        print(json.dumps({'ok':True,'applied':args.apply,'row_changes':0,**result},sort_keys=True))
        return 0
    except (IndexSetupError,OSError,sqlite3.Error) as error:
        if db is not None:db.rollback()
        code = str(error) if isinstance(error,IndexSetupError) else 'index_setup_failed'
        print(json.dumps({'ok':False,'applied':False,'error':code,'row_changes':0},sort_keys=True))
        return 1
    finally:
        if db is not None:db.close()


if __name__=='__main__':raise SystemExit(main())
