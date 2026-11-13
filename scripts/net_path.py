#!/usr/bin/env python3
"""Network path recorder: one light line a minute, so a stall can be placed on one hop (11-11 PM).

    python3 scripts/net_path.py            # record one line to logs/ops/net-path.jsonl (launchd, every 60 s)
    python3 scripts/net_path.py --summary  # stalls of the last 24 h, each with the hop it stopped at

Five times on 11-11 (16:03, 16:21, 16:31, 16:37, 17:04) this Mac could not reach Cloudflare over the
public path while the origin answered locally in ~20 ms. Each minute this records, in parallel and with
short timeouts (the line is written within about 6 s):
- LAN: ping to the default gateway, and which interface carries the default route (wired or Wi-Fi), its
  error counters;
- ISP: ping to 1.1.1.1;
- DNS: the system resolver's answer time for the public host;
- Cloudflare edge from this Mac: a new connection to /cdn-cgi/trace (answered by the edge, never the
  origin), with DNS/TCP/TLS/first-byte times and the edge airport;
- the whole public path through the tunnel: a new connection to a cache-busted /robots.txt;
- the tunnel: cloudflared metrics (live edge connections and their airports, request errors, registrations).
- the origin from this Mac (11-13 PM 16:2x): the same cache-busted /robots.txt straight to the local proxy
  (127.0.0.1:8400, Caddy -> frontend). When the public path stalls while this answers at once, the time was
  lost between Cloudflare and the proxy (edge, tunnel); when this stalls too, it was the origin itself.
Nothing here sends credentials or changes settings; requests carry X-Agentcon-QA: net_path.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/net-path.jsonl'
HOST = 'agentconcierge.biz'
METRICS = 'http://127.0.0.1:20241/metrics'
ORIGIN = 'http://127.0.0.1:8400'
KST = timezone(timedelta(hours=9))
SLOW_S = 4.0     # this Mac reaches Cloudflare at LAX; ~2 s is its normal (11-11 18:33: trace 1.9 s)
CURL_FORMAT = '%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}'


def run(args, timeout):
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout
    except (subprocess.TimeoutExpired, OSError) as error:
        return None, type(error).__name__


def default_route():
    _, out = run(['route', '-n', 'get', 'default'], 3)
    gateway = re.search(r'gateway: (\S+)', out or '')
    interface = re.search(r'interface: (\S+)', out or '')
    return (gateway.group(1) if gateway else None), (interface.group(1) if interface else None)


def port_name(interface):
    _, out = run(['networksetup', '-listallhardwareports'], 3)
    for block in (out or '').split('\n\n'):
        if f'Device: {interface}\n' in block + '\n':
            name = re.search(r'Hardware Port: (.+)', block)
            return name.group(1).strip() if name else None
    return None


def counters(interface):
    _, out = run(['netstat', '-I', interface, '-b'], 3)
    for line in (out or '').splitlines()[1:2]:
        cols = line.split()
        if len(cols) >= 10:
            return {'in_errors': int(cols[5]), 'out_errors': int(cols[8])}
    return None


def ping(target):
    if not target:
        return None
    code, out = run(['ping', '-c', '1', '-t', '2', target], 4)
    took = re.search(r'time=([\d.]+) ms', out or '')
    return round(float(took.group(1)), 1) if code == 0 and took else None   # ms, None = no answer


def dns():
    code, out = run(['dig', '+time=2', '+tries=1', HOST], 4)
    took = re.search(r'Query time: (\d+) msec', out or '')
    return int(took.group(1)) if code == 0 and took else None


def curl(url, body=False, host=None):
    """A new connection each time; the times show how far a timed-out request got (exit 28)."""
    code, out = run(['curl', '-s', '-m', '5', '-H', 'X-Agentcon-QA: net_path', '-w', '\n' + CURL_FORMAT]
                    + (['-H', f'Host: {host}'] if host else [])
                    + ([] if body else ['-o', '/dev/null']) + [url], 7)
    text, _, last = (out or '').rpartition('\n')
    parts = last.split()
    if len(parts) != 6:
        return {'error': (out or 'no output')[:80], 'exit': code}
    status, *times = parts
    names = ('dns_s', 'tcp_s', 'tls_s', 'first_byte_s', 'total_s')
    result = {'status': int(status), **{n: round(float(t), 3) for n, t in zip(names, times)}}
    if code not in (0, None):
        result['exit'] = code
    if body:
        colo = re.search(r'^colo=(\w+)', text, re.M)
        result['colo'] = colo.group(1) if colo else None
    return result


def tunnel():
    code, out = run(['curl', '-s', '-m', '2', METRICS], 3)
    if code != 0 or not out:
        return {'error': 'metrics_unreadable'}

    def value(name):
        found = re.search(rf'^{name}(?:\{{[^}}]*\}})? ([\d.e+]+)$', out, re.M)
        return float(found.group(1)) if found else None
    return {'connections': value('cloudflared_tunnel_ha_connections'),
            'request_errors': value('cloudflared_tunnel_request_errors'),
            'requests': value('cloudflared_tunnel_total_requests'),
            'registered': sum(float(n) for n in re.findall(r'^cloudflared_tunnel_tunnel_register_success\{[^}]*\} ([\d.]+)$', out, re.M)),
            'edges': sorted(set(re.findall(r'edge_location="(\w+)"', out)))}


def host_load():
    """Load average and the three busiest processes, so a slow minute can be matched to what ran (11-11 PM:
    22:12 Explore 4-7.6 s at load 6-7 with no registered heavy job)."""
    _, out = run(['ps', '-Ao', 'pcpu=,pid=,comm='], 3)
    top = []
    for line in (out or '').splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            try:   # the pid tells which python (frontend, jobs, a test run) or which database session it was
                top.append((float(parts[0]), f"{parts[2].rsplit('/', 1)[-1][:40]}#{parts[1]}"))
            except ValueError:
                continue
    top.sort(reverse=True)
    import os
    return {'load_1': round(os.getloadavg()[0], 2), 'top': [[name, cpu] for cpu, name in top[:3]]}


def stalled_hop(r):
    """The first hop that failed or was slow, from the LAN outwards; None when the whole path was fine."""
    if r.get('gateway_ms') is None:
        return 'lan'
    if r.get('internet_ms') is None:
        return 'isp'
    if r.get('dns_ms') is None or r['dns_ms'] > SLOW_S * 1000:
        return 'dns'
    edge = r.get('edge') or {}
    if edge.get('status') != 200 or edge.get('total_s', 99) > SLOW_S:
        return 'mac_to_cloudflare'
    tun = r.get('tunnel') or {}
    if tun.get('connections') is not None and tun['connections'] < 4:
        return 'tunnel'
    public = r.get('public') or {}
    if public.get('status') != 200 or public.get('total_s', 99) > SLOW_S:
        origin = r.get('origin')
        if origin is not None and (origin.get('status') != 200 or origin.get('total_s', 99) > SLOW_S / 2):
            return 'origin'              # the local proxy or app was slow too: not the tunnel
        return 'cloudflare_to_origin'    # the origin answered locally at once (or was not probed)
    return None


def record():
    gateway, interface = default_route()
    with ThreadPoolExecutor(max_workers=7) as pool:
        jobs = {'gateway_ms': pool.submit(ping, gateway), 'internet_ms': pool.submit(ping, '1.1.1.1'),
                'dns_ms': pool.submit(dns), 'edge': pool.submit(curl, f'https://{HOST}/cdn-cgi/trace', True),
                'public': pool.submit(curl, f'https://{HOST}/robots.txt?net_path={int(time.time())}'),
                'origin': pool.submit(curl, f'{ORIGIN}/robots.txt?net_path={int(time.time())}', False, HOST),
                'tunnel': pool.submit(tunnel)}
        row = {'at': datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'), 'interface': interface,
               'port': port_name(interface) if interface else None, 'errors': counters(interface) if interface else None}
        row.update({name: job.result() for name, job in jobs.items()})
    row['host'] = host_load()
    row['stalled'] = stalled_hop(row)
    return row


def summary(rows, hours=24):
    since = (datetime.now(KST) - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    rows = [r for r in rows if r.get('at', '') >= since]
    stalls = [r for r in rows if r.get('stalled')]
    by_hop = {}
    for r in stalls:
        by_hop[r['stalled']] = by_hop.get(r['stalled'], 0) + 1
    return {'since': since, 'minutes': len(rows), 'stalled_minutes': len(stalls), 'by_hop': by_hop,
            'last': [{'at': r['at'], 'hop': r['stalled'], 'edge': r.get('edge'), 'public': r.get('public')} for r in stalls[-10:]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--summary', action='store_true')
    parser.add_argument('--hours', type=int, default=24)
    args = parser.parse_args(argv)
    if args.summary:
        rows = []
        for line in OUT.read_text().splitlines() if OUT.is_file() else []:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        print(json.dumps(summary(rows, args.hours), ensure_ascii=False, indent=1))
        return 0
    row = record()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
