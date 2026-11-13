"""Single-source public MCP contracts; transport code never mutates definitions."""
from ..broker.categories import CATEGORIES
from .connections import KINDS


def mcp_tools():
    TOKEN_ARG = {"visitor_token": {"type": "string", "description": "Your visitor token (vt_…) so I remember you. Omit on first contact."}}
    TOOLS = [
        {"name": "hello", "description": "Optional greeting. Greets you, remembers you if you pass your visitor token, and asks what you need.",
         "inputSchema": {"type": "object", "properties": {**TOKEN_ARG, "name": {"type": "string", "description": "Your agent name"}}},
         "annotations": {"readOnlyHint": False}},
        {"name": "chat", "description": "Converse: describe a task in plain English and refine it over several turns ('only free ones', 'details 1', 'more', 'what's new', 'stop'). Keeps the conversation for your visitor token; replies are in English.",
         "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}, **TOKEN_ARG}, "required": ["message"]}},
        {"name": "search", "description": "Browse: list up to three catalog matches for a task so you can compare names, grades and latest successful verification. Stateless and read-only; no conversation is saved. Searches A2A first, then MCP; x402 requires an explicit choice. price_status is free, paid or paid_or_unknown (price_usdc null). Returns the same ranked list as find_agents; use find_agents when you are ready to connect.",
         "inputSchema": {"type": "object", "properties": {
             "task": {"type": "string", "description": "The specific capability needed (e.g. 'weather forecast', 'stock price', 'web search')"},
             "kind": {"type": "string", "enum": [*KINDS, "any"], "description": "Explicit recommendation protocol filter; Any searches A2A then MCP, excluding x402. Defaults to A2A first, then MCP; x402 requires an explicit choice."},
             "category": {"type": "string", "enum": list(CATEGORIES.keys()), "description": "Compatibility field; task relevance is derived from the task text."},
             "auth": {"type": "string", "enum": ["none", "agent"], "description": "Compatibility field; authentication preference does not affect ranking."},
             "k": {"type": "integer", "description": "Compatibility field; at most three results is returned."},
             **TOKEN_ARG}, "required": ["task"]}},
        {"name": "find_agents", "description": "Recommend and connect: pick up to three active agents for a task and get what you need to connect to each (endpoint, verification evidence, calling details). Stateless and read-only; no conversation is saved. price_status is free, paid (price_usdc per call in micro-USDC) or paid_or_unknown (the provider states a price or none is known; price_usdc is null). A listing our gateway can run has connection_available (same as gateway_ready) and run_here: pass its arguments to this server's call tool to run it in this session; mcp_config is a settings entry for an MCP host.",
         "inputSchema": {"type": "object", "properties": {
             "task": {"type": "string", "description": "What you need done"},
             "kind": {"type": "string", "enum": [*KINDS, "any"], "description": "Explicit recommendation protocol filter; Any searches A2A then MCP, excluding x402. Defaults to A2A first, then MCP; x402 requires an explicit choice."},
             "category": {"type": "string", "enum": list(CATEGORIES.keys()), "description": "Compatibility field; task relevance is derived from the task text."},
             "auth": {"type": "string", "enum": ["none", "agent"], "description": "Compatibility field; authentication preference does not affect ranking."},
             **TOKEN_ARG}, "required": ["task"]}},
        {"name": "check_agent", "description": "Read-only check before you call an agent: our recorded status, recent check success rate and latency, grade, evidence sources and up to three alternatives for an endpoint or agent-card URL. The URL is only looked up, never called.",
         "inputSchema": {"type": "object", "properties": {
             "url": {"type": "string", "description": "The agent's endpoint or agent-card URL (public http or https)."},
             **TOKEN_ARG}, "required": ["url"]}},
        {"name": "whats_new", "description": "Read the last task saved by chat and re-evaluate its evidence without changing it. Use chat to save a task first (valid visitor token required).",
         "inputSchema": {"type": "object", "properties": TOKEN_ARG, "required": ["visitor_token"]}},
        {"name": "subscribe", "description": "Legacy contact command. Use /api/task-updates with explicit task scope and authorization; this command cannot grant permission.",
         "inputSchema": {"type": "object", "properties": {"contact_url": {"type": "string"},
                                                          "contact_type": {"type": "string", "enum": ["webhook", "a2a"]}, **TOKEN_ARG},
                         "required": ["contact_url"]}},
        {"name": "verify_contact", "description": "Confirm your contact with the 6-digit code I sent there.",
         "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}, **TOKEN_ARG}, "required": ["code", "visitor_token"]}},
        {"name": "call", "description": "Run one tool of a listing you chose, through our gateway, after checking its current schema. Only tools classified read-only are relayed; destructive tools and tools that need the provider's own credentials are refused. A paid listing runs only with a payment proof you supply. Do not retry an uncertain outcome automatically.",
         "inputSchema": {"type": "object", "properties": {
             "resource_id": {"type": "integer", "description": "The resource_id of the agent, MCP server, or API to call"},
             "tool": {"type": "string", "description": "The specific tool name to execute"},
             "arguments": {"type": "object", "description": "Key-value arguments to pass to the tool"},
             "task": {"type": "string", "description": "The task query (optional; used to find immediate alternatives if execution fails)"},
             "account_id": {"type": "string", "description": "Optional credit account ID for paid tools (defaults to your visitor ID)"},
             "payment": {"type": "object", "description": "Optional payment details (tx_hash, signature, headers) for paid endpoints"},
             "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128,
                 "description": "Stable caller key for supported ticketed delivery while its execution record is retained. Reuse with identical input; uncertain execution stays paused for review."},
             **TOKEN_ARG}, "required": ["resource_id", "tool"]}},
        {"name": "report", "description": "Record caller feedback. On failure, suggest up to three currently verified alternatives and eligible published workflows without executing a retry. Retain the selected protocol and reject known shared failure domains.",
         "inputSchema": {"type": "object", "properties": {
             "resource_id": {"type": "integer", "description": "The resource_id of the agent/tool that was executed"},
             "ok": {"type": "boolean", "description": "Whether the tool call succeeded (true) or failed (false)"},
             "error": {"type": "string", "description": "Optional error message or reason on failure"},
             "error_type": {"type": "string", "enum": ["timeout", "http_5xx", "auth_error", "schema_mismatch", "rate_limit"],
                 "description": "Optional structured failure category. This report never authorizes a retry."},
             "protocol": {"type": "string", "enum": ["auto", "any", "a2a", "mcp", "x402"],
                 "description": "Optional explicit recovery scope; otherwise retain the prior selection."},
             "task": {"type": "string", "description": "The task query (optional; defaults to your last searched task)"},
             **TOKEN_ARG}, "required": ["resource_id", "ok"]}},
        {"name": "credit", "description": "Check your own virtual credit balance using a valid visitor token. Top-ups and subscriptions are being prepared; this tool only reads the current balance.",
         "inputSchema": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ["balance"], "description": "Action: balance to check your credits."},
             "account_id": {"type": "string", "description": "Your own visitor account ID (defaults to the authenticated visitor ID)"},
             **TOKEN_ARG}, "required": ["action"]}},
        {"name": "adapt_rest", "description": "Turn a public OpenAPI/Swagger document into tools (action list_tools, which only reads the document) or call one of its endpoints (action call). A call sends the HTTP method the document declares, including POST, PUT or DELETE, to that public API without credentials, so it can change data there.",
         "inputSchema": {"type": "object", "properties": {
             "spec_url": {"type": "string", "description": "URL of the OpenAPI/Swagger JSON specification."},
             "spec": {"type": "object", "description": "Inline OpenAPI JSON specification object."},
             "action": {"type": "string", "enum": ["list_tools", "call"], "description": "Action: 'list_tools' to discover executable tools, 'call' to invoke an endpoint."},
             "tool": {"type": "string", "description": "Tool name to execute when action='call'."},
             "arguments": {"type": "object", "description": "Arguments for the tool invocation."},
             "base_url": {"type": "string", "description": "Optional override for API base URL."},
             **TOKEN_ARG}}},
    ]
    TOOLS.extend([
        {'name': 'search_workflows', 'description': 'Find up to three relevant published workflows by purpose, node capability, or English and common non-English aliases. Discovery does not execute it.',
         'inputSchema': {'type': 'object', 'properties': {
             'task': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
             'protocol': {'type': 'string', 'enum': [*KINDS, 'any'], 'description': 'Optional explicit constraint on workflow node protocols.'},
             **TOKEN_ARG}, 'required': ['task']}, 'annotations': {'readOnlyHint': True}},
        {'name': 'workflow_details', 'description': 'Read a currently public workflow definition and its recorded execution readiness. Review inputs and use the existing authorized workflow run API to execute.',
         'inputSchema': {'type': 'object', 'properties': {
             'template_id': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647}, **TOKEN_ARG},
             'required': ['template_id']}, 'annotations': {'readOnlyHint': True}},
    ])
    # When each tool fits and one concrete call, so a caller can choose without trial and error (QA 18, B4).
    GUIDE = {
        'hello': ('Use when you want this service to remember you across calls.', '{"name": "travel-planner-agent"}'),
        'chat': ('Use when a conversation helps: refine a previous list ("only free ones"), ask for "details 2", or "more".', '{"message": "find a weather forecast API"}'),
        'search': ('Use when you want to browse and compare candidates for one task before choosing.', '{"task": "translate a document to Spanish"}'),
        'find_agents': ('Use when you want to connect to one of them now or run it here with call.', '{"task": "extract text from a PDF", "kind": "mcp"}'),
        'check_agent': ('Use when you already have an agent URL and want our evidence before calling it.', '{"url": "https://agent.example.org/.well-known/agent-card.json"}'),
        'whats_new': ('Use when you saved a task through chat earlier and want its evidence re-checked.', '{"visitor_token": "vt_..."}'),
        'subscribe': ('Use only for legacy contact registration; task updates use /api/task-updates.', '{"contact_url": "https://example.org/hook", "contact_type": "webhook"}'),
        'verify_contact': ('Use after subscribe, with the code delivered to that contact.', '{"code": "123456", "visitor_token": "vt_..."}'),
        'call': ('Use when you have chosen a listing and want this gateway to run one of its admitted tools.', '{"resource_id": 133020, "tool": "get_country_profile", "arguments": {"country_code": "US"}}'),
        'report': ('Use after a call to record the outcome and, on failure, get verified alternatives.', '{"resource_id": 133020, "ok": false, "error_type": "timeout"}'),
        'credit': ('Use when you need your own credit balance before a paid call.', '{"action": "balance", "visitor_token": "vt_..."}'),
        'adapt_rest': ('Use when the API you need has an OpenAPI document but no MCP server.', '{"spec_url": "https://api.example.org/openapi.json", "action": "list_tools"}'),
        'search_workflows': ('Use when a multi-step published workflow may already do your task.', '{"task": "technology news with supporting research"}'),
        'workflow_details': ('Use after search_workflows to inspect one workflow\'s steps and readiness.', '{"template_id": 12}'),
    }
    FIELD_HELP = {
        'chat': {'message': 'Plain-English request or follow-up, at most 2000 characters.'},
        'subscribe': {'contact_url': 'HTTPS webhook or A2A endpoint that receives updates.', 'contact_type': 'Whether contact_url is a webhook or an A2A agent.'},
        'verify_contact': {'code': 'The six-digit code delivered to your contact.'},
        'search_workflows': {'task': 'The outcome you need, in plain language.'},
        'workflow_details': {'template_id': 'The workflow id returned by search_workflows.'},
    }
    for tool in TOOLS:
        when, example = GUIDE.get(tool['name'], ('', ''))
        if when:
            tool['description'] = tool['description'].rstrip() + ' ' + when + ' Example arguments: ' + example
        for field, text in FIELD_HELP.get(tool['name'], {}).items():
            properties = tool['inputSchema'].get('properties', {})
            if field in properties and not properties[field].get('description'):
                properties[field] = {**properties[field], 'description': text}
    for tool in TOOLS:
        name = tool['name']
        read_only = name in ('search','find_agents','check_agent','whats_new','search_workflows','credit','workflow_details')
        # Hints follow what each tool really does (PM 11-14 04:1x). call relays only tools the execution policy
        # classifies read-only (proxy: is_relay_safe_tool), so it is not destructive, but it reaches third-party
        # servers and may run a paid listing with the caller's payment proof, so it is not read-only either.
        # adapt_rest call sends whatever method the caller's OpenAPI document declares (POST/PUT/DELETE too).
        external = name in ('call', 'adapt_rest')
        tool['annotations'] = {
            'readOnlyHint': read_only,
            'destructiveHint': name == 'adapt_rest',
            'idempotentHint': read_only,
            'openWorldHint': external or name == 'subscribe',
        }
        # Catalog lookup tools never write conversation state; chat/hello remain stateful.
        tool['outputSchema'] = {
            'type': 'object',
            'description': 'Structured tool result. Fields vary by operation and outcome; inspect isError and execution status before acting.',
            'properties': {
                'intent': {'type': 'string'},
                'text': {'type': 'string'},
                'visitor': {'type': ['object', 'null']},
                'recommendations': {'type': 'array', 'maxItems': 3, 'items': {'type': 'object'}},
                'ok': {'type': 'boolean'},
                'status': {'type': 'string'},
                'execution': {'type': 'object'},
            },
            'required': ['text'],
            'additionalProperties': True,
        }
    # run_workflow starts a public run and may answer with an MCP task (mcp_tasks.py), so it keeps its own
    # annotations (not read-only, open world) and its execution.taskSupport.
    import copy
    from .mcp_tasks import TOOL as RUN_WORKFLOW
    TOOLS.append({**copy.deepcopy(RUN_WORKFLOW), 'outputSchema': copy.deepcopy(TOOLS[-1]['outputSchema'])})
    return TOOLS


def discovery_arguments(arguments):
    """Normalize earlier manifest names and reject conflicting or ambiguous input."""
    value = dict(arguments)
    task, query = value.get('task'), value.get('query')
    if task is not None and query is not None and task != query:
        raise ValueError('Use one matching task or query value.')
    task = task if task is not None else query
    if type(task) is not str or not task.strip() or len(task) > 2000:
        raise ValueError('Provide a non-empty task of at most 2000 characters.')
    kind, protocol = value.get('kind'), value.get('protocol')
    for item in (kind, protocol):
        if item is not None and (type(item) is not str or item.strip().lower() not in ('a2a', 'mcp', 'x402', 'any', 'auto', '')):
            raise ValueError('Choose A2A, MCP, x402, or Any protocol.')
    if kind is not None and protocol is not None and kind.strip().lower() != protocol.strip().lower():
        raise ValueError('Use one matching kind or protocol selection.')
    selected = kind if kind is not None else protocol
    value['task'], value['kind'] = task, selected.strip().lower() if selected is not None else None
    return value
