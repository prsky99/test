"""Compact projection of the existing ranked discovery service."""
import copy
import json
import re

from ..capability_registry import digest
from ..concierge.connections import public_agent
from ..concierge.discovery_state import execution_state, registered_tools
from ..concierge.execution_policy import safe_registered_tool
from ..concierge.protocols import requested_protocol, search_protocols
from .cache import BoundedCache

PROFILE='adoption-compact-v1'
CANDIDATE_LIMIT=32


def bounded(value, maximum=7800):
    if len(json.dumps(value,ensure_ascii=True,allow_nan=False).encode())>maximum:
        raise ValueError('RESPONSE_TOO_LARGE')
    return value


class Catalog:
    def __init__(self,front):
        self.front=front;self.store=front.store
        self.schemas=BoundedCache(entries=128,ttl=300)

    def describe(self,resource_id,version=None,*,resource=None,state=None,compact=False):
        if type(resource_id)is not int or not 0<resource_id<2**31:raise ValueError('INVALID_INPUT')
        row=resource or self.store.resource(resource_id)
        if not row:raise ValueError('NOT_FOUND')
        state=state or execution_state(self.store,row)
        if version is not None and state['version_id']!=version:raise ValueError('SCHEMA_CHANGED')
        if not state['verified']:raise ValueError('NOT_VERIFIED')
        tools=[tool for tool in registered_tools(row) if safe_registered_tool(tool)]
        if row['kind']=='mcp' and not tools:raise ValueError('UNSUPPORTED_CONTRACT')
        specs=public_agent({'id':row['id'],'kind':row['kind'],'tools_schema':tools},resource=row)['tools_schema']
        identity=digest([state['version_id'],specs,PROFILE])
        summary={'resource_id':row['id'],'protocol':row['kind'],'version_id':state['version_id'],
                 'schema_digest':identity,'evidence':{key:state[key]for key in ('verified','verified_at','expires_at')}}
        if compact and len(json.dumps(specs,ensure_ascii=True).encode())>7000:
            return {**summary,'schema_deferred':True}
        definition=copy.deepcopy(self.schemas.get(identity,lambda:bounded({
            'resource_id':row['id'],'protocol':row['kind'],'version_id':state['version_id'],
            'schema_digest':identity,'tools_schema':specs},32768)))
        definition['evidence']={key:state[key] for key in ('verified','verified_at','expires_at')}
        return bounded(definition,32400)

    def discover(self,body):
        if not isinstance(body,dict)or set(body)-{'task','protocol','resource_type','known_schema_digests','prepare','arguments'}:
            raise ValueError('INVALID_INPUT')
        task=body.get('task')
        if type(task)is not str or not 1<=len(task.strip())<=500:raise ValueError('INVALID_INPUT')
        known=body.get('known_schema_digests',[])
        if (type(known)is not list or len(known)>16 or
                any(type(x)is not str or not re.fullmatch('[0-9a-f]{64}',x)for x in known)):
            raise ValueError('INVALID_INPUT')
        kind=requested_protocol(task,{'protocol':body.get('protocol')})
        target=body.get('resource_type','auto')
        if target not in ('auto','agent','workflow'):raise ValueError('INVALID_INPUT')
        if 'prepare'in body and type(body['prepare'])is not bool:raise ValueError('INVALID_INPUT')
        from ..concierge.workflow_discovery import wants_workflow,recommend
        if target=='workflow'or target=='auto'and wants_workflow(task):
            value=recommend(self.store,task,{'protocol':kind},runtime=getattr(self.front,'workflow_runtime',None))
            compact=[]
            for row in value['workflows'][:3]:
                item={k:row.get(k)for k in ('id','name','page_path','definition_hash','protocols','node_count','execution_availability')}
                item['name']=str(item.get('name')or'Published workflow')[:120]
                item['description']=str(row.get('description')or'')[:240]
                compact.append(item)
            return bounded({'profile':PROFILE,'status':'matched'if compact else'no_match',
                'resource_type':'workflow','items':compact,'execution_authorized':False})
        from .projection import current_states
        items=[];resources={};states={}
        # Qualify a bounded shortlist before limiting the public result. A
        # recently healthy listing must not hide another verified connection.
        # Qualify each protocol separately so unverified A2A candidates cannot
        # exhaust automatic discovery before MCP is considered.
        for protocol in search_protocols(kind):
            found=self.front.rec.search(task,kind=protocol,limit=CANDIDATE_LIMIT)[:CANDIDATE_LIMIT]
            batch_resources,batch_states=current_states(self.store,[r['id']for r in found])
            resources.update(batch_resources);states.update(batch_states)
            for row in found:
                evidence=row.get('capability_contract')or{}
                current=states.get(row['id'],{})
                if not current.get('verified')or current['version_id']!=evidence.get('connection_version_id'):continue
                items.append({'id':row['id'],'name':str(row.get('name')or'Agent')[:120],
                    'protocol':row['kind'],'url':row['url'],'grade':row.get('grade'),
                    'version_id':current['version_id'],
                    'verified_at':current['verified_at'],'expires_at':current['expires_at'],
                    'match_basis':'heuristic','execution_authorized':False})
                if len(items)==3:break
            if len(items)==3:break
        result={'profile':PROFILE,'status':'matched'if items else'no_match',
                'resource_type':'agent','items':items,'execution_authorized':False}
        if items:
            definition=self.describe(items[0]['id'],items[0]['version_id'],resource=resources[items[0]['id']],state=states[items[0]['id']],compact=True)
            result['selected_contract']={k:v for k,v in definition.items()if k!='tools_schema'}
            if definition.get('schema_deferred'):result['schema_deferred']=True
            elif definition['schema_digest']not in known:
                trial={**result,'selected_contract':definition}
                if len(json.dumps(trial,ensure_ascii=True).encode())<=7800:result=trial
                else:result['schema_deferred']=True
            else:result['schema_cached']=True
        return bounded(result)
