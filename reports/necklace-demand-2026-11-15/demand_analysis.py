"""Demand table (PM 16:03 #1): topics of Chat/find_agents/A2A asks, 7 and 30 days, our traffic left out."""
import ast, collections, json, re, sys, time
from pathlib import Path
S = Path(sys.argv[1]); ROOT = Path('/Users/kingstonelee/workspace/A2A_Discovery')
NOW = time.time()
asks = {}
for l in open(S/'demand_asks.txt'):
    p = l.rstrip('\n').split('|', 4)
    if len(p) == 5 and p[0].isdigit(): asks[int(p[0])] = dict(id=int(p[0]), v=p[1], ch=p[2], at=float(p[3]), text=p[4])
reps = []
for l in open(S/'demand_rows.txt'):
    p = l.rstrip('\n').split('|')
    if len(p) >= 11 and p[0].isdigit():
        reps.append(dict(id=int(p[0]), v=p[1], ch=p[2], at=float(p[3]), mark=p[4], intent=p[5], status=p[6], task=p[7], cat=p[8], n=int(p[9] or 0), text='|'.join(p[10:])))
# pair each reply with its ask: same visitor, nearest earlier ask
byv = collections.defaultdict(list)
for a in asks.values(): byv[a['v']].append(a)
for r in reps:
    if not r['text']:
        prev = [a for a in byv[r['v']] if a['id'] < r['id']]
        r['text'] = max(prev, key=lambda a: a['id'])['text'] if prev else ''
# our literals: string constants in scripts/ and tests/
lits = set()
norm = lambda t: re.sub(r'\s+', ' ', re.sub(r'\{[^}]*\}|\d+', '#', t.lower())).strip(' #.?!')
for f in list((ROOT/'scripts').glob('*.py')) + list((ROOT/'tests').rglob('*.py')):
    try: tree = ast.parse(f.read_text(errors='ignore'))
    except Exception: continue
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and 6 <= len(n.value) <= 200: lits.add(norm(n.value))
        elif isinstance(n, ast.JoinedStr):
            s = ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in n.values)
            if 6 <= len(s) <= 200: lits.add(norm(s))
def walk(o):
    if isinstance(o, str):
        if 6 <= len(o) <= 200: lits.add(norm(o))
    elif isinstance(o, dict): [walk(v) for v in o.values()]
    elif isinstance(o, list): [walk(v) for v in o]
for f in (ROOT/'tests/data').rglob('*.json'):
    try: walk(json.loads(f.read_text(errors='ignore')))
    except Exception: pass
for f in (ROOT/'tests/data').rglob('*.jsonl'):
    for line in f.read_text(errors='ignore').splitlines():
        try: walk(json.loads(line))
        except Exception: pass
lits.discard('')
PROBE = re.compile(r'liveness check|reply with the single word ok|友好握手|协作实验席位|structured discovery request$|紫薇|red-team auditor|recontact-verify|task update destination request', re.I)
def why_out(r):
    if r['mark'] == 'internal' or r['ch'] == 'admin-test': return 'internal mark'
    t = r['text'].strip()
    if re.search(r'\s\d{2,4}$|\(\d{4}\)$', t): return 'measurement suffix'
    if norm(t) in lits: return 'our script text'
    if PROBE.search(t): return 'probe/handshake'
    return None
TOPICS = [  # (topic, role or None, pattern)
 ('weather', 'weather.forecast.v1', r'weather|wheather|forecast|rain|temperature'),
 ('currency / fx', 'fx.rates.v1', r'currenc|exchange rate|\busd\b|\beur\b|\bkrw\b|\bjpy\b|fx\b'),
 ('crypto price', 'crypto.price.v1', r'bitcoin|\bbtc\b|\beth\b|crypto|token price|solana'),
 ('stock / finance data', None, r'stock|ticker|nasdaq|earnings|market data|sec filing|10-k'),
 ('translation', None, r'translat|korean|japanese|spanish|french'),
 ('email send', None, r'e-?mail|smtp|newsletter|transactional'),
 ('website uptime / monitoring', None, r'website is up|uptime|monitor|status page|down\b|alert'),
 ('web page summarize / scrape', 'web.grounding.v1', r'summari[sz]e (a )?(web|page|url|article)|scrap|crawl|web page|extract .*url|read (a|this) (url|page)'),
 ('pdf / document', None, r'\bpdf\b|document|docx'),
 ('research papers', 'papers.search.v1', r'paper|arxiv|research|scholar|citation'),
 ('news', 'news.search.v1', r'\bnews\b|headline|latest .*(ai|tech)'),
 ('web search', 'web.grounding.v1', r'web search|search the web|google|search engine'),
 ('database / sql', None, r'postgres|sql|database|mysql|supabase|mongodb'),
 ('github / code', 'package.health.v1', r'github|repo|pull request|issue|code review|npm|pypi|package'),
 ('security / cve', 'cve.record.v1', r'\bcve\b|vulnerab|exploit|security scan|kev'),
 ('dns / domain / email auth', 'domain.lookup.v1', r'\bdns\b|domain|whois|\bspf\b|dkim|dmarc|ssl cert'),
 ('image generation', None, r'image|picture|photo|draw|logo'),
 ('calendar / scheduling', 'holiday.calendar.v1', r'calendar|schedul|meeting|holiday|event'),
 ('jobs', None, r'\bjobs?\b|hiring|career|resume'),
 ('travel / flights', 'airport.lookup.v1', r'flight|airport|hotel|travel|booking'),
 ('time / timezone', 'timezone.time.v1', r'time ?zone|current time|what time'),
 ('maps / places', None, r'\bmap|geocod|address|places?\b|restaurant'),
 ('ai readiness / llms.txt', 'website.ai_readiness.v1', r'llms\.txt|robots\.txt|ai readiness|ai-ready'),
 ('company lookup', 'company.registry.v1', r'company|business registry|corporat'),
 ('video / youtube', None, r'video|youtube|transcri'),
 ('social media', None, r'twitter|\bx\.com|tweet|reddit|linkedin|telegram|slack|discord'),
 ('payments', None, r'payment|stripe|invoice|x402|usdc'),
 ('agents / workflow / a2a', None, r'\bagents?\b|workflow|a2a|mcp server|orchestrat'),
]
OUTREACH = re.compile(r'hello from|handshake|introduction|introduce|seeking (paid|collab)|parley|bootstrap|public research only|connectivity check|capability intro|we provide|i am an? |^a2a$|red.team|alliance|联盟', re.I)
def topic(t):
    if OUTREACH.search(t.strip()): return '(agent outreach / handshake)'
    t = t.lower()
    for name, role, pat in TOPICS:
        if re.search(pat, t): return name
    if re.fullmatch(r'\W*(hi|hello|hey|help|what can you do\W*|thanks?.*|ok|test.*|ping)\W*', t) or len(t) < 3: return '(greeting / empty)'
    return '(other)'
kept, dropped = [], collections.Counter()
for r in reps:
    w = why_out(r)
    if w: dropped[w] += 1
    else: r['topic'] = topic(r['text']); kept.append(r)
def table(days):
    rs = [r for r in kept if r['at'] > NOW - days*86400]
    c = collections.defaultdict(lambda: dict(n=0, v=set(), ch=collections.Counter(), zero=0))
    for r in rs:
        d = c[r['topic']]; d['n'] += 1; d['v'].add(r['v']); d['ch'][r['ch']] += 1
        if r['status'] == 'no_match' or (r['intent'] == 'find' and r['n'] == 0 and r['status'] not in ('greet','help','stop')): d['zero'] += 1
    out = sorted(({'topic': k, 'asks': d['n'], 'clients': len(d['v']), 'chat_rest': d['ch']['rest'], 'a2a': d['ch']['a2a'],
                   'mcp': d['ch']['mcp'], 'no_match': d['zero']} for k, d in c.items()), key=lambda x: (-x['clients'], -x['asks']))
    return {'days': days, 'asks': len(rs), 'clients': len({r['v'] for r in rs}), 'topics': out}
# combos: same visitor, asks within 30 minutes, 2+ distinct real topics
combos = collections.Counter(); combo_clients = collections.defaultdict(set)
for v, rs in collections.groupby(sorted(kept, key=lambda r: (r['v'], r['at'])), key=lambda r: r['v']) if False else []: pass
seqs = collections.defaultdict(list)
for r in sorted(kept, key=lambda r: (r['v'], r['at'])): seqs[r['v']].append(r)
for v, rs in seqs.items():
    sess, last = [], None
    def close(sess):
        ts = []
        for r in sess:
            if not r['topic'].startswith('(') and r['topic'] not in ts: ts.append(r['topic'])
        if len(ts) >= 2:
            key = ' -> '.join(ts[:3]); combos[key] += 1; combo_clients[key].add(v)
    for r in rs:
        if last is not None and r['at'] - last > 1800: close(sess); sess = []
        sess.append(r); last = r['at']
    close(sess)
outcome_fail = None
res = {'generated': time.strftime('%Y-%m-%d %H:%M KST'), 'source': 'agent_messages (concierge replies paired with asks), read-only',
       'dropped': dict(dropped), 'kept': len(kept), 'd7': table(7), 'd30': table(30),
       'combos': [{'combo': k, 'sessions': n, 'clients': len(combo_clients[k])} for k, n in combos.most_common(25)]}
(S/'demand_table.json').write_text(json.dumps(res, indent=1, ensure_ascii=False))
for d in ('d7', 'd30'):
    t = res[d]; print(f"== {t['days']}d asks {t['asks']} clients {t['clients']}")
    for x in t['topics'][:22]: print(f"{x['topic']:30} {x['asks']:4} {x['clients']:4}  rest {x['chat_rest']:3} a2a {x['a2a']:3} mcp {x['mcp']:3}  no_match {x['no_match']}")
print('dropped', dict(dropped), 'kept', len(kept))
for x in res['combos'][:15]: print(x)
