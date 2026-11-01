"""Reconstructed agent-type scenario plan; each execution boundary is explicit."""

# A type is an interaction role, not an exclusive product/vendor classification.
GROUPS = (
    ('crawler', (
        ('robots-readable', 'Read robots.txt rules', 'live'),
        ('robots-head', 'HEAD agrees with robots GET', 'live'),
        ('sitemap-xml', 'Parse the public sitemap', 'live'),
        ('category-links', 'Follow sitemap category links', 'live'),
        ('category-expiry', 'Keep category pages stable after evidence expiry', 'isolated'),
        ('category-escaping', 'Escape untrusted category listing text', 'isolated'),
        ('private-access', 'Enforce authentication independently of robots rules', 'isolated'),
        ('real-indexing', 'Confirm actual search engine indexing', 'manual'),
    )),
    ('llm-browsing', (
        ('llms-readable', 'Read the concise LLM guide', 'live'),
        ('llms-full', 'Read the expanded LLM guide', 'live'),
        ('llms-head', 'HEAD agrees with LLM document GET', 'live'),
        ('entry-guide', 'Read the machine entry document', 'live'),
        ('skill-guide', 'Read the skill document', 'live'),
        ('count-definitions', 'Distinguish catalog and execution verification counts', 'source'),
        ('prompt-injection', 'Treat external tool descriptions as untrusted data', 'isolated'),
        ('vendor-session', 'Verify an actual third-party browsing agent session', 'manual'),
    )),
    ('browser', (
        ('allowed-cors', 'Complete trusted-origin preflight over TLS', 'isolated'),
        ('origin-denial', 'Deny execution tools to untrusted browser origins', 'live'),
        ('header-exposure', 'Expose session headers only to trusted browser origins', 'isolated'),
        ('csp', 'Apply CSP to actual browser rendering', 'isolated'),
        ('responsive', 'Operate Chat at mobile viewport sizes', 'isolated'),
        ('local-network', 'Separate local network permission from CORS', 'isolated'),
    )),
    ('coding', (
        ('manifest', 'Discover the MCP manifest', 'live'),
        ('python-client', 'Use the Python remote discovery client', 'isolated'),
        ('node-client', 'Use the Node remote discovery client', 'isolated'),
        ('schema-name', 'Use advertised task/protocol argument names', 'isolated'),
        ('alias-conflict', 'Reject conflicting legacy argument aliases', 'isolated'),
        ('private-isolation', 'Keep private workspace authority out of public agents', 'isolated'),
    )),
    ('mcp', (
        ('initialize', 'Negotiate an implemented protocol revision', 'live'),
        ('tools-list', 'Read the bounded tool list', 'live'),
        ('annotations', 'Inspect optional tool behavioral annotations', 'live'),
        ('output-schema', 'Inspect optional output schemas', 'live'),
        ('seoul-weather', 'Select weather tools for a Seoul forecast', 'live'),
        ('follow-details', 'Resume MCP discovery through a detail request', 'live'),
        ('no-sse', 'Accept documented SSE absence instead of a false failure', 'live'),
        ('invalid-cursor', 'Reject invented tool-list continuation cursors', 'isolated'),
    )),
    ('a2a', (
        ('card', 'Discover the A2A agent card', 'live'),
        ('seoul-weather', 'Discover a Seoul forecast through A2A', 'live'),
        ('data-part', 'Read structured A2A data parts', 'live'),
        ('context-follow', 'Continue using the returned contextId', 'live'),
        ('context-conflict', 'Reject a conflicting visitor/context owner', 'isolated'),
        ('context-guess', 'Reject another client guessing a contextId', 'isolated'),
        ('role-version', 'Preserve advertised message response formats', 'isolated'),
        ('real-signed-agent', 'Verify a genuine signed remote A2A caller', 'manual'),
    )),
    ('rest', (
        ('seoul-weather', 'Discover a Seoul forecast through REST', 'live'),
        ('follow-details', 'Retain result identity through REST details', 'live'),
        ('protocol-filter', 'Apply strict explicit protocol selection', 'isolated'),
        ('quota', 'Return actual request-limit policy and Retry-After', 'isolated'),
        ('invalid-jsonrpc', 'Distinguish malformed JSON and invalid envelopes', 'isolated'),
        ('latency', 'Measure discovery latency without claiming execution success', 'live'),
    )),
    ('x402', (
        ('explicit-only', 'Exclude x402 from automatic discovery', 'isolated'),
        ('explicit-filter', 'Honor an explicit x402 request', 'isolated'),
        ('payment-challenge', 'Inspect an isolated HTTP 402 challenge', 'isolated'),
        ('no-wallet-leak', 'Keep payment details out of the Chat interface', 'isolated'),
        ('real-settlement', 'Validate an actual authorized settlement', 'manual'),
        ('bazaar-listing', 'Confirm external Bazaar registration', 'manual'),
    )),
    ('workflow', (
        ('template-search', 'Discover a relevant published workflow', 'isolated'),
        ('template-details', 'Read current workflow inputs and readiness', 'isolated'),
        ('graph-authority', 'Require customer authorization to execute a graph', 'isolated'),
        ('run-key', 'Poll an isolated run using its scoped run key', 'isolated'),
        ('idempotency', 'Avoid duplicate isolated provider execution', 'isolated'),
        ('external-run', 'Execute an actual provider workflow with scoped approval', 'manual'),
    )),
    ('revisit', (
        ('mcp-rest-memory', 'Retain memory across MCP and REST', 'isolated'),
        ('reset-notice', 'Explain an unknown visitor session reset', 'isolated'),
        ('current-evidence', 'Reject stale success after newer failure', 'isolated'),
        ('report-batching', 'Preserve ranking while batching report verification', 'isolated'),
    )),
    ('task-updates', (
        ('purpose-consent', 'Require task-specific destination authorization', 'isolated'),
        ('verified-destination', 'Require destination verification before delivery', 'isolated'),
        ('withdrawal', 'Honor revocation and independent marketing consent', 'isolated'),
        ('real-delivery', 'Confirm actual authorized notification receipt', 'manual'),
    )),
    ('adversarial', (
        ('oversized', 'Reject oversized inputs without provider contact', 'isolated'),
        ('schema-authority', 'Reject invented tools and argument authority', 'isolated'),
        ('ssrf', 'Reject private outbound destinations', 'isolated'),
        ('xss', 'Render hostile strings as text in the browser', 'isolated'),
        ('uncertain-retry', 'Pause uncertain execution without an automatic retry', 'isolated'),
        ('secret-masking', 'Keep secrets out of rendered Chat content', 'isolated'),
    )),
)


def scenarios():
    """Planning inventory, never a claim that every scenario has been executed."""
    return [{'id': group + ':' + key, 'agent_type': group, 'title': title, 'mode': mode}
            for group, cases in GROUPS for key, title, mode in cases]
