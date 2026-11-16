"""TLS 0-RTT early data at the edge (RFC 8470), for routes that must not run twice (11-16, PM: 0-RTT on the zone).

Cloudflare accepts 0-RTT for GET, HEAD and OPTIONS and marks such a request with `Early-Data: 1` on its way to us
(developers.cloudflare.com/speed/optimization/protocol/0-rtt-connection-resumption/). Early data can be replayed, so a
GET that spends a one-use value (an OAuth state or code) answers 425 Too Early before touching it; the client sends
the same request again after the handshake, without the header, and that one is handled as before.
"""
from fastapi.responses import Response


def is_early(request):
    return request.headers.get('early-data', '').strip() == '1'


def too_early(request):
    """A 425 response when REQUEST came as TLS early data, else None. Nothing of the request is read or spent."""
    if not is_early(request):
        return None
    return Response(status_code=425, headers={'Cache-Control': 'no-store', 'Retry-After': '0'})
