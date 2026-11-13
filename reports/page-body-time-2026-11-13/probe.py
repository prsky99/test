"""Public HTML: headers, compressed size and when each chunk of the body arrives (new connection per sample)."""
import json, sys, time
sys.path.insert(0, '/Users/kingstonelee/workspace/A2A_Discovery')
from scripts.user_slo import on_fresh, phases, BASE
paths = sys.argv[2:] or ['/', '/new/en/chat.html', '/new/en/explore.html']
n = int(sys.argv[1])
out = []
for i in range(n):
    for path in paths:
        def get(c):
            t0 = time.monotonic(); chunks = []; size = 0
            with c.stream('GET', BASE + path, headers={'Accept': 'text/html'}) as r:
                th = time.monotonic() - t0
                for b in r.iter_raw():
                    size += len(b); chunks.append((round(time.monotonic() - t0, 3), size))
                h = {k: r.headers.get(k) for k in ('cf-cache-status', 'cache-control', 'age', 'content-encoding', 'content-length', 'cf-ray', 'server-timing', 'x-edge-origin-output', 'last-modified', 'etag', 'vary')}
            return r.status_code, h, size, th, chunks
        t = time.monotonic(); st, h, size, th, chunks = on_fresh(get); tot = time.monotonic() - t
        ph = phases()
        row = {'i': i, 'path': path, 's': round(tot, 3), 'status': st, 'wire_bytes': size, 'chunks': len(chunks),
               'tls_s': ph.get('tls_s'), 'headers_s': ph.get('first_byte_s'),
               'first_chunk_s': chunks[0][0] if chunks else None, 'last_chunk_s': chunks[-1][0] if chunks else None,
               'chunk_times': chunks[:3] + chunks[-3:], 'gap': max(((round(b[0]-a[0],3), a[1]) for a,b in zip(chunks, chunks[1:])), default=None), **h}
        out.append(row)
        print(path, row['s'], st, h['cf-cache-status'], h['content-encoding'], size, 'tls', row['tls_s'], 'hdr', row['headers_s'],
              'first', row['first_chunk_s'], 'last', row['last_chunk_s'], 'chunks', len(chunks), 'age', h['age'], 'gap(s,bytes_before)', row['gap'], flush=True)
        time.sleep(1)
json.dump(out, open(__file__.replace('probe.py', f'probe-{time.strftime("%H%M")}.json'), 'w'), indent=1)
