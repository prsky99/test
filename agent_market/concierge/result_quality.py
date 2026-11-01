"""Recognize explicit upstream non-answers without rejecting legitimate zero results."""
import json
import re

NON_ANSWER=re.compile(r'^(?:mcp\s+)?(?:no\s+(?:response|output)|empty\s+(?:response|output)|\uc751\ub2f5\s*\uc5c6\uc74c|\ucd9c\ub825\s*\uc5c6\uc74c)(?:\s+(?:from\s+)?(?:mcp|agent|server))?$',re.I)

def _useful(value,task='',depth=0):
    if depth>4:return False
    health=bool(re.search(r'\b(?:ping|health|connectivity)\b',str(task),re.I))
    if isinstance(value,str):
        text=value.strip().strip('[](){}').strip()
        if not text or text.lower()in('null','none','undefined')or NON_ANSWER.fullmatch(text):return False
        if not health and text.lower()in('pong','ok','success','completed'):return False
        if re.search(r'executed task deterministically with 100% schema conformance',value,re.I):return False
        if value.lstrip().startswith('{')and len(value)<=65536:
            try:parsed=json.loads(value)
            except (TypeError,ValueError,RecursionError):pass
            else:return _useful(parsed,task,depth+1)
        return True
    if isinstance(value,dict):
        if not value:return False
        if not health and value.get('response')=='pong':return False
        if value.get('error')and not any(value.get(k)for k in ('results','articles','answer','content')):return False
        if isinstance(value.get('findings'),str)and not _useful(value['findings'],task,depth+1):return False
        metadata = {'status','ok','success','message','request_id','task_id','id','code','timestamp','metadata'}
        if not health and set(value) <= metadata:
            if re.search(r'\bstatus\b',str(task),re.I):
                return bool(value.get('status'))
            message = value.get('message')
            if (not isinstance(message,str) or not _useful(message,task,depth+1)
                    or re.fullmatch(r'(?:request\s+)?(?:processed|done|accepted|completed|queued)[.!]?',message.strip(),re.I)):
                return False
        return True
    return False

def usable_a2a_parts(parts,task=''):
    if not isinstance(parts,list):return False
    for part in parts:
        if not isinstance(part,dict):continue
        kind=part.get('kind')or part.get('type')or next((k for k in ('text','data','file')if k in part),None)
        if kind=='text'and isinstance(part.get('text'),str)and _useful(part['text'],task):return True
        if kind=='data'and isinstance(part.get('data'),dict)and _useful(part['data'],task):return True
        if kind=='file'and isinstance(part.get('file'),dict)and any(part['file'].get(k)for k in ('uri','bytes')):return True
    return False
