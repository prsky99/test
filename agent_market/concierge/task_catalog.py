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


# Task pages built from the evidence catalog alone (11-10): phrases that recur in the names and
# descriptions of agents with recorded evidence. 'title|term' when the listing wording differs
# from the page title. A page needs CATALOG_MIN listings that contain the term as a phrase in the
# name or the opening of the description (LEAD characters), within the matches' main category.
# Phrases whose matches were reviewed and found mixed (e.g. 'base64', 'crm', 'gas price') are left out.
CATALOG_TASKS = {
    'Weather, maps and travel': [ 'earthquake data|earthquakes',
        'wildfire data|wildfire', 'space weather', 'moon phase', 'places search',
        'local business search|local business', 'restaurant recommendations|restaurants', 'flight prices',
        'concert tickets|concerts',
        'tide predictions|tide', 'airport information|airport', 'aviation weather|metar', 'flood risk|flood', 'elevation data|elevation', 'census geocoding|census'],
    'Search and web': [
        'clean markdown', 'llms txt', 'robots txt check|robots txt', 'link preview', 'web scraping', 'headless browser', 'google search', 'x search', 'fact check', 'wikipedia summary',
        'schema org markup|schema org', 'seo audit', 'ai visibility', 'ai crawler access|ai crawler', 'domain check',
        'domain age', 'domain availability', 'whois lookup|whois', 'dns records',
        'mx records', 'tls certificate', 'security headers check', 'status page', 'app store data|app store',
        'youtube transcript', 'youtube channel', 'linkedin profile', 'social posts', 'instagram posts',
        'brand mentions', 'influencer search|influencer',
        'open graph metadata|open graph', 'redirect chain check|redirect chain'],
    'Developer tools': [
        'npm package', 'package version', 'known vulnerabilities', 'cisa kev', 'github repo', 'json schema',
        'regex tools|regex', 'uuid generator|uuid', 'cron expression', 'terraform',
        'license check', 'tool search', 'chat completions', 'llm inference', 'llm pricing',
        'text to image', 'semantic search', 'knowledge graph',
        'jwt decode|jwt', 'rerank'],
    'Data and databases': [
        'barcode lookup|barcode', 'word count', 'business days',
        'iban validation|iban', 'email validation', 'isin lookup|isin', 'exif metadata|exif'],
    'Documents and knowledge': [
        'translation services|translation', 'research papers', 'semantic scholar', 'academic papers',
        'literature review'],
    'Finance and crypto': [ 'open interest', 'funding rates', 'hyperliquid', 'xrpl', 'crypto market', 'crypto news',
        'prediction markets', 'wallet balance', 'base tokens', 'fear and greed index', 'insider trades',
        'sec edgar filings', 'public company', 'company profile', 'exchange rates',
        'inflation data|inflation', 'gdp data|gdp', 'unemployment data|unemployment', 'interest rates', 'us treasury',
        'mortgage rates', 'income tax', 'sales tax', 'withholding tax', 'tax rates', 'minimum wage', 'payroll',
        'bookkeeping', 'accounting',
        'earnings calendar', 'order book', 'polymarket', 'kalshi'],
    'Commerce and marketing': [ 'email finder', 'product recalls',
        'property check', 'supply chain', 'job postings',
        'tariff codes|tariff'],
    'Health, science and education': [
        'nutrition', 'calorie counting|calories', 'fitness', 'mental health', 'icd 10 codes|icd 10', 'astrology',
        'recipes',
        'medicare data|medicare', 'bible verses|bible', 'tarot'],
    'Security and operations': [
        'ip reputation', 'identity verification', 'agent trust', 'agent reputation',
        'url safety check|url safety', 'phishing detection|phishing', 'epss scores|epss', 'pii redaction', 'prompt injection detection|prompt injection'],
    'Public data and legal': [ 'official legislation', 'court records', 'vat number validation', 'esg data|esg',
        'country data',
        'lei lookup'],
    'Agents and AI models': [
        'agent discovery', 'agent card', 'a2a agents', 'x402 payments',
        'erc 8004 agents|erc 8004', 'agent identity'],
}
CATALOG_MIN = 3
LEAD = 60
EXCLUDED_FALLBACK = {'log analysis'}  # catalog matches describe IP lookups, not log analysis
_PURPOSE_PREFIX = re.compile(r'^(?:use (?:this )?when|call this when|use for)\b[^:]{0,80}?\b(?:needs?|wants?) (?:to )?', re.I)


def lead(item):
    """Name plus the opening of the description, where a listing says what it is for."""
    description = _PURPOSE_PREFIX.sub('', str(item.get('description') or ''))
    return {'name': item.get('name'), 'description': description[:LEAD]}


def phrase_match(term, item):
    """The listing contains the term as a phrase (each word may take a plural ending)."""
    text = ' '+re.sub(r'[^a-z0-9]+', ' ', ' '.join(str(item.get(k) or '') for k in ('name', 'description')).lower())+' '
    words = re.findall(r'[a-z0-9]+', term.lower())
    return bool(words) and re.search(' '+' '.join(re.escape(w)+'(?:s|es)?' for w in words)+' ', text) is not None


def catalog_tasks(tasks, catalog, now=None):
    """Adds task pages from the evidence catalog: short search-based tasks, then CATALOG_TASKS.

    `tasks` is the list of finished task dicts, `catalog` the cleaned agents with evidence. Agents are
    ordered by the published ranking basis (growth_pages.rank_key)."""
    from .growth_pages import rank_key
    ranked = sorted(catalog, key=lambda a: rank_key(a, now), reverse=True)
    done = {t['slug'] for t in tasks}
    added = []

    def add(group, title, term, minimum, query):
        slug = slugify(title)
        if slug in done:
            return
        matches = [a for a in ranked if phrase_match(term, lead(a))]
        if not matches:
            return
        counts = {}
        for a in matches:
            counts[a.get('category')] = counts.get(a.get('category'), 0) + 1
        main = max(counts, key=lambda c: (counts[c], c is not None, str(c)))
        agents = [a for a in matches if a.get('category') == main][:MAX_AGENTS]
        if len(agents) >= minimum:
            done.add(slug)
            added.append({'slug': slug, 'title': title[:1].upper()+title[1:], 'query': query, 'group': group, 'agents': agents})

    for group, phrases in TASKS.items():
        for phrase in phrases:
            if phrase not in EXCLUDED_FALLBACK:
                add(group, phrase, phrase, MIN_AGENTS, phrase)
    for group, entries in CATALOG_TASKS.items():
        for entry in entries:
            title, _, term = entry.partition('|')
            add(group, title, term or title, CATALOG_MIN, term or title)
    return tasks + added


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
        tasks = catalog_tasks(tasks, self.catalog.values())
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
