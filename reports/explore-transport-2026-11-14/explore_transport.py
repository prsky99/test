import json, datetime, bisect, collections, statistics
net = []
for line in open('logs/ops/net-path.jsonl'):
    try: d = json.loads(line)
    except ValueError: continue
    try: t = datetime.datetime.strptime(d['at'], '%Y-%m-%d %H:%M:%S').timestamp()
    except Exception: continue
    net.append((t, d))
net.sort(key=lambda x: x[0]); keys = [t for t, _ in net]
def near(ts):
    i = bisect.bisect_left(keys, ts); best = None
    for j in (i - 1, i):
        if 0 <= j < len(net) and abs(net[j][0] - ts) <= 90: best = net[j][1] if best is None or abs(net[j][0]-ts) < abs(best_t-ts) else best; best_t = net[j][0]
    return best
rows = []
for line in open('logs/ops/user-slo.jsonl'):
    try: r = json.loads(line)
    except ValueError: continue
    try: at = datetime.datetime.fromisoformat(r['at']).timestamp()
    except Exception: continue
    for s in (r.get('explore') or {}).get('samples') or []:
        if s.get('tcp_s') is None or s.get('tls_s') is None or s.get('first_byte_s') is None: continue
        dns = s.get('dns_s') or 0; tcp = s['tcp_s'] - dns; tls = s['tls_s'] - s['tcp_s']
        server = (s.get('server_ms') or 0) / 1000; wait = s['first_byte_s'] - s['tls_s']; mid = max(0.0, wait - server)
        body = max(0.0, (s.get('body_s') or s['first_byte_s']) - s['first_byte_s'])
        n = near(at)
        rows.append({'at': r['at'][:16], 's': s['s'], 'dns': round(dns, 2), 'tcp': round(tcp, 2), 'tls': round(tls, 2), 'server': round(server, 2), 'edge_tunnel': round(mid, 2), 'body': round(body, 2),
                     'load': r.get('load_1_start'), 'cache': s.get('cache'), 'colo': s.get('colo'),
                     'net_edge_tls': (n or {}).get('edge', {}).get('tls_s') if n else None, 'net_edge_tcp': (n or {}).get('edge', {}).get('tcp_s') if n else None,
                     'gw_ms': (n or {}).get('gateway_ms'), 'inet_ms': (n or {}).get('internet_ms'), 'tun_err': (n or {}).get('tunnel', {}).get('request_errors') if n else None})
over = [x for x in rows if x['s'] > 3]
print('samples', len(rows), 'over3s', len(over))
def dom(x):
    parts = {'dns': x['dns'], 'tcp+tls': x['tcp'] + x['tls'], 'server': x['server'], 'edge/tunnel': x['edge_tunnel'], 'body': x['body']}
    return max(parts, key=parts.get)
print('dominant segment among >3s:', collections.Counter(dom(x) for x in over))
hs = [x for x in over if x['tcp'] + x['tls'] >= 1.5]
print('>3s with tcp+tls>=1.5:', len(hs))
print('normal tcp+tls median (<=3s samples):', statistics.median([x['tcp'] + x['tls'] for x in rows if x['s'] <= 3]))
print('tcp vs tls split in high-handshake samples: tcp median', statistics.median([x['tcp'] for x in hs]) if hs else None, 'tls median', statistics.median([x['tls'] for x in hs]) if hs else None)
print('load in high-handshake samples:', sorted(x['load'] for x in hs if x['load'] is not None))
print('load in normal samples median:', statistics.median([x['load'] for x in rows if x['s'] <= 3 and x['load'] is not None]))
for x in hs[:40]: print(x)
json.dump(rows, open('/private/tmp/claude-501/-Users-kingstonelee-workspace-A2A-Discovery/c112238f-1913-449c-8c01-1f2f99ab0f80/scratchpad/explore_transport.json', 'w'))
