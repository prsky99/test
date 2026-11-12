"""One line a minute beside net_path: is this Mac's own line the bottleneck? (PM 11-12 14:3x, read only)

    .venv/bin/python -m scripts.net_side [--until "2026-11-13 08:30"] [--once]

Daytime samples measured from this Mac showed TLS stalls in steps of about one second and long body stalls while
TCP stayed at 0.14 s, the shape of packet loss and retransmission. Visitors do not use this line, so if its upload
is full (the owner uses Chrome Remote Desktop all day, which sends the screen up), our own measurements read worse
than the site is. Each minute this records, at the same moment:
- interface bytes in/out since the last line (netstat -ib) and TCP retransmitted packets/bytes (netstat -s)
- ping loss and delay to the first hop and to 1.1.1.1 (10 packets each)
- Chrome Remote Desktop host processes: CPU, open network sockets, bytes in/out (nettop); never touched
- cloudflared bytes in/out (nettop)
Nothing is changed. Lines go to logs/ops/net-side.jsonl.
"""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/net-side.jsonl'
REMOTE = 'ChromeRemoteDesktopHost'


def run(args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ''


def default_route(text=None):
    text = run(['route', '-n', 'get', 'default']) if text is None else text
    gateway = re.search(r'gateway:\s*(\S+)', text)
    interface = re.search(r'interface:\s*(\S+)', text)
    return (gateway.group(1) if gateway else None), (interface.group(1) if interface else None)


def interface_bytes(interface, text=None):
    text = run(['netstat', '-ib', '-I', interface]) if text is None else text
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 10 and parts[0] == interface and parts[2].startswith('<Link'):
            return {'ibytes': int(parts[6]), 'obytes': int(parts[9]), 'ierrs': int(parts[5]) if parts[5].isdigit() else 0,
                    'oerrs': int(parts[8]) if parts[8].isdigit() else 0}
    return None


def tcp_retransmits(text=None):
    text = run(['netstat', '-s', '-p', 'tcp']) if text is None else text
    found = re.search(r'(\d+) data packets? \((\d+) bytes?\) retransmitted', text)
    timeouts = re.search(r'(\d+) retransmit timeouts?', text)
    return {'packets': int(found.group(1)) if found else None, 'bytes': int(found.group(2)) if found else None,
            'timeouts': int(timeouts.group(1)) if timeouts else None}


def ping(host, text=None):
    text = run(['ping', '-c', '10', '-i', '0.2', '-q', '-t', '8', host], timeout=15) if text is None else text
    loss = re.search(r'([\d.]+)% packet loss', text)
    rtt = re.search(r'= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', text)
    return {'loss_pct': float(loss.group(1)) if loss else None,
            'avg_ms': float(rtt.group(2)) if rtt else None, 'max_ms': float(rtt.group(3)) if rtt else None}


def pids(pattern):
    return [int(p) for p in run(['pgrep', '-f', pattern]).split() if p.isdigit()]


def process_bytes(pid_list, text=None):
    """{pid: (bytes_in, bytes_out)} from one nettop sample (cumulative per process)."""
    if text is None:
        if not pid_list:
            return {}
        args = ['nettop', '-P', '-L', '1', '-n', '-J', 'bytes_in,bytes_out']
        for pid in pid_list:
            args += ['-p', str(pid)]
        text = run(args)
    out = {}
    for line in text.splitlines():
        found = re.match(r'(.+)\.(\d+),(\d+),(\d+),', line)
        if found:
            out[int(found.group(2))] = (int(found.group(3)), int(found.group(4)))
    return out


def cpu(pid_list):
    if not pid_list:
        return 0.0
    text = run(['ps', '-o', '%cpu=', '-p', ','.join(map(str, pid_list))])
    return round(sum(float(v) for v in text.split() if re.fullmatch(r'[\d.]+', v)), 1)


def sockets(pid_list):
    if not pid_list:
        return 0
    text = run(['lsof', '-nP', '-a', '-i', '-p', ','.join(map(str, pid_list))])
    return max(0, len(text.splitlines()) - 1)


def delta(now, before):
    if now is None or before is None:
        return None
    return {k: (now[k] - before[k]) if isinstance(now.get(k), int) and isinstance(before.get(k), int) else None
            for k in now}


def sample(previous):
    gateway, interface = default_route()
    remote = pids(REMOTE)
    tunnel = pids('cloudflared')
    counters = {'iface': interface_bytes(interface) if interface else None, 'tcp': tcp_retransmits(),
                'proc': process_bytes(remote + tunnel)}
    remote_bytes = [counters['proc'].get(p) for p in remote if p in counters['proc']]
    tunnel_bytes = [counters['proc'].get(p) for p in tunnel if p in counters['proc']]
    sums = {'remote': (sum(b[0] for b in remote_bytes), sum(b[1] for b in remote_bytes)) if remote_bytes else None,
            'tunnel': (sum(b[0] for b in tunnel_bytes), sum(b[1] for b in tunnel_bytes)) if tunnel_bytes else None}
    line = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'interface': interface,
            'iface': delta(counters['iface'], previous.get('iface')), 'tcp_retransmit': delta(counters['tcp'], previous.get('tcp')),
            'ping_gateway': ping(gateway) if gateway else None, 'ping_1111': ping('1.1.1.1'),
            'remote_desktop': {'pids': len(remote), 'cpu_pct': cpu(remote), 'sockets': sockets(remote)}, 'seconds': None}
    for name in ('remote', 'tunnel'):
        now_sum, before = sums[name], previous.get(name)
        moved = ({'in': now_sum[0] - before[0], 'out': now_sum[1] - before[1]}
                 if now_sum and before and now_sum[0] >= before[0] and now_sum[1] >= before[1] else None)
        if name == 'remote':
            line['remote_desktop']['bytes'] = moved
        else:
            line['cloudflared_bytes'] = moved
    if previous.get('t'):
        line['seconds'] = round(time.time() - previous['t'], 1)
    state = {'iface': counters['iface'], 'tcp': counters['tcp'], 'remote': sums['remote'], 'tunnel': sums['tunnel'],
             't': time.time()}
    return line, state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--until', default=None)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    until = datetime.strptime(args.until, '%Y-%m-%d %H:%M').timestamp() if args.until else None
    state = {}
    _, state = sample(state)          # first counters only; the first line has real differences
    while True:
        next_at = time.time() + 60
        time.sleep(max(0.0, next_at - time.time()))
        line, state = sample(state)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, 'a') as stream:
            stream.write(json.dumps(line) + '\n')
        if args.once or (until and time.time() >= until):
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
