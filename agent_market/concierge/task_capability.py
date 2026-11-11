"""Match requested operations and input objects, not incidental catalog words."""
import re
from .chat_task_spec import canonical_text


def text_task(task):
    from .selection import ALIASES
    text=canonical_text(task).lower()
    for source,target in sorted(ALIASES.items(),key=lambda pair:-len(pair[0])):
        if source[0].isascii():
            text=re.sub(r'\b'+re.escape(source)+r'\b',' '+target+' ',text)
        else:
            text=text.replace(source,' '+target+' ')
    return text


def needs_specific_action(task):
    text=text_task(task)
    return bool(re.search(r'\b(?:translat\w*|summari[sz]\w*|weather|forecast|sql|spf|dkim|dmarc|dns)\b|\bweb\s+search\b|\b(?:generate|create|render)\b.{0,30}\b(?:image|picture)\b|\b(?:current|latest|spot)\s+price\b|\bsend\b.{0,30}\b(?:emails?|mail|messages?)\b',text))


def matches(task,tool,kind,resource=None):
    from .task_conditions import assess
    if assess(task, resource or {}, tool)['status'] == 'mismatch':
        return False
    request=text_task(task)
    name=str(tool.get('name')or tool.get('id')or'').replace('_',' ').lower()
    from .selection import _tool_purpose
    purpose=_tool_purpose(tool.get('description')).lower()
    text=name+' '+purpose
    context=text+' '+str((resource or {}).get('name')or'').lower()+' '+str((resource or {}).get('description')or'').lower()
    schema=tool.get('inputSchema')
    props=schema.get('properties',{})if isinstance(schema,dict)else{}
    if not isinstance(props,dict):props={}
    if re.search(r'\btranslat\w*\b',request):
        existing = bool(re.search(r'\b(?:search|find|browse)\b.{0,30}\b(?:existing|published|historical|translations)\b', request))
        if not existing and not re.search(r'\btranslat(?:e|es|ing|or)\b', name) and not re.search(
                r'\btranslat(?:e|es|ing)\b.{0,50}\b(?:text|content|sentences?|documents?|messages?|input)\b', purpose):
            return False
        if re.search(r'\b(?:quran|ayahs?|verses?|bible|scripture)\b',context)and not re.search(r'\b(?:quran|ayahs?|verses?|bible|scripture)\b',request):return False
        if kind=='mcp'and not any(re.search(r'text|content|sentence|document|query|source|input',key,re.I) for key in props):return False
    if re.search(r'\b(?:generate|create|render)\b.{0,30}\b(?:image|picture)\b',request):
        if re.search(r'\b3d\s+models?\b',text)and not re.search(r'\b3d\b',request):return False
        if not re.search(r'\b(?:generat\w*|creat\w*|render\w*|synthesi\w*)\b.{0,70}\b(?:images?|pictures?|artwork)\b|\b(?:image|picture)\s+generat\w*',text):return False
        if re.search(r'\b(?:marketplace|work contracts?|job board|hire an? agent)\b',purpose):return False
    if re.search(r'\bsummari[sz]\w*\b',request)and re.search(r'\b(?:videos?|youtube|podcasts?|episodes?)\b',request):
        # A channel's video list is not a summary; the tool or listing must summarize or transcribe.
        if not re.search(r'\b(?:summar\w*|transcri\w*|captions?|subtitles?)\b',context):return False
    if re.search(r'\bsummari[sz]\w*\b',request)and re.search(r'\b(?:meeting|minutes)\b',request):
        if not re.search(r'\b(?:meeting|minutes|transcripts?|conversations?)\b',text)and not re.search(r'\bsummari[sz]\w*\s+(?:(?:any|user|provided)\s+)?(?:text|content|documents?)\b',purpose):return False
        if kind=='mcp'and not any(re.search(r'text|transcript|notes|content|document|input',key,re.I)for key in props):return False
        if re.search(r'\baction items?\b',request)and not re.search(r'\b(?:action items?|next steps?|decisions?)\b',purpose):return False
    if re.search(r'\b(?:bitcoin|btc|ethereum|eth)\b',request)and re.search(r'\b(?:prices?|quotes?)\b',request):
        if not re.search(r'\b(?:prices?|quotes?|exchange rates?|spot)\b',text):return False
        if re.search(r'\b(?:hiring|recruit\w*|job)\b',purpose):return False
        if re.search(r'\b(?:candles?|ohlcv|historical)\b',purpose)and not re.search(r'\b(?:candles?|ohlcv|historical|history)\b',request):return False
        if re.search(r'\b(?:liquidation|implied|probabilit\w*|power[- ]law|valuation|predictions?|forecasts?|when will)\b',text)and not re.search(r'\b(?:liquidation|implied|probabilit\w*|power[- ]law|valuation|risk|predictions?|forecasts?|when will)\b',request):return False
    if re.search(r'\bweb\s+search\b',request)and not re.search(r'\bgames?\b',request):
        if re.search(r'\b(?:video games?|gaming|game library)\b',purpose):return False
        if not re.search(r'\bweb\s+search\b|\bsearch\s+(?:the\s+)?(?:web|internet)\b',name)and not re.search(r'\b(?:search\w*\s+(?:(?:the|live|public)\s+){0,2}(?:web|internet)|live web pages)\b',purpose):
            if kind!='x402'or not re.search(r'\bweb search\b',purpose):return False
    if re.search(r'\bsend\b.{0,30}\b(?:emails?|mail|messages?)\b',request):
        if not re.search(r'\b(?:send|deliver)\w*\s+(?:an?\s+|custom\s+|outbound\s+)?(?:emails?|mail|messages?)\b|\bemail\s+(?:send|deliver)\w*',text):return False
        if kind=='mcp'and not any(re.search(r'body|content|message|text',key,re.I)for key in props):return False
    if re.search(r'\bsql\b',request)and re.search(r'\b(?:read|run|execut|query)\w*',request):
        if not re.search(r'\b(?:run|execut|query)\w*\b',text):return False
        if re.search(r'\b(?:validat|transpil|convert|synthesi|generat|explain|analy[sz])\w*',name):return False
        if re.search(r'\bpostgres(?:ql)?\b',request)and re.search(r'\bclickhouse\b',context):return False
    if re.search(r'\b(?:papers?|scholarly articles?)\b',request)and re.search(r'\b(?:search|find|research)\b',request):
        if kind=='mcp'and not set(props).intersection({'query','q','search','topic','keywords','keyword'}):return False
        if re.search(r'\bsummari[sz]\w*\b',name)and not re.search(r'\bsearch\w*\b',purpose):return False
        if re.search(r'\b(?:archives?|collection|corpus)\b',context)and not re.search(r'\b(?:archives?|collection|corpus)\b',request):
            if not re.search(r'\b(?:search|find|query|discover)\w*\s+(?:(?:academic|research|scholarly|scientific)\s+){0,2}(?:papers?|articles?|publications?|literature|works)\b',purpose):return False
    if re.search(r'\bweb\s+search\b',request)and re.search(r'\b(?:collection|corpus)\b',context):
        if not re.search(r'\b(?:search|query)\w*\s+(?:the\s+|live\s+|public\s+)?(?:web|internet)\b',purpose):return False
    if re.search(r'\b(?:weather|forecast)\b',request):
        if (not re.search(r'\b(?:marketplace|catalog|directory|providers?|agents?)\b', request)
                and re.search(r'\b(?:find|search|list|discover|recommend)\w*\s+(?:(?:a|an|the|available|matching|weather|forecast|specialist|best|mcp|a2a)\s+){0,5}(?:agents?|providers?|listings?|endpoints?|tools?)\b', purpose)):
            return False
        if re.search(r'\b(?:tools?|catalog|directory|park status)\b',text)and not re.search(r'\b(?:catalog|directory|tools?)\b',request):return False
        # A weather-alerts request is served by an alerts tool whose own purpose names weather alerts
        # ("get_alerts: Get active NWS weather alerts for a US state", 11-11 real task p12).
        alerts_tool = (re.search(r'\b(?:alerts?|warnings?|watches)\b', request)
                       and re.search(r'\b(?:alerts?|warnings?)\b', name)
                       and re.search(r'\bweather\s+(?:alerts?|warnings?|watches)\b', purpose))
        if not alerts_tool and not re.search(r'\b(?:weather|forecast|temperature)\b',name)and not re.search(r'\b(?:get|fetch|return|provide|retrieve|check)\w*\s+(?:(?:the|current|local|daily|hourly|live|a|an)\s+){0,3}(?:weather|forecast|temperature)\b',purpose):return False
        domains=(r'\b(?:ski|skiing|snowboard)\b',r'\b(?:camper|camping)\b',
                 r'\b(?:construction|roofing|painting|remodeling)\b')
        for domain in domains[:2]:
            if re.search(domain,purpose)and not re.search(domain,request):return False
        if re.search(r'\bsuitability\b',purpose)and not re.search(r'\bsuitability\b',request):
            if not any(re.search(domain,purpose)and re.search(domain,request)for domain in domains):return False
        if kind=='mcp'and re.search(r'\b(?:seoul|tokyo|london|paris|berlin|sydney|toronto)\b',request):
            if set(props).intersection({'country','country_code','countryCode'})and not set(props).intersection({'location','city','place','lat','latitude','coordinates'}):return False
    if re.search(r'\b(?:spf|dkim|dmarc|dns)\b',request)and re.search(r'\b(?:check|lookup|verify|inspect|read|audit|test)\w*\b',request):
        if re.search(r'\b(?:add|create|update|set|delete|remove|publish|write|append)\b',name):return False
        if not re.search(r'\b(?:check|lookup|verify|inspect|read|audit|test|resolve|get|fetch|analy[sz]e)\w*\b',text):return False
    if re.search(r'\bgithub\b', request) and re.search(r'\b(?:issues?|pull requests?)\b', request):
        if not re.search(r'\b(?:issues?|pull requests?)\b', text):return False
        if kind == 'mcp' and re.search(r'\b(?:search|find)\b', request):
            if not set(props).intersection({'query','q','search','keywords','keyword'}):return False
            if not re.search(r'\b(?:issues?|pull requests?)\b', name) and not re.search(
                    r'\b(?:search|find|query)\w*\s+(?:(?:for|public|open|closed|all|the|github)\s+){0,4}(?:github\s+)?(?:issues?|pull requests?)\b', purpose):return False
    if re.search(r'\bgithub\b',request)and re.search(r'\b(?:repositories|repos|projects)\b',request):
        if re.search(r'\b(?:discussions|issues|pull requests|commits|diagrams)\b',name):return False
        if kind=='mcp'and not re.search(r'\btrending\b',request)and not set(props).intersection({'query','q','search','keyword','keywords','topic'}):return False
    return True
