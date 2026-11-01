"""English server-rendered category previews built from current public evidence."""
import html
import json
import time
from datetime import datetime,timezone

from ..broker.categories import CATEGORIES
from ..concierge.fast_chat import display_label
from ..concierge.connections import gateway_agent_url
from .projection import current_states
from .storage import ready


def category_links(front):
    # Category landing pages survive changes in the available verified inventory.
    return ['/agents/category/'+category for category in sorted(CATEGORIES)]


def category_page(front,category):
    if category not in CATEGORIES:raise ValueError('NOT_FOUND')
    from ..concierge.discovery import discovery_store
    rows=[];states={}
    with discovery_store(front.store)as store:
        after=0
        # A bounded publication scan avoids a full category search per crawler.
        # Recheck current contracts: a publication alone is not execution proof.
        for _ in range(8) if ready(store) else ():
            batch=store.query('''SELECT p.resource_id FROM adoption_publications p
                JOIN resources r ON r.id=p.resource_id
                WHERE p.verified=1 AND p.expires>? AND r.active=1
                AND r.kind IN ('a2a','mcp') AND r.category=? AND p.resource_id>?
                ORDER BY p.resource_id LIMIT 96''',(time.time(),category,after))
            if not batch:break
            resources,current=current_states(store,[r['resource_id']for r in batch])
            states.update(current)
            for item in batch:
                rid=item['resource_id']
                if current.get(rid,{}).get('verified'):
                    resource=resources[rid]
                    rows.append({'id':rid,'name':resource.get('name'),'kind':resource['kind'],
                        'url':gateway_agent_url(rid,resource['kind'])})
                if len(rows)==12:break
            if len(rows)==12 or len(batch)<96:break
            after=batch[-1]['resource_id']
    category_name=CATEGORIES[category].name_en or category.replace('_',' ').title()
    esc=lambda value:html.escape(str(value),quote=True)
    canonical='https://agentconcierge.biz/agents/category/'+category
    title=category_name+' Agents — Agent Concierge'
    description='Explore recorded execution checks and public connections for '+category_name.lower()+'. Revalidate before running.'
    entries=[]
    if not rows:
        entries.append('<li>No agents with a current successful execution check are available in this preview. Explore the catalog or check again later.</li>')
    for row in rows:
        state=states[row['id']]
        entries.append('<li><article><h2>'+esc(display_label(row.get('name'),'Verified agent'))+'</h2><p>'+esc(row['kind'].upper())+
            '</p><p>Recorded execution check: '+esc(datetime.fromtimestamp(state['verified_at'],timezone.utc).isoformat())+'</p><a href="'+esc(row['url'])+'">Connection details</a></article></li>')
    data={'@context':'https://schema.org','@type':'CollectionPage','name':title,'description':description,'url':canonical}
    structured=json.dumps(data,ensure_ascii=True).replace('<','\\u003c')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>'+esc(title)+'</title><meta name="description" content="'+esc(description)+'"><meta property="og:title" content="'+esc(title)+'">'
        '<meta property="og:description" content="'+esc(description)+'"><meta property="og:url" content="'+esc(canonical)+'">'
        '<link rel="canonical" href="'+esc(canonical)+'"><link rel="stylesheet" href="/new/en/assets/styles.css">'
        '<script type="application/ld+json">'+structured+'</script></head><body><main><a href="/">Agent Concierge</a><h1>'+esc(category_name)+
        ' Agents</h1><p>'+esc(description)+'</p><ul>'+''.join(entries)+'</ul>'+about_category(CATEGORIES[category],category_name)+
        '<p>Checks describe recorded evidence and do not guarantee continuous availability.</p>'
        '<a href="/new/en/explore.html">Explore agents</a></main></body></html>')


def about_category(definition,category_name):
    """What the category covers and how listings are checked, so the page explains itself to readers and crawlers."""
    esc=lambda value:html.escape(str(value),quote=True)
    return ('<section><h2>About '+esc(category_name)+'</h2><p>'+esc(definition.description)+'</p></section>'
        '<section><h2>How these listings are checked</h2><p>Agent Concierge collects public A2A agents and MCP servers, '
        'checks that their endpoints respond, and records execution checks against their published tools. A listing appears '
        'in this preview only while its latest recorded check for the current connection version succeeded. The date shown '
        'is when that check ran; providers can change or go offline afterwards, so revalidate the connection before you rely on it.</p>'
        '<p>To compare options for a specific task, describe the task in <a href="/new/en/chat.html">Chat</a> to receive up to three '
        'relevant agents, or search the full catalog, including listings that are not yet verified, in '
        '<a href="/new/en/explore.html">Explore</a>.</p></section>')
