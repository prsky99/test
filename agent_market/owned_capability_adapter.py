"""Exact first-party projections into the private documentation and news contracts."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from .capability_contracts import validate
from .capability_registry import decoded, digest
from .concierge.execution_policy import validate_arguments
from .owned_data_agents.catalog import tool_spec

PROFILE = 'owned-research-docs-v1'
ENDPOINT = 'https://agentconcierge.biz/api/owned-data-agents/research-papers/mcp'
TOOL = 'search_research_papers'
CONTRACT = 'docs.search.v1'
FILES = ['owned_capability_adapter.py','capability_adapters.py','owned_data_agents/catalog.py',
         'owned_data_agents/engine.py','owned_data_agents/english.py','owned_data_agents/dispatch.py']
NEWS_PROFILE = 'owned-technology-news-v1'
NEWS_ENDPOINT = 'https://agentconcierge.biz/api/owned-data-agents/technology-news/mcp'
NEWS_TOOL = 'search_technology_news'
NEWS_CONTRACT = 'news.search.v1'
IMPLEMENTATION = digest([hashlib.sha256(Path(__file__).parent.joinpath(name).read_bytes()).hexdigest() for name in FILES])


def _news_profile(resource):
    if resource.get('source') != 'agentconcierge-owned' or resource.get('key') != 'agentconcierge-owned:technology-news':
        raise ValueError('Use the exact registered first-party news connection.')
    found=[t for t in decoded(resource.get('usage_full_tools'),[]) if isinstance(t,dict) and t.get('name')==NEWS_TOOL]
    expected=tool_spec('technology-news')
    if len(found)!=1 or {k:found[0].get(k) for k in expected} != expected:
        raise ValueError('The first-party news schema changed.')
    return {'id':NEWS_PROFILE,'schema_hash':digest(expected),'implementation_hash':IMPLEMENTATION,
        'input_notice':'English Hacker News stories for public technology keywords. Queries use at most 160 characters; each call returns up to five stories, newest first, from the requested start time.'}


def profile(resource, contract, tool):
    if resource.get('url') == NEWS_ENDPOINT and contract == NEWS_CONTRACT and tool == NEWS_TOOL:
        return _news_profile(resource)
    if resource.get('url') != ENDPOINT or contract != CONTRACT or tool != TOOL:return None
    if resource.get('source') != 'agentconcierge-owned' or resource.get('key') != 'agentconcierge-owned:research-papers':
        raise ValueError('Use the exact registered first-party research connection.')
    found=[t for t in decoded(resource.get('usage_full_tools'),[]) if isinstance(t,dict) and t.get('name')==TOOL]
    expected=tool_spec('research-papers')
    if len(found)!=1 or {k:found[0].get(k) for k in expected} != expected:
        raise ValueError('The first-party research schema changed.')
    return {'id':PROFILE,'schema_hash':digest(expected),'implementation_hash':IMPLEMENTATION,
        'input_notice':'English public research records. Queries use at most 500 characters; each call returns up to five sources. Cached records retain their original retrieval time.'}


def arguments(resource, contract, tool, supplied, *, expected=None):
    current=profile(resource,contract,tool)
    if current is None or expected is not None and current!=expected:raise ValueError('The reviewed research connection changed.')
    if current['id']==NEWS_PROFILE:
        validate(NEWS_CONTRACT,supplied)
        if supplied['language']!='en' or len(supplied['query'])>160:
            raise ValueError('This news connection supports English queries of at most 160 characters.')
        native={'query':supplied['query'],'limit':min(supplied['limit'],5)}
        validate_arguments(tool_spec('technology-news'),native)
        return native
    validate(CONTRACT,supplied)
    if supplied['language']!='en':raise ValueError('This research connection supports English output.')
    native={'query':supplied['query'],'limit':min(supplied['limit'],5)}
    validate_arguments(tool_spec('research-papers'),native)
    return native


def _normalize_news(supplied, output):
    validate_arguments({'inputSchema':tool_spec('technology-news')['outputSchema']},output)
    if output['agent']!='technology-news' or output['data']['query']!=supplied['query']:
        raise ValueError('The news output does not match the reviewed request.')
    observed=output['retrieved_at'];parsed=datetime.fromisoformat(observed.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset()!=timezone.utc.utcoffset(parsed):
        raise ValueError('The source retrieval timestamp must be UTC.')
    start=datetime.fromisoformat(supplied['from_utc'].replace('Z','+00:00'))
    rows=output['data']['items']
    if len(rows)>min(supplied['limit'],5):raise ValueError('The source result limit changed.')
    # Stories before the requested start are omitted, never re-dated.
    kept=[r for r in rows if datetime.fromisoformat(r['published_at'].replace('Z','+00:00'))>=start]
    items=[{'title':r['title'],'url':r['url'],'source':r['source'],'published_at':r['published_at'],
        'retrieved_at':observed,'summary':'Hacker News story submitted '+r['published_at'][:10]+'.'} for r in kept]
    value={'items':items,'partial':bool(output['data']['partial'] or len(kept)<len(rows)
        or output['cache']['status']=='stale_cache' or supplied['limit']>5)}
    validate(NEWS_CONTRACT,supplied,value)
    return value


def normalize(resource, contract, tool, supplied, output, *, expected=None):
    arguments(resource,contract,tool,supplied,expected=expected)
    if profile(resource,contract,tool)['id']==NEWS_PROFILE:
        return _normalize_news(supplied, output)
    validate_arguments({'inputSchema':tool_spec('research-papers')['outputSchema']},output)
    if output['agent']!='research-papers' or output['data']['query']!=supplied['query']:
        raise ValueError('The research output does not match the reviewed request.')
    observed=output['retrieved_at'];parsed=datetime.fromisoformat(observed.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset()!=timezone.utc.utcoffset(parsed):
        raise ValueError('The source retrieval timestamp must be UTC.')
    if len(output['data']['items'])>min(supplied['limit'],5):raise ValueError('The source result limit changed.')
    items=[{'title':r['title'],'url':r['url'],
        'excerpt':'Public bibliographic record. DOI: '+r['doi'],
        'version':r['publication_date'] or 'Undated bibliographic record','retrieved_at':observed}
        for r in output['data']['items']]
    value={'items':items,'partial':bool(output['data']['partial'] or output['cache']['status']=='stale_cache' or supplied['limit']>5)}
    validate(CONTRACT,supplied,value)
    return value
