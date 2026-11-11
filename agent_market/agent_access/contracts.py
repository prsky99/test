"""Stable compact MCP interface, independent of dynamic provider schemas."""
PROFILE='adoption-compact-v1'
TASK={'type':'string','minLength':1,'maxLength':500}
REF={'type':'integer','minimum':1,'maximum':2147483647}


def obj(properties,required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}


def tools():
    definitions=[
        ('discover','Find up to three verified agents or published workflows. Preparation never executes a provider.',obj({
            'task':TASK,'protocol':{'enum':['auto','any','a2a','mcp','x402']},
            'resource_type':{'enum':['auto','agent','workflow']},'prepare':{'type':'boolean'},
            'arguments':{'type':'object','maxProperties':30},
            'known_schema_digests':{'type':'array','maxItems':16,'items':{'type':'string','pattern':'^[0-9a-f]{64}$'}}},('task',))),
        ('describe','Read the selected agent contract and current execution evidence.',obj({
            'resource_id':REF,'version_id':{'type':'string','pattern':'^cv_[0-9a-f]{32}$'}},('resource_id',))),
        ('execute','Execute a prepared, customer-authorized informational search, or inspect/cancel its operation.',obj({
            'action':{'enum':['run','status','cancel']},'preparation_id':{'type':'string','pattern':'^ap_[0-9a-f]{32}$'},
            'grant':{'type':'string','pattern':'^axg_[0-9a-f]{32}$'},
            'idempotency_key':{'type':'string','pattern':'^[A-Za-z0-9_.:-]{1,128}$'},
            'operation_id':{'type':'string','pattern':'^axo_[0-9a-f]{32}$'}},('action',))),
        ('resume','Revalidate the previous task. This never executes a provider.',obj({})),
        ('report','Record caller feedback and suggest alternatives without executing a retry.',obj({
            'resource_id':REF,'ok':{'type':'boolean'},'task':TASK,
            'error_type':{'enum':['timeout','http_5xx','auth_error','schema_mismatch','rate_limit']},
            'protocol':{'enum':['auto','any','a2a','mcp','x402']}},('resource_id','ok'))),
    ]
    return [{'name':name,'description':description,'inputSchema':schema,
             'annotations':{'readOnlyHint':name in ('describe','resume'),
                 'destructiveHint':name=='execute','idempotentHint':name in ('describe','resume'),
                 'openWorldHint':name=='execute'},
             'outputSchema':{'type':'object','properties':{
                 'status':{'type':'string'},'items':{'type':'array','maxItems':3,'items':{'type':'object'}}},
                 'additionalProperties':True}}
            for name,description,schema in definitions]


def openapi_profile(document):
    """Select public operations from the app and reuse the compact tool DTOs."""
    import copy
    selected={'/api/agent/v1/discover':'post','/api/agent/v1/resume':'get',
              '/api/agent/v1/report':'post','/api/agents/{rid}':'get','/api/feed/verified.json':'get'}
    paths={path:{method:copy.deepcopy(document['paths'][path][method])}
           for path,method in selected.items()if method in document.get('paths',{}).get(path,{})}
    # These bounded public documents are deliberately absent from FastAPI's generated paths.
    paths['/api/agent/v1/entry']={'get':{'summary':'Public discovery entry and supported actions',
        'responses':{'200':{'description':'Service discovery document','content':{'application/json':{'schema':{'type':'object'}}}}}}}
    paths['/api/agent/v1/check']={'get':{'operationId':'checkAgentUrl',
        'summary':'Check before you call: recorded status, recent check success rate, latency, grade, evidence sources and up to three alternatives for one URL; the URL is only looked up, never called',
        'parameters':[{'name':'url','in':'query','required':True,'schema':{'type':'string','format':'uri','maxLength':2048},
                       'description':'Public http(s) endpoint or agent-card URL'}],
        'responses':{'200':{'description':'Our record (found true) or found false with a register link',
                            'content':{'application/json':{'schema':{'type':'object','required':['found','url','evidence_sources','alternatives']}}}},
                     '400':{'description':'Not a public http(s) URL (private, reserved and local addresses are refused)'},
                     '429':{'description':'Rate limited; retry after the Retry-After seconds'}}}}
    paths['/api/agent/v1/openapi.json']={'get':{'summary':'This public discovery API contract',
        'responses':{'200':{'description':'OpenAPI document','content':{'application/json':{'schema':{'type':'object'}}}}}}}
    paths['/api/agent/v1/badge/{resource_id}.svg']={'get':{'summary':'Recorded current-version execution badge',
        'parameters':[{'name':'resource_id','in':'path','required':True,'schema':{'type':'integer','minimum':1}}],
        'responses':{'200':{'description':'Verification status SVG; unverified does not mean execution succeeded',
            'content':{'image/svg+xml':{'schema':{'type':'string'}}}}}}}
    schemas={item['name']:item['inputSchema']for item in tools()}
    for path,name in (('/api/agent/v1/discover','discover'),('/api/agent/v1/report','report')):
        paths[path]['post']['requestBody']={'required':True,'content':{'application/json':{'schema':schemas[name]}}}
    for path in ('/api/agent/v1/discover','/api/agent/v1/resume','/api/agent/v1/report'):
        operation=paths[path][selected[path]]
        operation.setdefault('parameters',[]).append({'name':'X-Visitor-Token','in':'header',
            'required':path!='/api/agent/v1/discover','schema':{'type':'string'},
            'description':'Transport session returned by discovery. Never include it in a prompt or query string.'})
    components={};pending=[paths]
    while pending:
        value=pending.pop()
        if isinstance(value,list):pending.extend(value)
        elif isinstance(value,dict):
            reference=value.get('$ref','')
            prefix='#/components/schemas/'
            if reference.startswith(prefix)and reference[len(prefix):]not in components:
                name=reference[len(prefix):]
                components[name]=copy.deepcopy(document['components']['schemas'][name]);pending.append(components[name])
            pending.extend(v for k,v in value.items()if k!='$ref')
    return {'openapi':document['openapi'],'info':{'title':'Agent Concierge discovery','version':'1.0.0'},
        'servers':[{'url':'https://agentconcierge.biz'}],'x-agentconcierge-profile':'agent-discovery-v1',
        'paths':paths,'components':{'schemas':components}}
