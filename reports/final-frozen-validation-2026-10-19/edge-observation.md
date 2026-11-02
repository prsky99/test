# Public edge observation — 2026-10-19

Default Python urllib requests returned403 on the public homepage, presets API
and agent-card discovery. The same agent-card request returned200 locally and
with the explicit AgentConcierge-Acceptance/1.0 User-Agent over public HTTPS.
A browser-like public homepage request returned200 with operating HTML,
CSP/no-store/nosniff/HSTS. Actual response evidence is in public-http-recheck.json
and public-agent-discovery.json.

The public error explicitly reports Cloudflare1010: blocked browser signature.
Cloudflare documents1010 and Browser Integrity Check behavior here:
https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/
https://developers.cloudflare.com/waf/tools/browser-integrity-check/

The observed distinction is an edge policy compatibility condition. It is not
proof that all API clients fail or that the origin application denies requests.
No Cloudflare account setting was inspected or changed. Operator review is
needed if generic library clients must work without explicit client identity.
Any exception should be limited to approved machine-protocol paths while
retaining application authentication, consent, SSRF controls, rate limits and
other edge protections. Do not disable all edge security or treat User-Agent
as an authentication credential. No configuration exception is applied here.
