"""/registry: what the verified MCP registry lists, what it leaves out and how an organization uses it (E7, 11-18).

Facts from the agent team (docs/VERIFIED_REGISTRY.md, 043ceed3). The GitHub Copilot steps follow GitHub's own page
(docs.github.com, "Restrict MCP server access to a custom registry"); a client setting not confirmed in its official
documentation is not described. The disclaimer is the agent team's exact sentence. Linked from /methodology.
"""
import html

BASE = 'https://agentconcierge.biz/registry/verified'
GITHUB_DOC = 'https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-mcp-usage/configure-mcp-server-access'
DISCLAIMER = ('Checked by AgentValCon with keyless read-only tool calls. Not affiliated with or endorsed by the MCP '
              "Registry; server names and texts are the publishers' own.")
# Matched with verified_registry.exclusion_reason by the agent team (11-15).
REASONS = [('no_recent_success', 'no successful keyless tool call in the last 7 days'),
           ('definition_risk', 'a risk signal in its tool definitions in the last 30 days'),
           ('requires_credentials', 'every remote endpoint requires a header such as an API key'),
           ('entry_not_valid', 'its name, description (1 to 100 characters) or version does not fit the official '
                               'format, or it has no public HTTPS remote endpoint'),
           ('left_catalog_criteria', 'no longer grade A and healthy, or no longer in the official registry')]
CHANGES = BASE + '/v0.1/x/biz.agentconcierge/changes'


def page_html(base='https://agentconcierge.biz'):
    from .growth_pages import ORIGIN, heading, shell
    esc = lambda value: html.escape(str(value), quote=True)
    li = lambda items: '<ul>' + ''.join('<li>' + item + '</li>' for item in items) + '</ul>'
    parts = [heading('Registry · Agent Value Gateway', 'Verified MCP registry',
                     'A read-only registry in the format of the official MCP Registry API v0.1 that lists only remote '
                     'MCP servers we have called successfully without a key.'),
             '<section aria-labelledby="rWhat"><h2 id="rWhat">Address</h2><p>Base URL: <code>' + esc(BASE) + '</code>. '
             'Clients add <code>/v0.1/servers</code> themselves. The current number of servers is '
             '<code>verified_registry.listed</code> in <a href="/status.json">/status.json</a>.</p></section>',
             '<section aria-labelledby="rIn"><h2 id="rIn">What is listed</h2><p>A server is listed only when all of these '
             'hold:</p>' + li([
                 'It is a remote server in the official MCP Registry.',
                 'Its quality grade is A and its health is healthy.',
                 'We called one of its tools successfully, without a key, in the last 7 days.',
                 'It needs no authentication header (optional headers stay as the publisher wrote them).',
                 'No risk signal in its tool definitions in the last 30 days. Until that check runs, entries say '
                 '&quot;not checked yet&quot;.']) + '</section>',
             '<section aria-labelledby="rOut"><h2 id="rOut">When a server leaves</h2><p>A server that no longer meets the '
             'criteria is left out of the next snapshot (snapshots are made every hour), and the changes feed records '
             'why:</p>' + li(['<code>' + esc(code) + '</code>: ' + esc(text) for code, text in REASONS])
             + '<p>Changes feed (JSON Feed 1.1): <a href="' + esc(CHANGES) + '"><code>' + esc(CHANGES) + '</code></a>. '
             'Listings, delistings with a reason, and tool-definition changes (names only).</p></section>',
             '<section aria-labelledby="rSame"><h2 id="rSame">What stays the publisher&#39;s</h2><p>Server names, '
             'descriptions, versions and addresses are the publishers&#39; own text from the official registry. Our facts '
             'are only under <code>_meta</code> &quot;biz.agentconcierge/verification&quot;: the last successful call, '
             'the tool we called, the grade and the evidence page. Listing is never paid for; owning or paying for an '
             'agent is not a criterion, and there are no paid ranks or badges.</p></section>',
             '<section aria-labelledby="rUse"><h2 id="rUse">Use it in GitHub Copilot</h2><ol>'
             '<li>In your organization settings, open Copilot, then Policies.</li>'
             '<li>Set &quot;MCP servers in Copilot&quot; to Enabled.</li>'
             '<li>In &quot;MCP Registry URL&quot;, enter <code>' + esc(BASE) + '</code> (the base URL only).</li>'
             '<li>Under &quot;Restrict MCP access to registry servers&quot;, choose &quot;Registry only&quot; to allow '
             'only listed servers, or &quot;Allow all&quot;.</li></ol>'
             '<p class="muted">GitHub describes this as a public preview; &quot;Registry only&quot; matches servers by '
             'name and also turns off Copilot connectors. See <a href="' + esc(GITHUB_DOC) + '" rel="noopener">GitHub&#39;s '
             'instructions</a>.</p></section>',
             '<section aria-labelledby="rNote"><h2 id="rNote">Source and notice</h2><p>' + esc(DISCLAIMER) + '</p>'
             '<p class="muted">Official MCP Registry data is published under CC0 1.0. How we test agents: '
             '<a href="/methodology">our method</a>.</p></section>']
    structured = {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'Verified MCP registry',
                  'url': ORIGIN + '/registry', 'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': ORIGIN + '/'}}
    return shell(title='Verified MCP registry | AgentValCon',
                 description='A read-only MCP registry (API v0.1) of remote servers we called successfully without a key.',
                 canonical=ORIGIN + '/registry', body='<div class="pearl-page">' + ''.join(parts) + '</div>',
                 structured=structured, index=True)


def registry_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse
    from .growth_pages import PAGE_CSP
    router = APIRouter()

    @router.get('/registry', include_in_schema=False)
    def page():
        return HTMLResponse(page_html(), headers={'Content-Security-Policy': PAGE_CSP})

    return router
