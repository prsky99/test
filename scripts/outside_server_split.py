"""Split the public response time outside the server into three parts, by hour (PM 11-13 10:3x).

After the 11-13 09:35 align bundle the server time stayed the same (explore 770 -> 795 ms) while the time
outside it grew (explore 0.87 -> 1.31 s, find_agents 0.93 -> 1.23 s); 11-12 showed the same daytime shape with
no deploy. This reads the two measurements we already keep and splits that outside time:

  client_edge  DNS + TCP + TLS to the Cloudflare edge          (curl time_appconnect, cumulative)
  edge_origin  first byte wait minus the server's own time      (request send, edge work, cloudflared tunnel,
                                                                 the origin outside the app's Server-Timing)
  body         first byte to last byte                          (transfer of the answer)

Sources (read only):
  logs/ops/user-slo.jsonl   hourly public samples with Server-Timing (explore, recommend, pages)
  logs/ops/net-path.jsonl   one probe a minute: /cdn-cgi/trace (edge only) and /robots.txt (origin, near zero
                            server time); c2o = (robots first byte - TLS) - (trace first byte - TLS)

Nothing is excluded: every sample with the timing fields counts. The numbers explain where the time goes; they
do not change any target verdict.

    .venv/bin/python -m scripts.outside_server_split --since "2026-11-12 00:00" --out logs/ops/outside-server-2026-11-14
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('explore', 'recommend', 'pages')


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[index]


def split_sample(sample):
    """The three outside parts of one user_slo sample, or None when a timing field is missing."""
    try:
        tls, first, body_end = float(sample['tls_s']), float(sample['first_byte_s']), float(sample['body_s'])
        server = float(sample['server_ms']) / 1000.0
    except (KeyError, TypeError, ValueError):
        return None
    return {'total': body_end, 'server': server, 'client_edge': tls,
            'edge_origin': first - tls - server, 'body': body_end - first,
            'outside': body_end - server, 'colo': sample.get('colo') or ''}


def split_probe(row):
    """net_path minute: client->edge, edge-only wait, and the origin trip (c2o) of a near-zero-work request."""
    edge, public = row.get('edge') or {}, row.get('public') or {}
    try:
        if edge.get('status') != 200 or public.get('status') != 200:
            return None
        edge_wait = float(edge['first_byte_s']) - float(edge['tls_s'])
        public_wait = float(public['first_byte_s']) - float(public['tls_s'])
        return {'client_edge': float(public['tls_s']), 'edge_wait': edge_wait, 'c2o': public_wait - edge_wait,
                'body': float(public['total_s']) - float(public['first_byte_s']), 'colo': edge.get('colo') or ''}
    except (KeyError, TypeError, ValueError):
        return None


def read_jsonl(path, since, until):
    rows = []
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = str(row.get('at', ''))[:16]
        if since <= at and (not until or at < until):
            rows.append(row)
    return rows


def summarize(parts, keys):
    out = {'n': len(parts)}
    for key in keys:
        values = [p[key] for p in parts]
        out[key] = {'p50': quantile(values, 0.5), 'p90': quantile(values, 0.9)}
    return out


def slo_table(rows):
    """{kind: {(date, hour): summary}} plus whole-window totals and the colo mix."""
    keys = ('total', 'server', 'outside', 'client_edge', 'edge_origin', 'body')
    by_hour, whole, colos = defaultdict(lambda: defaultdict(list)), defaultdict(list), defaultdict(lambda: defaultdict(int))
    for row in rows:
        at = str(row['at'])
        for kind in KINDS:
            for sample in (row.get(kind) or {}).get('samples') or []:
                part = split_sample(sample)
                if part is None:
                    continue
                by_hour[kind][(at[:10], at[11:13])].append(part)
                whole[kind].append(part)
                colos[kind][part['colo'] or '?'] += 1
    return ({kind: {key: summarize(v, keys) for key, v in sorted(hours.items())} for kind, hours in by_hour.items()},
            {kind: summarize(v, keys) for kind, v in whole.items()}, {k: dict(v) for k, v in colos.items()})


def probe_table(rows):
    keys = ('client_edge', 'edge_wait', 'c2o', 'body')
    by_hour, by_colo = defaultdict(list), defaultdict(list)
    for row in rows:
        part = split_probe(row)
        if part is None:
            continue
        by_hour[(row['at'][:10], row['at'][11:13])].append(part)
        by_colo[part['colo'] or '?'].append(part)
    return ({key: summarize(v, keys) for key, v in sorted(by_hour.items())},
            {colo: summarize(v, keys) for colo, v in sorted(by_colo.items())})


def ms(value):
    return '-' if value is None else '%d' % round(value * 1000)


def markdown(result):
    lines = ['# Time outside the server, split in three (%s ~ %s)' % (result['since'], result['until'] or 'now'), '',
             'Medians in ms (p90 in brackets). outside = total - server = client_edge + edge_origin + body.',
             'No sample is excluded; this explains the time and does not change any verdict.', '']
    lines += ['## Night vs day (medians, ms)', '',
              '| what | band | n | total | server | outside | client->edge | edge->origin | body |', '|---|---|---|---|---|---|---|---|---|']
    for kind, bands in result['slo_bands'].items():
        for b, s in sorted(bands.items(), reverse=True):
            lines.append('| user_slo %s | %s | %d | %s | %s | %s | %s | %s | %s |' % (
                kind, b, s['n'], ms(s['total']['p50']), ms(s['server']['p50']), ms(s['outside']['p50']),
                ms(s['client_edge']['p50']), ms(s['edge_origin']['p50']), ms(s['body']['p50'])))
    lines += ['', '| net_path | band | n | client->edge | edge-only wait (RTT) | c2o | body |', '|---|---|---|---|---|---|---|']
    for b, s in sorted(result['probe_bands'].items(), reverse=True):
        lines.append('| robots vs trace | %s | %d | %s (p90 %s) | %s | %s (p90 %s) | %s |' % (
            b, s['n'], ms(s['client_edge']['p50']), ms(s['client_edge']['p90']), ms(s['edge_wait']['p50']),
            ms(s['c2o']['p50']), ms(s['c2o']['p90']), ms(s['body']['p50'])))
    lines += ['']
    lines += ['edge->origin holds one client<->edge round trip (the request itself). "of which RTT" is that hour\'s',
              'net_path edge-only wait (/cdn-cgi/trace, no origin); "tunnel+origin" = edge->origin minus it. That is an',
              'estimate across two measurements (one user_slo minute vs the hour\'s probe median): a negative value is',
              'that noise. Read the night/day table for the comparison.', '']
    for kind, whole in result['slo_whole'].items():
        lines += ['## user_slo %s (n=%d, colo %s)' % (kind, whole['n'], result['slo_colos'].get(kind)), '',
                  '| date hour | n | total | server | outside | client->edge | edge->origin | of which RTT | tunnel+origin | body |',
                  '|---|---|---|---|---|---|---|---|---|---|']
        for (date, hour), s in result['slo_hours'][kind].items():
            probe = result['probe_hours'].get((date, hour))
            rtt = probe['edge_wait']['p50'] if probe else None
            rest = s['edge_origin']['p50'] - rtt if rtt is not None else None
            lines.append('| %s %s | %d | %s | %s | %s | %s (%s) | %s (%s) | %s | %s | %s |' % (
                date[5:], hour, s['n'], ms(s['total']['p50']), ms(s['server']['p50']), ms(s['outside']['p50']),
                ms(s['client_edge']['p50']), ms(s['client_edge']['p90']), ms(s['edge_origin']['p50']),
                ms(s['edge_origin']['p90']), ms(rtt), ms(rest), ms(s['body']['p50'])))
        lines.append('| whole | %d | %s | %s | %s | %s | %s | - | - | %s |' % (
            whole['n'], ms(whole['total']['p50']), ms(whole['server']['p50']), ms(whole['outside']['p50']),
            ms(whole['client_edge']['p50']), ms(whole['edge_origin']['p50']), ms(whole['body']['p50'])))
        lines.append('')
    lines += ['## Stalled minutes by hop (net_path)', '',
              '"origin": the local probe (127.0.0.1:8400) was slow too; "cloudflare_to_origin": the origin answered',
              'locally at once, or was not probed yet (before 11-13 16:28); "mac_or_cloudflare_to_origin": as',
              'before, but the request\'s own TLS with the edge took over 1 s, so this Mac\'s leg is in play too',
              '(from 11-13 18:3x; earlier rows keep the older label).', '']
    for b, counts in sorted(result.get('stalls', {}).items(), reverse=True):
        lines.append('- %s: %s' % (b, ', '.join('%s %d' % (k, v) for k, v in sorted(counts.items()))))
    lines += ['']
    lines += ['## net_path one probe a minute (robots.txt vs edge-only trace)', '',
              '| date hour | n | client->edge | edge-only wait | c2o (tunnel+origin) | body |', '|---|---|---|---|---|---|']
    for (date, hour), s in result['probe_hours'].items():
        lines.append('| %s %s | %d | %s (%s) | %s | %s (%s) | %s |' % (
            date[5:], hour, s['n'], ms(s['client_edge']['p50']), ms(s['client_edge']['p90']), ms(s['edge_wait']['p50']),
            ms(s['c2o']['p50']), ms(s['c2o']['p90']), ms(s['body']['p50'])))
    lines += ['', '| colo | n | client->edge | edge-only wait | c2o | body |', '|---|---|---|---|---|---|']
    for colo, s in result['probe_colos'].items():
        lines.append('| %s | %d | %s | %s | %s | %s |' % (colo, s['n'], ms(s['client_edge']['p50']),
                                                      ms(s['edge_wait']['p50']), ms(s['c2o']['p50']), ms(s['body']['p50'])))
    return '\n'.join(lines) + '\n'


def band(hour):
    """01-08 KST is the quiet path (net_side 11-13: TLS spikes 2.1% vs 20-32% in the day)."""
    return 'night 01-08' if 1 <= int(hour) <= 8 else 'day 09-24'


def band_table(slo_rows, probe_rows):
    slo, probe = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    for row in slo_rows:
        for kind in KINDS:
            for sample in (row.get(kind) or {}).get('samples') or []:
                part = split_sample(sample)
                if part:
                    slo[kind][band(str(row['at'])[11:13])].append(part)
    for row in probe_rows:
        part = split_probe(row)
        if part:
            probe[band(row['at'][11:13])].append(part)
    keys = ('total', 'server', 'outside', 'client_edge', 'edge_origin', 'body')
    return ({kind: {b: summarize(v, keys) for b, v in bands.items()} for kind, bands in slo.items()},
            {b: summarize(v, ('client_edge', 'edge_wait', 'c2o', 'body')) for b, v in probe.items()})


def stall_table(probe_rows):
    """Stalled minutes by hop and band (net_path.stalled_hop). 'origin' exists from 11-13 16:28 (local probe):
    before that a stall past the edge is 'cloudflare_to_origin' whether the tunnel or the origin held it."""
    by_band, probed = defaultdict(lambda: defaultdict(int)), defaultdict(int)
    for row in probe_rows:
        b = band(row['at'][11:13])
        probed[b] += 1
        if row.get('origin') is not None:
            by_band[b]['(local origin probed)'] += 1
        if row.get('stalled'):
            by_band[b][row['stalled']] += 1
    return {b: dict(by_band[b], minutes=probed[b]) for b in probed}


def build(slo_path, probe_path, since, until=''):
    slo_rows, probe_rows = read_jsonl(slo_path, since, until), read_jsonl(probe_path, since, until)
    slo_hours, slo_whole, slo_colos = slo_table(slo_rows)
    probe_hours, probe_colos = probe_table(probe_rows)
    slo_bands, probe_bands = band_table(slo_rows, probe_rows)
    return {'stalls': stall_table(probe_rows), 'since': since, 'until': until, 'slo_hours': slo_hours, 'slo_whole': slo_whole, 'slo_colos': slo_colos,
            'probe_hours': probe_hours, 'probe_colos': probe_colos, 'slo_bands': slo_bands, 'probe_bands': probe_bands}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--since', required=True, help='KST "YYYY-MM-DD HH:MM"')
    parser.add_argument('--until', default='')
    parser.add_argument('--slo', default=str(ROOT / 'logs/ops/user-slo.jsonl'))
    parser.add_argument('--probes', default=str(ROOT / 'logs/ops/net-path.jsonl'))
    parser.add_argument('--out', help='path prefix; writes <out>.md and <out>.json')
    args = parser.parse_args(argv)
    result = build(args.slo, args.probes, args.since, args.until)
    text = markdown(result)
    if args.out:
        Path(args.out + '.md').write_text(text)
        flat = dict(result, slo_hours={k: {' '.join(h): s for h, s in v.items()} for k, v in result['slo_hours'].items()},
                    probe_hours={' '.join(h): s for h, s in result['probe_hours'].items()})
        Path(args.out + '.json').write_text(json.dumps(flat, indent=1))
    print(text)


if __name__ == '__main__':
    main()
