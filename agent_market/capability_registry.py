"""Immutable connection versions and bounded, purpose-specific verification evidence."""
import hashlib
import json
import math
import secrets
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS connection_agents (
 resource_id INTEGER PRIMARY KEY, agent_ref TEXT UNIQUE NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS connection_versions (
 id TEXT PRIMARY KEY, resource_id INTEGER NOT NULL, binding_hash TEXT NOT NULL,
 schema_hash TEXT NOT NULL, profile_version TEXT NOT NULL, schema_complete INTEGER NOT NULL,
 created REAL NOT NULL, UNIQUE(resource_id,binding_hash,schema_hash,profile_version));
CREATE INDEX IF NOT EXISTS connection_versions_resource ON connection_versions(resource_id,created DESC);
CREATE TABLE IF NOT EXISTS capability_evidence (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL, scope TEXT NOT NULL, outcome TEXT NOT NULL,
 started REAL NOT NULL, finished REAL NOT NULL, recorded REAL NOT NULL, expires REAL NOT NULL,
 code TEXT, operation_ref TEXT, contract_id TEXT NOT NULL DEFAULT '', validator_version TEXT NOT NULL,
 dataset_version TEXT NOT NULL, cases INTEGER NOT NULL, successes INTEGER NOT NULL,
 artifact_hash TEXT, UNIQUE(version_id,scope,operation_ref,contract_id));
CREATE INDEX IF NOT EXISTS capability_evidence_version ON capability_evidence(version_id,scope,finished DESC);
CREATE INDEX IF NOT EXISTS capability_evidence_public_window ON capability_evidence(scope,finished,outcome,version_id,started);
CREATE TABLE IF NOT EXISTS capability_approvals (
 version_id TEXT NOT NULL, contract_id TEXT NOT NULL, tool TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(version_id,contract_id));
CREATE TABLE IF NOT EXISTS capability_eligibility (
 resource_id INTEGER PRIMARY KEY, version_id TEXT NOT NULL, outcome TEXT NOT NULL,
 executed_at REAL NOT NULL, expires REAL NOT NULL);
'''
INVALIDATION='''CREATE TRIGGER IF NOT EXISTS capability_binding_invalidation
AFTER UPDATE OF url,kind,usage_full_hash,usage_tools_hash,auth_info,auth_observed,active,health_status,usage_guide,details ON resources
WHEN OLD.url IS NOT NEW.url OR OLD.kind IS NOT NEW.kind OR OLD.usage_full_hash IS NOT NEW.usage_full_hash
 OR OLD.usage_tools_hash IS NOT NEW.usage_tools_hash OR OLD.auth_info IS NOT NEW.auth_info
 OR OLD.auth_observed IS NOT NEW.auth_observed
 OR OLD.active IS NOT NEW.active OR OLD.health_status IS NOT NEW.health_status
 OR OLD.usage_guide IS NOT NEW.usage_guide OR OLD.details IS NOT NEW.details
BEGIN DELETE FROM capability_eligibility WHERE resource_id=NEW.id; END;'''
PROFILES={'mcp':'mcp-stateless-v1','a2a':'a2a-sync-v1','x402':'x402-probe-v1'}
TTL=86400


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decoded(value,default):
    try:
        result=json.loads(value) if isinstance(value,str) else value
        return result if isinstance(result,type(default)) else default
    except (ValueError,TypeError):return default


def full_tools(tools):
    """Preserve every schema keyword; order tools without truncating their schemas."""
    if not isinstance(tools,list) or len(tools)>1000:raise ValueError('Invalid tool schema collection.')
    result=[];names=set()
    for tool in tools:
        if not isinstance(tool,dict) or not isinstance(tool.get('name'),str) or not 0<len(tool['name'])<=100 or tool['name'] in names:
            raise ValueError('Invalid or duplicate tool name.')
        names.add(tool['name'])
        item={k:tool[k] for k in ('name','description','inputSchema','outputSchema','annotations') if k in tool}
        if 'inputSchema' not in item:raise ValueError('A full input schema is required.')
        if not isinstance(item['inputSchema'],(dict,bool)):raise ValueError('Invalid input schema.')
        result.append(item)
    def bounded(value,depth=0):
        if depth>24:raise ValueError('Tool schemas exceed the nesting limit.')
        if isinstance(value,dict):
            for child in value.values():bounded(child,depth+1)
        elif isinstance(value,list):
            for child in value:bounded(child,depth+1)
    bounded(result)
    result.sort(key=lambda item:item['name'])
    if len(canonical(result))>2*1024*1024:raise ValueError('Tool schema collection exceeds its limit.')
    return result


def version_parts(resource):
    guide=decoded(resource.get('usage_guide'),{});details=decoded(resource.get('details'),{})
    binding={k:resource.get(k) for k in ('kind','url','auth_required','auth_observed','auth_declared','auth_info')}
    binding['guide']={k:guide.get(k) for k in ('endpoint','binding','spec_version','methods','endpoint_override')}
    binding['card']={k:details.get(k) for k in ('endpoints','spec_version','securitySchemes','security','endpoint_override')}
    if (resource.get('source') == 'agentconcierge-owned' and str(resource.get('key') or '').startswith('agentconcierge-owned:')
            and details.get('owned_schema_revision')):
        binding['owned_schema_revision'] = details.get('owned_schema_revision')
    complete=resource.get('kind')!='mcp' or resource.get('usage_full_tools') is not None
    source=resource.get('usage_full_tools') if resource.get('usage_full_tools') is not None else resource.get('usage_tools')
    tools=decoded(source,[])
    try:
        schema=digest({'complete':complete,'tools':tools})
    except (ValueError,TypeError,RecursionError):
        # Preserve a distinct opaque pin for rejected provider data. Never turn
        # invalid numeric constraints into an empty, executable schema.
        complete=False
        schema=digest({'complete':False,'invalid_schema_source':str(source)})
    return digest(binding),schema,PROFILES.get(resource.get('kind'),'unsupported-v1'),complete


def known_schema_failure(store, resource):
    """Retain a rejected contract pin across health recovery for that version.

    A health response is not a schema review. A newly surveyed full contract has
    a different immutable version and does not inherit the old failure marker.
    """
    if store is None or not isinstance(resource, dict) or type(resource.get('id')) is not int:
        return False
    binding, schema, profile, _ = version_parts(resource)
    version = 'cv_' + digest([resource['id'], binding, schema, profile])[:32]
    return bool(store.query("""SELECT 1 FROM capability_evidence
        WHERE version_id=? AND scope='execution' AND outcome='failed'
        AND code='SCHEMA_CHANGED' LIMIT 1""", (version,)))



TRANSIENT_FAILURES = ('UPSTREAM_TOOL_ERROR', 'UPSTREAM_TIMEOUT', 'UPSTREAM_NETWORK', 'CAPACITY_EXCEEDED')

class Registry:
    def __init__(self,store):self.store=store

    def current(self,resource,*,create=True):
        if type(resource) is int:resource=self.store.resource(resource)
        if not isinstance(resource,dict) or resource.get('kind') not in PROFILES:return None
        binding,schema,profile,complete=version_parts(resource);rid=resource['id']
        version='cv_'+digest([rid,binding,schema,profile])[:32]
        existing=self.store.query('SELECT a.agent_ref FROM connection_agents a JOIN connection_versions v ON v.resource_id=a.resource_id WHERE v.id=?',(version,))
        if existing:
            return {'id':version,'agent_ref':existing[0][0],'schema_hash':schema,'binding_hash':binding,'profile_version':profile,'schema_complete':complete,'resource_id':rid}
        if not create:return None
        with self.store.tx() as db:
            db.execute('INSERT OR IGNORE INTO connection_agents VALUES (?,?,?)',(rid,'ag_'+secrets.token_hex(16),time.time()))
            db.execute('INSERT OR IGNORE INTO connection_versions VALUES (?,?,?,?,?,?,?)',(version,rid,binding,schema,profile,int(complete),time.time()))
            ref=db.execute('SELECT agent_ref FROM connection_agents WHERE resource_id=?',(rid,)).fetchone()[0]
        return {'id':version,'agent_ref':ref,'schema_hash':schema,'binding_hash':binding,'profile_version':profile,'schema_complete':complete,'resource_id':rid}

    def record(self,version,*,scope,outcome,started,finished,operation_ref=None,code=None,contract_id='',cases=1,successes=None,artifact_hash=None,dataset='live-execution-v1',guard=None):
        from .concierge.execution_errors import failure_code
        if not version or scope not in ('transport','execution','contract') or outcome not in ('succeeded','failed','unknown'):raise ValueError('Invalid evidence category.')
        now=time.time()
        if any(type(t) not in (int,float) or not math.isfinite(t) for t in (started,finished)) or not 0<started<=finished<=now+5:
            raise ValueError('Evidence requires actual execution timestamps.')
        if type(cases) is not int or not 1<=cases<=10000:raise ValueError('Invalid evidence sample count.')
        successes=cases if successes is None and outcome=='succeeded' else 0 if successes is None else successes
        if type(successes) is not int or not 0<=successes<=cases:raise ValueError('Invalid evidence successes.')
        if scope=='contract':
            from .capability_contracts import CONTRACTS
            if contract_id not in CONTRACTS:raise ValueError('Unknown capability contract.')
        else:contract_id=''
        # References, dataset IDs and artifact digests are generated by trusted
        # application code. Never accept input/output bodies or visitor identity.
        import re
        if operation_ref is not None and not re.fullmatch(r'(?:ex|at)_[0-9a-f]{24}',operation_ref):raise ValueError('Invalid operation reference.')
        if artifact_hash is not None and not re.fullmatch('[0-9a-f]{64}',artifact_hash):raise ValueError('Invalid artifact digest.')
        if not re.fullmatch('[a-z0-9.-]{1,80}',dataset):raise ValueError('Invalid dataset version.')
        identity='ev_'+secrets.token_hex(16)
        with self.store.tx() as db:
            if guard is not None and not guard():return None
            if not db.execute('SELECT 1 FROM connection_versions WHERE id=?',(version['id'],)).fetchone():raise ValueError('Unknown connection version.')
            db.execute('INSERT OR IGNORE INTO capability_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,version['id'],scope,outcome,started,finished,now,finished+TTL,failure_code(code) if code else None,operation_ref,contract_id,'capability-validator-v1',dataset,cases,successes,artifact_hash))
            from .agent_access.storage import enqueue
            enqueue(self.store,db,version['resource_id'],'execution_changed'if scope=='execution'else'contract_changed',version['id'],identity,
                    observation={'scope':scope,'outcome':outcome,'finished':finished})
        current=self.current(version['resource_id']) if scope=='execution' else None
        if current and current['id']==version['id']:
            with self.store.tx() as db:
                row=db.execute('SELECT * FROM resources WHERE id=?',(version['resource_id'],)).fetchone()
                if row:
                    binding,schema,profile,_=version_parts(dict(row))
                    if 'cv_'+digest([version['resource_id'],binding,schema,profile])[:32]==version['id']:
                        db.execute('INSERT INTO capability_eligibility VALUES (?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET version_id=excluded.version_id,outcome=excluded.outcome,executed_at=excluded.executed_at,expires=excluded.expires WHERE excluded.executed_at>=capability_eligibility.executed_at',
                            (version['resource_id'],version['id'],outcome,finished,finished+TTL))
        return identity

    def approve(self,resource,contract_id,tool,*,guard=None):
        from .capability_contracts import CONTRACTS
        from .concierge.execution_policy import tools_for,safe_registered_tool
        if contract_id not in CONTRACTS:raise ValueError('Unknown capability contract.')
        version=self.current(resource)
        if not version or not version['schema_complete']:raise ValueError('Survey the full tool schema first.')
        spec=next((t for t in tools_for(resource) if t.get('name')==tool),None)
        if resource['kind']!='mcp' or not spec or not safe_registered_tool(spec):raise ValueError('Select a registered informational MCP tool.')
        from .workflow_product_semantics import CONTRACT_ID as PRODUCT_V2, registered_tool
        if contract_id==PRODUCT_V2:
            if not registered_tool(resource,tool):raise ValueError('Approve only the exact typed v2 input/output schemas and read-only annotations.')
        with self.store.tx() as db:
            if guard is not None:
                # The optional current-role guard and its approval share one
                # writer lock; catalog version creation has already completed.
                if db.in_transaction:raise ValueError('Use a standalone guarded contract approval.')
                db.execute('BEGIN IMMEDIATE')
                if guard() is not True:raise PermissionError('Current contract approval authority is required.')
            db.execute('INSERT OR REPLACE INTO capability_approvals VALUES (?,?,?,?)',(version['id'],contract_id,tool,time.time()))
        return version

    def projection(self,resource,*,version=None,strict=False):
        # strict: routing decisions (fallback rollout) need the latest execution itself to have succeeded.
        version=version or self.current(resource)
        if not version:return {}
        now=time.time();reason='not_verified';profile_available=False
        from .concierge.execution_policy import admit,tools_for,safe_registered_tool,ExecutionDenied
        try:
            from .execution_authority import require_enabled
            require_enabled(self.store,'invoke')
            admit(resource,resource['kind'],public=True,authorize_charge=resource['kind']=='x402')
            if resource['kind']=='mcp' and not any(safe_registered_tool(t) for t in tools_for(resource)):raise ExecutionDenied('No registered informational tool.')
            profile_available=True
        except ExecutionDenied as exc:reason=exc.error_code.lower()
        rows=self.store.query('SELECT * FROM capability_evidence WHERE version_id=? AND scope=\'execution\' ORDER BY finished DESC,recorded DESC,id DESC LIMIT 2',(version['id'],))
        latest=dict(rows[0]) if rows else None
        # One transient provider failure right after a current success (a burst
        # limit or a slow reply) does not withdraw readiness; a second
        # consecutive failure, or any other failure, still does.
        if (not strict and latest and latest['outcome']!='succeeded' and latest['code'] in TRANSIENT_FAILURES and len(rows)>1
                and rows[1]['outcome']=='succeeded' and rows[1]['expires']>now):
            latest=dict(rows[1])
        valid=bool(latest and latest['outcome']=='succeeded' and latest['expires']>now and version['schema_complete'])
        if profile_available:
            reason='verified' if valid else 'latest_failure' if latest and latest['outcome']!='succeeded' else 'schema_not_surveyed' if not version['schema_complete'] else 'expired' if latest and latest['expires']<=now else 'not_verified'
        contracts=[]
        for row in self.store.query('SELECT contract_id,created,tool FROM capability_approvals WHERE version_id=?',(version['id'],)):
            evidence=self.store.query('SELECT outcome,expires,started,dataset_version,artifact_hash,cases FROM capability_evidence WHERE version_id=? AND scope=\'contract\' AND contract_id=? ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1',(version['id'],row[0]))
            exact=True
            from .workflow_product_semantics import CONTRACT_ID as PRODUCT_V2, registered_tool
            if row[0]==PRODUCT_V2:
                exact=registered_tool(resource,row['tool'])
            from .capability_adapter_dispatch import profile as adapter_profile, evidence_dataset
            try:
                adapter=adapter_profile(resource,row[0],row['tool'])
                if adapter and (not evidence or evidence[0]['dataset_version']!=evidence_dataset(adapter)):
                    exact=False
            except (ValueError,TypeError,KeyError):
                exact=False
            if evidence and evidence[0]['dataset_version']=='generic-io-transform-v1':
                profiles=getattr(getattr(self.store,'_workflow_runtime',None),'io_profiles',None)
                exact=bool(profiles and profiles.verified_evidence(version['id'],row[0],row['tool'],evidence[0]))
            contracts.append({'id':row[0],'verified':bool(exact and valid and evidence and evidence[0]['outcome']=='succeeded' and evidence[0]['expires']>now and evidence[0]['started']>=row['created'])})
        return {'agent_ref':version['agent_ref'],'connection_profile_version':version['profile_version'],
                'gateway_ready':bool(profile_available and valid),
                'connection_readiness':{'profile_available':profile_available,'verified_callable':bool(profile_available and valid),'reason':reason,'verified_at':latest['finished'] if valid and profile_available else None,'evidence_scope':'execution'},'capability_contracts':contracts}

    def inspect(self,rid):
        resource=self.store.resource(rid)
        if not resource:return None
        version=self.current(resource)
        if not version:return {'resource_id':rid,'supported':False}
        return {**self.projection(resource,version=version),'resource_id':rid,'version':version,
                'evidence':[dict(r) for r in self.store.query('SELECT * FROM capability_evidence WHERE version_id=? ORDER BY finished DESC LIMIT 50',(version['id'],))]}
