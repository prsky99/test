"""11-10: pass request and response headers to the anonymous traffic counter (idempotent).

Used when overlaying front.py onto the active release: python deploy/growth/patch_front_traffic.py <front.py>
"""
import sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
old = ("            recorder().observe(request.method, request.url.path, response.status_code, client_ip,\n"
       "                               request.headers.get('user-agent', ''), getattr(request, '_body', None))\n")
new = ("            recorder().observe(request.method, request.url.path, response.status_code, client_ip,\n"
       "                               request.headers.get('user-agent', ''), getattr(request, '_body', None),\n"
       "                               request.headers, response.headers)\n")
if new not in s:
    assert s.count(old) == 1, 'traffic call not found'
    s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('patched', p)
