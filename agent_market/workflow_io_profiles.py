"""Signed generic I/O mappings bound to real native-tool contract tests."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import time

from .capability_contracts import CONTRACTS, validate
from .capability_registry import Registry, canonical, decoded, digest
from .workflow_transforms import apply, review, pointer, MISSING

NOTICE = 'verified-io-transform-v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflow_io_profiles (
 id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL,
 created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
'''


def implementation():
    return digest([hashlib.sha256(Path(__file__).parent.joinpath(name).read_bytes()).hexdigest()
                   for name in ('workflow_transforms.py','workflow_io_profiles.py','capability_contracts.py','concierge/execution_policy.py')])


class IOProfiles:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        self.registry = Registry(self.store)
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def spec(self, resource, tool):
        from .concierge.execution_policy import admit, safe_registered_tool, supported_schema
        admit(resource, 'mcp', public=True)
        found = [t for t in decoded(resource.get('usage_full_tools'),[]) if isinstance(t,dict) and t.get('name')==tool]
        if len(found)!=1 or not safe_registered_tool(found[0]):raise ValueError('Select one registered read-only tool.')
        spec = found[0]; annotation = spec.get('annotations') or {}
        if annotation.get('readOnlyHint') is not True or annotation.get('destructiveHint') is not False or annotation.get('idempotentHint') is not True:
            raise ValueError('Explicit read-only, non-destructive and idempotent annotations are required.')
        supported_schema(spec);supported_schema({'inputSchema':spec.get('outputSchema')})
        return spec

    @staticmethod
    def output(profile, raw, supplied=None):
        for check in profile['status_checks']:
            value = pointer(raw,check['path'])
            expected=check.get('allowed')
            if 'equals_input' in check:
                original=pointer(supplied,check['equals_input'])
                expected=[] if original is MISSING else [original]
            if value is MISSING or not any(type(value) is type(v) and value==v for v in expected):
                raise ValueError('The provider did not report an allowed result status.')
        return apply(profile['output_transform'],raw)

    def checked(self, data):
        from .workflows import sensitive
        keys={'resource_id','tool','contract_id','input_transform','output_transform','status_checks'}
        if not isinstance(data,dict) or set(data)!=keys or type(data['resource_id']) is not int or not 0<data['resource_id']<2**31:
            raise ValueError('Provide an agent, tool, contract and explicit input/output transformations.')
        if type(data['contract_id']) is not str or data['contract_id'] not in ('news.search.v1','docs.search.v1'):
            raise ValueError('Use a supported informational contract.')
        if type(data['tool']) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',data['tool']):raise ValueError('Use a registered tool name.')
        if sensitive(data):raise ValueError('Transformation profiles cannot contain credentials or private input.')
        resource=self.store.resource(data['resource_id']);spec=self.spec(resource,data['tool'])
        review(data['input_transform']);review(data['output_transform'])
        contract=CONTRACTS[data['contract_id']]
        if (data['input_transform']['input_schema']!=contract['input_schema'] or data['input_transform']['output_schema']!=spec['inputSchema']
                or data['output_transform']['input_schema']!=spec['outputSchema'] or data['output_transform']['output_schema']!=contract['output_schema']):
            raise ValueError('Mappings must exactly join the canonical and registered native schemas.')
        checks=data['status_checks']
        if not isinstance(checks,list) or len(checks)>5:raise ValueError('Use at most five explicit provider status checks.')
        for check in checks:
            if not isinstance(check,dict) or set(check) not in ({'path','allowed'},{'path','equals_input'}):
                raise ValueError('Use explicit bounded scalar success statuses.')
            pointer({},check['path'])
            if 'equals_input' in check:pointer({},check['equals_input'])
            elif (not isinstance(check['allowed'],list) or not 1<=len(check['allowed'])<=10
                  or any(type(v) not in (str,bool,int,type(None)) for v in check['allowed'])):
                raise ValueError('Use explicit bounded scalar success statuses.')
        # Do not manufacture fresh retrieval times or source URLs with literals.
        def provenance(expr):
            if expr['op']=='const' and isinstance(expr['value'],(dict,list)):
                raise ValueError('Map result records from provider data rather than literal containers.')
            if expr['op']=='parse_json':
                source=expr['value']
                if source['op']=='trim':source=source['value']
                if source['op'] not in ('get','get_root'):raise ValueError('Parse output JSON only from an original provider field.')
            if expr['op']=='object':
                for key,child in expr['fields'].items():
                    if key in ('url','retrieved_at','published_at'):
                        origin=child['value'] if child['op']=='utc' else child
                        if origin['op'] not in ('get','get_root'):raise ValueError('Source URLs and timestamps must come from the provider response.')
                    provenance(child)
            elif expr['op']=='map':provenance(expr['item'])
            elif expr['op']=='choose':provenance(expr['then']);provenance(expr['otherwise'])
            if expr['op'] not in ('const','get','get_root','object'):
                if 'value' in expr:provenance(expr['value'])
                for child in expr.get('values',[]):provenance(child)
        provenance(data['output_transform']['expression'])
        version=self.registry.current(resource)
        rows=self.store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],data['contract_id']))
        if not rows or rows[0]['tool']!=data['tool']:raise ValueError('Approve this current tool contract explicitly before testing the transformations.')
        return {**data,'version':version,'approval':dict(rows[0]),'implementation':implementation()}

    def create(self, body, actor, guard=lambda:False):
        from .workflows import sensitive
        from .execution_authority import require_enabled
        from .workflow_persistence import dispatch_scope
        if (not isinstance(body,dict) or set(body)!={'profile','cases','authority','notice'} or body['authority'] is not True
                or body['notice']!=NOTICE or not isinstance(body['cases'],list) or not 1<=len(body['cases'])<=3):
            raise ValueError('Authorize one to three real public-input transformation checks.')
        profile=self.checked(body['profile']);before=digest(profile);started=time.time();artifacts=[]
        for supplied in body['cases']:
            if sensitive(supplied) or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:api[_-]?key|token|password)\s*[:=]',canonical(supplied),re.I):
                raise ValueError('Use public, non-sensitive test input.')
            validate(profile['contract_id'],supplied)
            native=apply(profile['input_transform'],supplied)
            def dispatch_guard():
                if guard() is not True:raise ValueError('Current highest-administrator authority is required.')
                require_enabled(self.store,'invoke');require_enabled(self.store,'workflow')
                if digest(self.checked(body['profile']))!=before:raise ValueError('The reviewed connection changed.')
            dispatch_guard()
            with dispatch_scope(dispatch_guard):
                result=self.runtime.proxy.execute(profile['resource_id'],profile['tool'],native,public=True)
            if not isinstance(result,dict) or result.get('ok') is not True or result.get('hash_verified') is not True:
                raise ValueError('The real native tool execution did not pass its connection check.')
            raw=result.get('result') or {};raw=raw.get('structuredContent',raw)
            normalized=self.output(profile,raw,supplied);validate(profile['contract_id'],supplied,normalized)
            artifacts.append(digest([supplied,normalized]))
        if guard() is not True or digest(self.checked(body['profile']))!=before:raise ValueError('Approval authority or connection changed during the test.')
        now=time.time();identity='io_'+secrets.token_hex(16)
        payload={**profile,'id':identity,'audience':NOTICE,'actor':actor,'created':now,'expires':now+86400,
                 'cases':len(artifacts),'artifact_hash':digest(artifacts)}
        self.registry.record(profile['version'],scope='contract',outcome='succeeded',started=started,finished=now,
            contract_id=profile['contract_id'],cases=len(artifacts),artifact_hash=digest(artifacts),dataset='generic-io-transform-v1')
        with self.store.tx() as db:
            if guard() is not True or digest(self.checked(body['profile']))!=before:
                raise ValueError('Current highest-administrator authority and unchanged connection are required.')
            db.execute('INSERT INTO workflow_io_profiles VALUES (?,?,?,?,?,NULL)',
                       (identity,canonical(payload),self.runtime.authority.signature(payload),now,payload['expires']))
        return {'id':identity,'expires':payload['expires'],'cases':len(artifacts),'artifact_hash':payload['artifact_hash']}

    def get(self, identity, *, resource_id=None, contract_id=None, tool=None):
        if type(identity) is not str or not re.fullmatch(r'io_[0-9a-f]{32}',identity):raise ValueError('Use a verified I/O profile reference.')
        rows=self.store.query('SELECT payload,signature,expires,revoked FROM workflow_io_profiles WHERE id=?',(identity,))
        if not rows or rows[0]['revoked'] is not None or rows[0]['expires']<=time.time():raise ValueError('The I/O profile expired or was revoked.')
        row=rows[0];payload=json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'],self.runtime.authority.signature(payload)) or payload.get('id')!=identity
                or payload.get('audience')!=NOTICE or payload.get('expires')!=row['expires']):raise ValueError('The I/O profile is invalid.')
        base={k:payload[k] for k in ('resource_id','tool','contract_id','input_transform','output_transform','status_checks')}
        checked=self.checked(base)
        if any(payload[k]!=v for k,v in checked.items()):raise ValueError('The tested connection, approval or transformer changed.')
        if (resource_id is not None and resource_id!=payload['resource_id'] or contract_id is not None and contract_id!=payload['contract_id']
                or tool is not None and tool!=payload['tool']):raise ValueError('The I/O profile belongs to a different connection or contract.')
        return payload

    def list(self):
        return [dict(r) for r in self.store.query('SELECT id,created,expires,revoked FROM workflow_io_profiles ORDER BY created DESC LIMIT 100')]

    def verified_evidence(self, version_id, contract_id, tool, evidence):
        """Accept generic evidence only when backed by a current signed profile."""
        if (not evidence or evidence['outcome']!='succeeded' or evidence['expires']<=time.time()
                or evidence['dataset_version']!='generic-io-transform-v1'):return False
        for row in self.list():
            if row['revoked'] is not None or row['expires']<=time.time():continue
            try:profile=self.get(row['id'],contract_id=contract_id,tool=tool)
            except (ValueError,KeyError,TypeError):continue
            if (profile['version']['id']==version_id and evidence['started']>=profile['approval']['created']
                    and evidence['artifact_hash']==profile['artifact_hash'] and evidence['cases']==profile['cases']):return True
        return False

    def revoke(self, identity):
        if type(identity) is not str or not re.fullmatch(r'io_[0-9a-f]{32}',identity):raise ValueError('Use a verified I/O profile reference.')
        with self.store.tx() as db:db.execute('UPDATE workflow_io_profiles SET revoked=? WHERE id=? AND revoked IS NULL',(time.time(),identity))
        return {'ok':True}
