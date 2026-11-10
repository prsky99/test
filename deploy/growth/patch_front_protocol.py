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
open(p, 'w', encoding='utf-8').write(s)
print('patched', p)
