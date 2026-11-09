"""Task list, relevance rule and snapshot assembly shared by the jobs refresher and the build script.

The snapshot feeds growth_pages and growth_catalog. Searches are supplied by the caller: the jobs
service searches its own store (task_pages_job), the script uses the public Explore API.
"""
import json
import os
import re
import tempfile
from datetime import datetime, timezone

from .growth_pages import MAX_AGENTS, MIN_AGENTS, clean, clean_agent

# (group, task phrase). Phrases are written as a person would type them into Explore.
TASKS = {
    'Weather, maps and travel': [
        'weather forecast', 'current weather', 'air quality', 'severe weather alerts', 'geocoding addresses',
        'reverse geocoding', 'route planning', 'distance between places', 'nearby places search', 'time zone lookup',
        'flight search', 'flight status', 'hotel search', 'travel itinerary', 'public transit directions',
        'country information', 'tide and marine weather', 'sunrise and sunset times', 'ip geolocation', 'map tiles'],
    'Search and web': [
        'web search', 'news search', 'scrape a web page', 'extract article text', 'search academic papers',
        'website screenshot', 'crawl a website', 'search reddit', 'search hacker news', 'youtube search',
        'image search', 'wikipedia lookup', 'domain whois lookup', 'check website uptime', 'rss feed reader',
        'sitemap extraction', 'search github repositories', 'search stack overflow', 'patent search', 'job search'],
    'Developer tools': [
        'github issues', 'github pull requests', 'code review', 'run python code', 'execute javascript',
        'package metadata', 'npm package info', 'pypi package info', 'dependency vulnerabilities', 'docker containers',
        'kubernetes cluster', 'ci build status', 'api documentation lookup', 'regex testing', 'generate unit tests',
        'browser automation', 'playwright testing', 'git repository analysis', 'code search', 'library documentation'],
    'Data and databases': [
        'postgres query', 'mysql query', 'sqlite database', 'mongodb query', 'redis cache',
        'csv analysis', 'excel spreadsheet', 'json transformation', 'data visualization chart', 'bigquery',
        'snowflake data warehouse', 'elasticsearch search', 'vector database search', 'time series data', 'convert file formats',
        'pdf extraction', 'ocr text from image', 'unit conversion', 'random data generation', 'qr code generation'],
    'Documents and knowledge': [
        'summarize a document', 'translate text', 'translate a document', 'knowledge base search', 'notion pages',
        'confluence pages', 'google docs', 'markdown conversion', 'note taking', 'retrieval augmented generation',
        'dictionary definitions', 'grammar check', 'text to speech', 'speech to text', 'meeting notes summary',
        'obsidian notes', 'read epub books', 'citation formatting', 'documentation search', 'language detection'],
    'Productivity and communication': [
        'calendar scheduling', 'send email', 'read email inbox', 'slack messages', 'discord bot',
        'telegram messages', 'todo list', 'project management tasks', 'jira issues', 'linear issues',
        'trello boards', 'google drive files', 'dropbox files', 'contact management', 'reminders',
        'time tracking', 'form submissions', 'sms messages', 'whatsapp messages', 'team chat summary'],
    'Finance and crypto': [
        'stock prices', 'stock market news', 'company financials', 'currency exchange rates', 'cryptocurrency prices',
        'crypto wallet balance', 'blockchain transactions', 'token prices on base', 'defi protocols', 'nft collections',
        'sec filings', 'economic indicators', 'invoice generation', 'tax calculation', 'personal budgeting',
        'payment processing', 'onchain analytics', 'ethereum gas prices', 'trading signals', 'portfolio tracking'],
    'Commerce and marketing': [
        'product search', 'price comparison', 'shopify store', 'ecommerce orders', 'seo analysis',
        'keyword research', 'social media posting', 'ad campaign performance', 'email marketing', 'customer reviews analysis',
        'lead generation', 'crm contacts', 'company enrichment', 'competitor analysis', 'brand monitoring'],
    'Media and creative': [
        'image generation', 'image editing', 'video generation', 'music generation', 'podcast search',
        'transcribe video', 'background removal', 'logo design', 'meme generation', 'photo search',
        'audio transcription', 'video summarization', 'presentation slides', 'diagram generation', 'font pairing'],
    'Health, science and education': [
        'medical literature search', 'drug information', 'clinical trials search', 'nutrition facts', 'fitness tracking',
        'chemistry compounds', 'math problem solving', 'physics calculations', 'astronomy data', 'genomics data',
        'language learning', 'quiz generation', 'flashcards', 'course recommendations', 'arxiv papers'],
    'Security and operations': [
        'vulnerability scanning', 'cve lookup', 'ssl certificate check', 'dns lookup', 'threat intelligence',
        'password strength check', 'malware analysis', 'log analysis', 'server monitoring', 'incident alerts',
        'cloud cost analysis', 'aws resources', 'cloudflare dns', 'network ping test', 'email deliverability check'],
    'Public data and legal': [
        'government open data', 'legal case search', 'company registry lookup', 'contract review', 'regulation lookup',
        'census statistics', 'election data', 'public holidays', 'sanctions screening', 'trademark search'],
    'Agents and AI models': [
        'call another ai model', 'llm comparison', 'agent memory', 'multi agent orchestration', 'prompt optimization',
        'embedding generation', 'sentiment analysis', 'named entity extraction', 'text classification', 'content moderation'],
}


def slugify(phrase):
    return re.sub(r'[^a-z0-9]+', '-', phrase.lower()).strip('-')


STOP = {'a', 'an', 'and', 'the', 'of', 'to', 'for', 'from', 'on', 'in', 'with', 'between', 'another', 'your', 'text'}


def stems(phrase):
    words = [w for w in re.findall(r'[a-z0-9]+', phrase.lower()) if w not in STOP and len(w) > 1]
    return [w if len(w) <= 4 else w[:max(4, len(w)-2)] for w in words]


def relevant(phrase, item):
    """The listing itself must mention the task: every key word, or all but one for longer phrases."""
    text = ' '.join(str(item.get(k) or '') for k in ('name', 'description')).lower()
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    words = stems(phrase)
    found = sum(1 for w in words if re.search(r'(?<![a-z0-9])'+re.escape(w), text))
    return found >= (len(words) if len(words) <= 2 else len(words)-1)


def flatten(item):
    readiness = item.get('connection_readiness') or {}
    value = dict(item)
    value['verified_at'] = (readiness.get('verified_at') if readiness.get('verified_callable')
                            and readiness.get('evidence_scope') == 'execution' else None)
    return value


KINDS = ('a2a', 'mcp', 'x402')


def plan(categories, only=None):
    """Every search the snapshot needs, in order: two per task, then two per category and protocol."""
    steps = []
    for group, phrases in TASKS.items():
        for phrase in phrases:
            if only and slugify(phrase) not in only:
                continue
            steps += [('task', group, phrase, True, 12), ('task', group, phrase, False, 24)]
    for category in sorted(categories):
        for kind in KINDS:
            steps += [('catalog', category, kind, True, 300), ('catalog', category, kind, False, 300)]
    return steps


class Assembler:
    """Collects search results step by step; snapshot() returns the finished document."""

    def __init__(self):
        self.tasks = {}
        self.catalog = {}

    def add(self, step, items):
        if step[0] == 'task':
            _, group, phrase, _, _ = step
            agents = self.tasks.setdefault((group, phrase), {})
            for item in items:
                if len(agents) >= MAX_AGENTS*2 or item.get('id') in agents or not relevant(phrase, item):
                    continue
                agent = clean_agent(flatten(item))
                if agent:
                    agents[agent['id']] = agent
        else:
            for item in items:
                agent = clean_agent(flatten(item))
                if agent and agent['id'] not in self.catalog:
                    self.catalog[agent['id']] = agent

    def needs(self, step):
        """The plain search for a task is skipped once the checked search filled it."""
        return not (step[0] == 'task' and not step[3] and len(self.tasks.get((step[1], step[2]), {})) >= MAX_AGENTS)

    def snapshot(self, stats=None, captured_at=None):
        tasks = [{'slug': slugify(phrase), 'title': phrase[:1].upper()+phrase[1:], 'query': phrase, 'group': group,
                  'agents': list(agents.values())[:MAX_AGENTS]}
                 for (group, phrase), agents in self.tasks.items() if len(agents) >= MIN_AGENTS]
        value = {'version': 1, 'captured_at': captured_at or datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 'tasks': tasks, 'catalog': list(self.catalog.values())}
        if stats:
            value['stats'] = {'catalog_snapshot': stats}
        return value


def write(path, snapshot):
    if clean(snapshot) is None:
        raise ValueError('The snapshot failed validation; nothing was written.')
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix='.task-pages.')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(snapshot, out, ensure_ascii=False, separators=(',', ':'))
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
