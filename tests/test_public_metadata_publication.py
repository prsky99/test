"""Search metadata must agree before JavaScript, after navigation and across URLs."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import pytest

from agent_market.concierge.public_metadata import PAGES, ORIGIN, robots, sitemap, url

ROOT=Path(__file__).resolve().parents[1]


class Head(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.metas={}
        self.canonicals=[]
        self.feed(value)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta':
            self.metas.setdefault(attrs.get('name') or attrs.get('property'),[]).append(attrs.get('content'))
        if tag=='link' and attrs.get('rel')=='canonical':
            self.canonicals.append(attrs['href'])


@pytest.mark.parametrize('panel',PAGES)
def test_public_pages_have_unique_consistent_metadata_and_visible_requested_panel(panel):
    filename,title,description=PAGES[panel]
    value=(ROOT/'new/en'/filename).read_text()
    head=Head(value)
    assert head.canonicals==[url(panel)]
    assert head.metas['description']==[description]
    assert head.metas['og:title']==head.metas['twitter:title']==[title]
    assert head.metas['og:url']==head.metas['twitter:url']==[url(panel)]
    assert head.metas['og:image:type']==['image/png']
    assert head.metas['robots'][0].startswith('index, follow')
    assert re.search(r'<html lang="en"',value)
    assert not re.search(r'[\uac00-\ud7af]',value)
    section=re.search(r'<section\b[^>]*data-panel="'+panel+r'"[^>]*>',value)[0]
    assert 'hidden' not in section
    structured=json.loads(re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',value,re.S)[1])
    entity=structured['@graph'][-1]
    assert entity['url']==url(panel) and entity['description']==description
    # Discoverable HTML links, not a navigation button-only graph.
    assert 'href="'+url('test')+'"' in value
    assert 'href="'+url('workflows')+'"' in value


def test_all_reference_and_account_pages_have_noindex_metadata():
    live={row[0] for row in PAGES.values()}
    paths=list((ROOT/'new/en').glob('*.html'))
    assert len(paths)>=43
    for path in paths:
        if path.name in live:
            continue
        head=Head(path.read_text())
        assert len(head.canonicals)==1
        assert head.metas['description'] and 'noindex' in head.metas['robots'][0]


def test_all_crawler_groups_keep_private_actions_out_and_public_guides_in():
    parser=RobotFileParser()
    text=robots(ORIGIN)
    assert '/admin' not in text
    parser.parse(text.splitlines())
    for bot in ('Googlebot','OAI-SearchBot','ClaudeBot','PerplexityBot','GPTBot','UnknownBot'):
        assert parser.can_fetch(bot,url('test'))
        assert parser.can_fetch(bot,ORIGIN+'/llms.txt')
        for path in ('/customer/workspaces','/api/customer-auth/login','/api/gateway/mcp/1',
                     '/api/task-updates/123/action','/api/owned-data-agents/technology-news/mcp'):
            assert not parser.can_fetch(bot,ORIGIN+path)
    root=ET.fromstring(sitemap(ORIGIN))
    assert len(root)==9 and '<lastmod>' not in sitemap(ORIGIN)
    assert not any('#' in element.text for element in root.iter() if element.text)
