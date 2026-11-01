"""Remove expired operational logs; preserve today's records in active file handles."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent_market.log_retention import LOG_TIMEZONE, expired_log_files


def cleanup_runtime_logs(root, *, day, apply=False):
    """The running manager writes source/all copies before its console copy."""
    root=Path(root).resolve();logs=root/'logs';console=logs/'agentcon.log';startup=logs/'agentcon.log.startup'
    now=dt.datetime.combine(day,dt.time(12),LOG_TIMEZONE)
    candidates=expired_log_files(logs,now=now,protected=[console,startup])
    legacy=root/'gateway.log'
    if legacy.is_file() and not legacy.is_symlink() and dt.datetime.fromtimestamp(legacy.stat().st_mtime,LOG_TIMEZONE).date()<day:
        candidates.append(legacy)
    result={'day_kst':day.isoformat(),'apply':apply,'deleted_files':[],'deleted_bytes':0,'console_reset_bytes':0}
    # Check today's console records are already in the integrated daily log.
    # Clearing this duplicate in place preserves the live O_APPEND descriptor.
    all_today=logs/'all'/str(day.year)/f'{day.month:02d}'/f'all_{day.isoformat()}.log'
    can_reset=False
    if console.exists() and not console.is_symlink() and all_today.is_file() and not all_today.is_symlink():
        stamp=re.compile(rb'^\d{4}-\d{2}-\d{2} \d\d:\d\d:\d\d ')
        with console.open('rb')as handle:
            snapshot=handle.read()
        records=[];current=[];keep=False
        for line in snapshot.splitlines(keepends=True):
            if stamp.match(line):
                if current and keep:records.append(b''.join(current))
                current=[];keep=line.startswith(day.isoformat().encode()+b' ')
            current.append(line)
        if current and keep and snapshot.endswith(b'\n'):records.append(b''.join(current))
        integrated=all_today.read_bytes()
        missing=sum(record not in integrated for record in records)
        if missing:raise RuntimeError('Today console records are not fully duplicated; console preserved.')
        can_reset=True
        result['today_console_records_preserved_in_daily_log']=len(records)
    for file in candidates:
        size=file.stat().st_size
        result['deleted_files'].append(str(file.relative_to(root)))
        result['deleted_bytes']+=size
        if apply:file.unlink()
    if can_reset:
        result['console_reset_bytes']=console.stat().st_size
        if apply:
            descriptor=os.open(console,os.O_WRONLY|getattr(os,'O_NOFOLLOW',0))
            try:os.ftruncate(descriptor,0)
            finally:os.close(descriptor)
    if apply and startup.exists() and not startup.is_symlink() and startup.stat().st_size==0:
        os.utime(startup,None)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day',type=dt.date.fromisoformat,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    result=cleanup_runtime_logs(ROOT,day=args.day,apply=args.apply)
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(payload)
    print(payload)


if __name__=='__main__':main()
