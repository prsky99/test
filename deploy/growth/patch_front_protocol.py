"""11-10: first-call fixes for MCP and A2A clients (idempotent).

- POST /mcp/ and /a2a/ (trailing slash) are answered directly instead of a 307 redirect that
  some clients do not follow for POST.
- MCP resources/list, resources/templates/list and prompts/list return empty lists instead of
  -32601; several clients call them at start-up even when the capabilities do not list them.

    python deploy/growth/patch_front_protocol.py <front.py>
"""
import sys

p = sys.argv[1]
s = open(p, encoding='utf-8').read()
NL = '\n'

a2a = '    @router.post("/a2a")' + NL + '    async def a2a(request: Request):' + NL
if '@router.post("/a2a/", include_in_schema=False)' not in s:
    assert s.count(a2a) == 1, 'a2a route not found'
    s = s.replace(a2a, '    @router.post("/a2a")' + NL + '    @router.post("/a2a/", include_in_schema=False)' + NL
                  + '    async def a2a(request: Request):' + NL)

mcp = '    @router.post("/mcp")' + NL + '    async def mcp(request: Request):' + NL
if '@router.post("/mcp/", include_in_schema=False)' not in s:
    assert s.count(mcp) == 1, 'mcp route not found'
    s = s.replace(mcp, '    @router.post("/mcp")' + NL + '    @router.post("/mcp/", include_in_schema=False)' + NL
                  + '    async def mcp(request: Request):' + NL)

old = ('        if method != "tools/call":' + NL
       + '            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}}' + NL)
new = ('        if method in ("resources/list", "resources/templates/list", "prompts/list"):' + NL
       + '            # 11-10: clients probe these at start-up; this server offers tools only, so the lists are empty.' + NL
       + '            return mcp_result(rid, {{"resources/list": "resources", "resources/templates/list": "resourceTemplates",' + NL
       + '                                    "prompts/list": "prompts"}[method]: []})' + NL + old)
if '"resources/templates/list": "resourceTemplates"' not in s:
    assert s.count(old) == 1, 'mcp method-not-found branch not found'
    s = s.replace(old, new)
# 11-11: clients on a newer (draft) MCP revision send its date in MCP-Protocol-Version on the version
# negotiation calls too (initialize, server/discover). Those calls are answered with the versions we
# support so the client can pick one; every other method keeps the 400 the transport requires, now
# with the supported list in error.data.
check = ('        version = request.headers.get("mcp-protocol-version")' + NL
         + '        if version is not None and version.strip() not in MCP_VERSIONS:' + NL
         + '            # Streamable HTTP: an unsupported protocol version header is a 400 Bad Request.' + NL
         + '            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600,' + NL
         + '                "message": "Unsupported MCP-Protocol-Version. Supported: " + ", ".join(MCP_VERSIONS) + "."}}, status_code=400)' + NL)
deferred = ('        version = request.headers.get("mcp-protocol-version")' + NL
            + '        # Checked after parsing: initialize and server/discover negotiate the version (11-11).' + NL
            + '        unsupported_version = version is not None and version.strip() not in MCP_VERSIONS' + NL)
parsed = ('        if not isinstance(params, dict) or not isinstance(method, str):' + NL
          + '            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "method must be a string and params must be an object."}}' + NL
          + '        session = request.headers.get("mcp-session-id")' + NL)
gate = (parsed.rsplit('        session', 1)[0]
        + '        if unsupported_version and method not in ("initialize", "server/discover"):' + NL
        + '            # Streamable HTTP: an unsupported protocol version header is a 400 Bad Request.' + NL
        + '            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32600,' + NL
        + '                "message": "Unsupported MCP-Protocol-Version. Supported: " + ", ".join(MCP_VERSIONS) + ".",' + NL
        + '                "data": {"supported": list(MCP_VERSIONS), "requested": version.strip()[:40]}}}, status_code=400)' + NL
        + '        session = request.headers.get("mcp-session-id")' + NL)
if 'unsupported_version = version is not None' not in s:
    assert s.count(check) == 1, 'version check not found'
    assert s.count(parsed) == 1, 'parse check not found'
    s = s.replace(check, deferred).replace(parsed, gate)
discover_at = s.find('    if method == "server/discover":')
assert discover_at > 0, 'server/discover branch not found'
pv = '                "protocolVersion": asked if asked in MCP_VERSIONS else MCP_VERSIONS[0],' + NL
if '"supportedVersions": list(MCP_VERSIONS)' not in s:
    at = s.index(pv, discover_at)  # the first result after the server/discover branch
    s = s[:at] + pv + '                "supportedVersions": list(MCP_VERSIONS),' + NL + s[at + len(pv):]
open(p, 'w', encoding='utf-8').write(s)
print('patched', p)
