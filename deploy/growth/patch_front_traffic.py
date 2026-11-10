"""11-10: pass request and response headers to the anonymous traffic counter, and tag our own
security blocks (blocked_ip, policy_denied) so 4xx counts show them by cause (idempotent).

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
if 'request.headers, response.headers' not in s:
    assert s.count(old) == 1, 'traffic call not found'
    s = s.replace(old, new)
call = ("                               request.headers, response.headers)\n")
tagged = ("                               request.headers, response.headers,\n"
          "                               cause=request.scope.get('traffic_cause'))\n")
if tagged not in s:
    assert s.count(call) == 1, 'traffic headers call not found'
    s = s.replace(call, tagged)
for marker, cause in (('"error_code":"ACCESS_BLOCKED"', 'blocked_ip'), ('"error_code":"REQUEST_POLICY_DENIED"', 'policy_denied')):
    line = '            return JSONResponse({"audience":AUDIENCE,' + marker
    flag = "            request.scope['traffic_cause'] = '" + cause + "'\n"
    assert line in s, marker
    s = s.replace(flag + line, line).replace(line, flag + line)  # every such reply, tagged once
open(p, 'w', encoding='utf-8').write(s)
print('patched', p)
