"""Read-only whole-catalog compatibility audit; never contact agent providers."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from agent_market.collector import usage
from agent_market.concierge.execution_policy import admit, safe_registered_tool, validate_arguments, ExecutionDenied
from agent_market.concierge.recommendation_security import public_schema


def previous_policy(spec):
    name=spec.get('name')
    if not isinstance(name,str) or not name:return False
    annotations=spec.get('annotations') or {}
    schema=spec.get('inputSchema')
    required=schema.get('required',[]) if isinstance(schema,dict) else spec.get('required',[])
    if (not isinstance(annotations,dict) or not isinstance(required,list)
            or any(not isinstance(k,str) for k in required) or not isinstance(spec.get('description') or '',str)):
        return False
    return usage.is_safe_tool({**spec,'required':required}) and not usage._DENY.search(
        re.sub(r'(?i)(?<![a-z0-9])signals?(?![a-z0-9])','feed',name))


def audit(database, output, names_file=None):
    started=time.time();counts=collections.Counter();admission=collections.Counter();changed=collections.Counter()
    cache={};changed_names=set();errors=[];fingerprint=hashlib.sha256()
    with sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        for row in db.execute('SELECT id,kind,url,active,health_status,eval_security,price_usdc,auth_observed,auth_declared,usage_tools FROM resources'):
            resource=dict(row);kind=resource['kind'];counts['resources']+=1;counts['resources_'+kind]+=1
            try:admit(resource,public=True,authorize_charge=kind=='x402')
            except ExecutionDenied as exc:admission[kind+': '+str(exc)]+=1
            else:admission[kind+': eligible']+=1
            if kind!='mcp':continue
            try:tools=json.loads(resource['usage_tools'] or '[]')
            except (ValueError,TypeError):counts['invalid_tool_json']+=1;continue
            if not isinstance(tools,list):counts['invalid_tool_container']+=1;continue
            if tools:counts['mcp_resources_with_tool_definitions']+=1
            for spec in tools:
                counts['tool_occurrences']+=1
                if not isinstance(spec,dict):counts['invalid_tool_entry']+=1;continue
                try:
                    before=bool(previous_policy(spec));after=bool(safe_registered_tool(spec))
                    name=spec.get('name','');fingerprint.update(json.dumps([resource['id'],name,after]).encode())
                    counts['previously_allowed' if before else 'previously_refused']+=1
                    counts['now_allowed' if after else 'now_refused']+=1
                    if after and not before:
                        counts['confirmed_noun_collision_occurrences_fixed']+=1;changed_names.add(name)
                        match=usage._DENY.search(name)
                        changed[match[0].lower() if match else 'other']+=1
                    if before and not after:counts['new_conservative_refusals']+=1
                    if not after:continue
                    published=public_schema(spec)
                    compact=usage.compact_tools([published])[0] if 'inputSchema' in published else published
                    params=compact.get('params',{});required=compact.get('required',[])
                    if not isinstance(params,dict) or not isinstance(required,list) or any(k not in params for k in required):
                        counts['manual_input_required']+=1;continue
                    sample=usage.example_arguments({**compact,'params':params},None)
                    if sample is None:counts['manual_input_required']+=1;continue
                    schema=spec.get('inputSchema',{'type':'object','properties':spec.get('params',{}),'required':spec.get('required',[])})
                    key=json.dumps([schema,sample],sort_keys=True,allow_nan=False)
                    if key not in cache:
                        try:validate_arguments(spec,sample)
                        except ExecutionDenied as exc:cache[key]=str(exc)
                        else:cache[key]=None
                    counts['generic_example_rejected' if cache[key] else 'valid_generic_example']+=1
                except Exception as exc:
                    counts['audit_exceptions']+=1
                    if len(errors)<10:errors.append({'resource_id':resource['id'],'error':type(exc).__name__})
    mutation_count=0
    for name in changed_names:
        for mutated in ('delete_'+name,name+'_delete',name+'_sign_transaction',name+'_send_message','create_'+name):
            spec={'name':mutated,'annotations':{'readOnlyHint':True},'params':{},'required':[]}
            if safe_registered_tool(spec):
                raise RuntimeError('A destructive mutation was incorrectly accepted.')
            mutation_count+=1
    result={'mode':'read-only-full-local-catalog-no-provider-dispatch','counts':dict(counts),
        'resource_admission':dict(admission),'fixed_original_substring_matches':dict(changed),
        'fixed_unique_tool_names':len(changed_names),'schema_example_validation_cases':len(cache),
        'destructive_mutations_refused':mutation_count,'audit_exceptions':errors,
        'catalog_policy_fingerprint_sha256':fingerprint.hexdigest(),
        'duration_seconds':round(time.time()-started,2),'live_provider_calls':0,
        'limits':['Catalog admission is metadata compatibility, not proof of provider behavior or availability.',
                  'Unsafe/credential/authorization/schema/manual-input refusals are retained, not force-enabled.',
                  'Full live schemas and third-party availability require separate controlled live checks.']}
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
    if names_file:Path(names_file).write_text(json.dumps(sorted(changed_names),indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database');parser.add_argument('output');parser.add_argument('--names-file')
    args=parser.parse_args();audit(args.database,args.output,args.names_file)
