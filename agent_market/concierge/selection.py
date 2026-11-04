"""Single-agent selection from indexed, local verification evidence; no model or network calls."""
import itertools
from collections import Counter
from functools import lru_cache
import json
import math
import re
import time

from ..gateway.classify import query_terms
from ..gateway.ranking import Scored, _relevance
from .engine import Recommender, clean_external
from .recommendation_security import usable_endpoint, endpoint_origin, public_recommendation
from .connections import public_agent
from .discovery_contracts import contract_reads
from .retrieval_metrics import timed
from .execution_policy import supported_schema, ExecutionDenied
from .report_evidence import measured_report
from ..search_quality import observed

MAX_HEALTH_AGE = 24 * 3600
INCIDENTAL_LOOKAHEAD = 40  # further candidates examined for a focused listing once bundles fill the places
RESOURCE_BATCH = 500  # listing contracts read per lookup batch
# Common capability phrases are translated locally; protocol filters do not change quality ranking.
ALIASES = {
    '\uc6f9 \uac80\uc0c9': 'web search', '\uc6f9\uac80\uc0c9': 'web search', '\uc778\ud130\ub137 \uac80\uc0c9': 'web search', '\uac80\uc0c9 \uacb0\uacfc': 'search results',
    '\ub0a0\uc528': 'weather', '\uc77c\uae30\uc608\ubcf4': 'forecast', '\uc608\ubcf4': 'forecast', '\uae30\uc628': 'temperature', '\uac15\uc218': 'rainfall',
    '\ubbf8\uc138\uba3c\uc9c0': 'air quality', '\ucd08\ubbf8\uc138\uba3c\uc9c0': 'air quality', '\uacf5\uae30\uc9c8': 'air quality', '\ub300\uae30\uc9c8': 'air quality',
    '\uc8fc\uc2dd': 'stock', '\uc8fc\uac00': 'stock', '\uc2dc\uc138': 'price quote', '\ud658\uc728': 'exchange rate', '\uc554\ud638\ud654\ud3d0': 'crypto', '\ube44\ud2b8\ucf54\uc778': 'bitcoin',
    '\uc774\ub354\ub9ac\uc6c0': 'ethereum', '\uae08\uc735': 'finance', '\uc120\ubb3c': 'perpetual', '\ud380\ub529\ube44': 'funding rate',
    '\ud56d\uacf5': 'flight', '\ud56d\uacf5\uad8c': 'flight', '\ud638\ud154': 'hotel', '\uc9c0\ub3c4': 'maps', '\uc9c0\uc624\ucf54\ub529': 'geocoding',
    '\ub370\uc774\ud130\ubca0\uc774\uc2a4': 'database', '\ubd84\uc11d': 'analytics', '\ucc28\ud2b8': 'chart', '\ud1b5\uacc4': 'statistics',
    '\ubb38\uc11c': 'document', '\uc9c0\uc2dd': 'knowledge', '\ud30c\uc77c': 'file', '\ubcc0\ud658': 'convert', '\ubc88\uc5ed': 'translation',
    '\uc774\uba54\uc77c': 'email', '\uba54\uc77c': 'email', '\ub2ec\ub825': 'calendar', '\uc77c\uc815': 'calendar', '\uba54\uc2dc\uc9c0': 'messaging',
    '\uc774\ubbf8\uc9c0': 'image', '\uadf8\ub9bc': 'image', '\uc601\uc0c1': 'video', '\uc74c\uc131': 'audio', '\uc74c\uc545': 'music',
    '\ubcf4\uc548': 'security', '\ucde8\uc57d\uc810': 'vulnerability', '\ub3c4\uba54\uc778': 'domain', '\uc778\uc99d\uc11c': 'certificate',
    '\uc758\ub8cc': 'medical', '\ub17c\ubb38': 'research paper', '\uc5f0\uad6c': 'research', '\ub274\uc2a4': 'news', '\uae30\uc220': 'technology',
    '\ucf54\ub4dc': 'code', '\uac1c\ubc1c': 'development', '\ubc30\ud3ec': 'deployment', '\uae43\ud5c8\ube0c': 'github',
    '\uc774\uc288': 'issues', '\uae43\ud5c8\ube0c \uc774\uc288': 'github issues', '\uae43\ud5c8\ube0c\uc774\uc288': 'github issues',
    '\uc2a4\ud06c\ub798\ud551': 'scraping', '\ud06c\ub864\ub9c1': 'crawling', '\ucd94\ucd9c': 'extract', '\uac80\uc0c9': 'search',
    '\uacb0\uc81c': 'payment', '\uc9c0\uac11': 'wallet', '\uc1fc\ud551': 'shopping', '\uac00\uaca9\ube44\uad50': 'price comparison',
    '\uad50\uc721': 'education', '\ud559\uc2b5': 'learning', '\ubc95\ub960': 'legal', '\ud2b9\ud5c8': 'patent',
    # Spanish capability aliases
    'traducir': 'translation', 'traduccion': 'translation', 'traducci\u00f3n': 'translation',
    'clima': 'weather', 'tiempo': 'weather', 'meteo': 'weather', 'pronostico': 'forecast', 'pron\u00f3stico': 'forecast',
    'noticias': 'news', 'acciones': 'stock', 'bolsa': 'stock', 'precio': 'price', 'cotizacion': 'price quote', 'cotizaci\u00f3n': 'price quote',
    'documento': 'document', 'documentos': 'document', 'resumir': 'summarize', 'resumen': 'summary', 'moneda': 'currency', 'divisas': 'currency',
    'vuelo': 'flight', 'vuelos': 'flight', 'hotel': 'hotel', 'hoteles': 'hotel', 'mapa': 'maps', 'mapas': 'maps',
    'buscar': 'search', 'busqueda': 'search', 'b\u00fasqueda': 'search', 'correo': 'email', 'correos': 'email',
    'texto':'text', 'textos':'text', 'tecnolog\u00eda':'technology', 'tecnologia':'technology',
    # Japanese capability aliases (escaped Unicode)
    '\u8ad6\u6587':'research papers', '\u5b66\u8853':'academic',
    '\u5929\u6c17': 'weather', '\u4e88\u5831': 'forecast', '\u6c17\u6e29': 'temperature',
    '\u7ffb\u8a33': 'translation', '\u682a\u4fa1': 'stock price', '\u682a\u5f0f': 'stock',
    '\u30cb\u30e5\u30fc\u30b9': 'news', '\u691c\u7d22': 'search', '\u6771\u4eac': 'tokyo',
    '\u660e\u65e5': 'tomorrow', '\u4eca\u65e5': 'today', '\u70ba\u66ff': 'exchange rate',
    '\u6587\u66f8': 'document', '\u753b\u50cf': 'image', '\u52d5\u753b': 'video',
    '\u97f3\u58f0': 'audio', '\u5730\u56f3': 'maps', '\u8981\u7d04': 'summarize',
    '\u30e1\u30fc\u30eb': 'email', '\u30d5\u30a1\u30a4\u30eb': 'file', '\u30b3\u30fc\u30c9': 'code',
    '\u958b\u767a': 'development', '\u6599\u91d1': 'pricing', '\u6599\u7406': 'cooking',
    # Korean grammatical aliases (escaped Unicode)
    '\uc870\ud68c': 'lookup', '\uc870\ud68c\ud574': 'lookup', '\uc870\ud68c\ud560': 'lookup',
    '\ubb34\ub8cc': 'free', '\uc720\ub8cc': 'paid',
}
FILLER = set('find recommend recommendation recommendations best highest high quality reliable verified recent latest please need want looking look help show only ones one another alternative options option use using get give tell done accomplish trying without free paid cheap price pricing prices cost costs budget money key keys account accounts auth authentication no required any capable capability capabilities api apis agent agents tool tools server servers mcp a2a x402 for an to me can you i am is the my it its this that and or of in on a with do does which what how'.split())
FILLER.update('fast faster fastest quick quickly low lower lowest latency accurate accuracy highly top rated ratings grade grades report reports tested evaluation regular returning tier tiers subscription basic premium plan plans very really would could should will provide provides providing supports support current today tomorrow week days easy simple'.split())
# Prepositions and connectives carry no capability; they only dilute relevance.
FILLER.update('about into from by at as via per like than then also some other more most such into onto upon up'.split())
FILLER.update(('\ucd94\ucc9c','\ucd94\ucc9c\ud574\uc918','\ucc3e\uc544\uc918','\uc54c\ub824\uc918','\uc5d0\uc774\uc804\ud2b8','\uc11c\ubc84','\ub3c4\uad6c','\ubb34\ub8cc','\uc720\ub8cc','\uac00\uaca9','\uac00\uc7a5','\uc88b\uc740','\ud488\uc9c8','\ub192\uc740','\ud558\ub098','\uac1c','\ud544\uc694\ud574','\ubd80\ud0c1\ud574','\uc870\ud68c','\uc870\ud68c\ud574','\uc870\ud68c\ud560','\uc788\uc5b4','\uc218','\ud560','\ub18d\ub3c4'))
FILLER.update('quiero necesito busca encuentra recomienda agente que un una unos unas al el la los las de del para por en con sin gratis como es son ingles inglés'.split())
FILLER.update(('\u306e', '\u3092', '\u306f', '\u304c', '\u306b', '\u3067', '\u3068', '\u3057\u305f\u3044', '\u77e5\u308a\u305f\u3044', '\u6559\u3048\u3066', '\u304f\u3060\u3055\u3044', '\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8', '\u30c4\u30fc\u30eb', '\u7121\u6599', '\u6709\u6599', '\u3042\u308b', '\u3044\u3044', '\u304a\u3059\u3059\u3081'))
UNIT_NAMES = frozenset('miles mile kilometers kilometer km meters meter feet foot inches inch yards yard pounds pound lbs kilograms kilogram kg grams gram ounces ounce celsius fahrenheit kelvin gallons gallon liters liter'.split())


def search_terms(task):
    from .query_intent import interpret
    from .chat_task_spec import canonical_text
    text = interpret(canonical_text(task)).positive.lower()
    for source, target in sorted(ALIASES.items(), key=lambda pair: -len(pair[0])):
        if source[0].isascii():
            text = re.sub(r'\b' + re.escape(source) + r'\b', ' ' + target + ' ', text)
        else:
            text = text.replace(source, ' ' + target + ' ')
    # Korean grammatical particles and unmapped prose do not pollute the English catalog query.
    text = re.sub(r'\bai\b', 'artificial intelligence', text)
    words = re.findall(r'[a-z][a-z0-9_-]*', text.lower())
    if 'equity' in words or 'equities' in words:
        words.append('stock')
    filtered = [word for word in query_terms(' '.join(words), limit=1024) if word not in FILLER]
    if set(filtered).intersection({'convert', 'conversion'}) and set(filtered).intersection(UNIT_NAMES) and 'unit' not in filtered:
        filtered.append('unit')
    if re.search(r'\b(?:bitcoin|btc|ethereum|eth|stocks?|shares|equit(?:y|ies))\b',text)and re.search(r'\b(?:price|quote)s?\b',text):
        filtered.append('price')
    return filtered if len(filtered) <= 12 else filtered[:8] + filtered[-4:]



def _json(value, default):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, type(default)) else default
    except (ValueError, TypeError):
        return default


def _number(value, default=0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, OverflowError):
        return default


def _candidate_sql():
    return """
            SELECT r.id,r.category,r.kind,r.url,r.eval_grade,r.eval_score,r.eval_at,
                   r.last_ok_at,r.last_check_at,r.last_status_code,r.health_ok_24h,r.health_n_24h,
                   r.probe_latency_ms,r.trial_ok,r.trial_info,
                   t.id AS report_id,t.executed_at AS report_at,t.eval_grade AS report_grade,
                   t.eval_score AS report_score,t.is_success AS report_success,t.status_code AS report_status,
                   t.latency_ms AS report_latency,t.tool_name AS report_tool,t.connection_version_id AS report_version,
                   CAST(COALESCE(strftime('%s',t.created_at),t.created_at) AS REAL) AS report_created_at,t.executed_at AS report_executed_at,
                   ce.executed_at AS execution_at,ce.outcome AS execution_outcome,ce.expires AS execution_expires
              FROM resources_fts CROSS JOIN resources r ON r.id=resources_fts.rowid
              LEFT JOIN agent_test_reports t ON t.id=(
                SELECT id FROM (
                    SELECT id,executed_at AS at FROM agent_test_reports WHERE resource_id=r.id AND kind=r.kind AND executed_at IS NOT NULL AND connection_version_id IS NOT NULL
                    UNION
                    SELECT id,executed_at AS at FROM agent_test_reports WHERE agent_url=r.url AND kind=r.kind AND executed_at IS NOT NULL AND connection_version_id IS NOT NULL
                ) ORDER BY at DESC,id DESC LIMIT 1
              )
              LEFT JOIN capability_eligibility ce ON ce.resource_id=r.id
             WHERE resources_fts MATCH ? AND r.active=1 AND r.kind IN ('a2a','mcp','x402')
               AND (? IS NULL OR r.kind=?)
               AND r.health_status IN ('healthy','reachable')
               AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
               AND (r.last_ok_at >= ? OR (t.is_success=1 AND t.executed_at>=?)
                    OR (r.trial_ok=1 AND CASE WHEN json_valid(r.trial_info) THEN json_extract(r.trial_info,'$.at') ELSE 0 END >= ?))

        """


@timed('contracts')
def _advertised_tools(resource):
    """Use the same advertised capability set for admission and the reply."""
    from ..explore_documents import tools_for_search
    prepared = tools_for_search(resource)
    if prepared is not None:
        return prepared
    if resource.get('kind') == 'mcp' and resource.get('usage_full_tools') is not None:
        from .execution_policy import tools_for
        return tools_for(resource)[:100]
    guide = _json(resource.get('usage_guide'), {})
    tools = guide.get('tools') or guide.get('skills') or _json(resource.get('usage_tools'), [])
    return [tool for tool in tools[:100] if isinstance(tool, dict)] if isinstance(tools, list) else []


def _document_capability_matches(requested, text):
    text = text.lower().replace('_', ' ')
    if requested.intersection({'invoice', 'invoices'}) and not re.search(r'\binvoices?\b|\bbilling documents?\b', text):return False
    if requested.intersection({'receipt', 'receipts'}) and not re.search(r'\breceipts?\b', text):return False
    # A limitation such as "no OCR" is not evidence of OCR capability.
    positive = re.sub(r'\b(?:no|without|not|does not support|cannot perform)\s+(?:pdf|ocr)\b', '', text)
    if 'pdf' in requested and not re.search(r'\bpdf\b|\bocr\b|document (?:parsing|extraction|processing)', positive):return False
    if requested.intersection({'json', 'extract', 'convert', 'parse'}) and not re.search(r'\b(?:extract\w*|convert\w*|pars\w*|ocr|structured)\b', positive):return False
    return True


def _task_tool_matches(terms, tool):
    requested = set(terms)
    if not requested.intersection({'pdf', 'invoice', 'invoices', 'receipt', 'receipts'}):return True
    text = str(tool.get('name', '')) + ' ' + str(tool.get('description', ''))
    units = re.split(r'\b(?:get|post|put|patch|delete)\s+/', text.lower())
    return any(_document_capability_matches(requested, unit) for unit in units)


WORD_ENDINGS = ('ations', 'ation', 'ions', 'ion', 'izes', 'ize', 'ings', 'ing', 'ibe', 'ate', 'es', 'ed', 'e', 's')
_EQUIVALENT_PATTERNS = {
    'postgres': re.compile(r'\bpostgres(?:ql)?\b'),
    'postgresql': re.compile(r'\bpostgres(?:ql)?\b'),
    'bitcoin': re.compile(r'\b(?:bitcoin|btc)\b'),
    'weather': re.compile(r'\b(?:weather|forecast\w*|meteorolog\w*)\b'),
    'transcription': re.compile(r'\b(?:transcrib\w*|transcript\w*|speech[- ]to[- ]text)\b'),
    'audio': re.compile(r'\b(?:audio|speech|spoken|recording|podcast)\b'),
    'translation': re.compile(r'\btranslat\w*\b'),
    'convert': re.compile(r'\b(?:convert\w*|conversion\w*)\b'),
    'conversion': re.compile(r'\b(?:convert\w*|conversion\w*)\b'),
    'direction': re.compile(r'\bdirections?\b'),
    'directions': re.compile(r'\bdirections?\b'),
    'documentation': re.compile(r'\b(?:documentation|docs|API reference)\b'),
    'academic': re.compile(r'\b(?:academic|scholarly|research)\b'),
    'scholarly': re.compile(r'\b(?:academic|scholarly|research)\b'),
    'paper': re.compile(r'\b(?:papers?|scholarly (?:articles?|literature)|literature)\b'),
    'literature': re.compile(r'\b(?:literature|papers?|scholarly articles?|bibliographic)\b'),
    'code': re.compile(r'\b(?:code|pull requests?|github pr|pr reviews?)\b'),
    'equity': re.compile(r'\b(?:equity|equities|stocks?|shares)\b'),
    'currency': re.compile(r'\b(?:currenc(?:y|ies)|forex|fx|exchange[- ]rates?)\b'),
    'resume': re.compile(r'\b(?:resumes?|curriculum[- ]vitae|cv)\b'),
    'cv': re.compile(r'\b(?:resumes?|curriculum[- ]vitae|cv)\b'),
    'invoice': re.compile(r'\b(?:invoices?|billing[- ]documents?)\b'),
    'hotel': re.compile(r'\b(?:hotels?|lodgings?|accommodations?)\b'),
    'flight': re.compile(r'\b(?:flights?|airfares?|airlines?)\b'),
}


@lru_cache(maxsize=4096)
def _term_pattern(term):
    if term in ('direction', 'directions'):
        return _EQUIVALENT_PATTERNS[term]
    for ending in WORD_ENDINGS:
        if term.endswith(ending) and len(term) - len(ending) >= 5:
            return re.compile(r'\b' + re.escape(term[:-len(ending)]) + r'\w*')
    stem = term[:-1] if len(term) > 4 and term.endswith('s') else term
    endings = r'(?:s|es|ed|ers?|ors?|ing|ions?|ations?)?' if len(stem) >= 5 else r's?'
    return re.compile(r'\b' + re.escape(stem) + endings + r'\b')


def _term_in(term, text):
    """Match a task word and its inflections (translate, translation, translator)."""
    eq = _EQUIVALENT_PATTERNS.get(term)
    if eq is not None and eq.search(text):
        return True
    if term in ('direction', 'directions'):
        return False
    return _term_pattern(term).search(text) is not None


# A tool that finds other APIs or agents ("find a paid API for anything") is a
# catalog, and account tools ("Get an API key", "identify", quotes) perform no
# task. Neither is evidence that the listing performs the requested work.
CATALOG_TOOL = re.compile(
    r'\b(?:find|search|discover|browse|list|recommend|route)\w*\s+(?:(?:for|over|across|through|among)\s+)?'
    r'(?:a|an|any|every|all|other|available|matching|the best|best)\s+(?:[\w-]+\s+){0,2}'
    r'(?:apis?|agents?|tools?|services?|sellers?|listings?|providers?|endpoints?|servers?|skills?)\b(?!\s+keys?)')
ACCOUNT_TOOL = re.compile(
    r'\b(?:api[- ]?keys?|invocation details|identify|whoami|health[- ]?checks?|ping|sign[- ]?ups?)\b')


def _task_tools(tools, terms=()):
    """Advertised tools that perform work, excluding catalog and account tools.

    A tool whose own name states a requested word ("Identify a plant") is kept."""
    kept = []
    for tool in tools:
        name = ' '.join(str(tool.get('name') or tool.get('id') or '').lower().replace('_', ' ').split())
        text = name + ' ' + ' '.join(str(tool.get('description') or '').lower().split())
        if re.search(r'\b(?:invocation details|payment info|payment details|billing info|pricing|api[- ]?keys?|sign[- ]?ups?)\b',name):continue
        if any(_term_in(term, name) for term in terms if term not in ('api', 'apis', 'agent', 'agents')):
            kept.append(tool)
            continue
        if ACCOUNT_TOOL.search(name) or CATALOG_TOOL.search(text):
            continue
        kept.append(tool)
    return kept


def _described_tools(resource, tools):
    """Tool descriptions that actually describe the tool.

    Many listings copy one marketing sentence into every skill. Such text, or
    the agent's own description repeated on a tool, is not evidence that a
    tool named like the task performs it."""
    if len(tools) <= 1:
        return [t for t in tools if str(t.get('description') or '').strip()]
    agent_text = ' '.join(str(resource.get('description') or '').lower().split())
    texts = [' '.join(str(t.get('description') or '').lower().split()) for t in tools]
    shared = {text for text, count in Counter(texts).items() if text and count >= 3}
    # A single-tool listing legitimately reuses its own description.
    copied = agent_text if len(tools) >= 2 else None
    return [t for t, text in zip(tools, texts) if text and text != copied and text not in shared]


def _evidence_matches(terms, resource, tools):
    """At least one task term must appear in a real description, not only in a tool name."""
    primary = str(resource.get('description') or '').lower()
    described = ' '.join(str(t.get('description') or '') for t in _described_tools(resource, tools)).lower()
    return any(_term_in(term, primary) or _term_in(term, described) for term in terms)


EQUITY_TERMS = {'stock', 'stocks', 'equity', 'equities', 'shares', 'nasdaq', 'nyse', 'sp500', 'earnings'}
EQUITY_EVIDENCE = re.compile(r'\b(?:stocks?|equit(?:y|ies)|nasdaq|nyse|s&p 500|stock tickers?|listed companies|securities filings?)\b')
CRYPTO_EVIDENCE = re.compile(r'\b(?:crypto\w*|perpetuals?|perps?|tokens?|defi|bitcoin|ethereum|onchain|on-chain|prediction[- ]markets?)\b')


def _asset_class_matches(requested, resource, tools):
    """A stock-market request is not served by a crypto-only market tool."""
    if not requested.intersection(EQUITY_TERMS):
        return True
    texts = [' '.join(str(resource.get(k) or '') for k in ('name', 'description')).lower()]
    texts += [(str(t.get('name') or '') + ' ' + str(t.get('description') or '')).lower() for t in tools]
    return any(EQUITY_EVIDENCE.search(text) and not (CRYPTO_EVIDENCE.search(text) and not EQUITY_EVIDENCE.search(text))
               for text in texts)


def _tool_purpose(description):
    """The first sentence states what a tool does; later text covers delivery, limits and contact."""
    # Parenthetical asides ("only with the user's ok to share their email") are conditions, not the task.
    text = ' '.join(re.sub(r'\([^)]*\)', ' ', str(description or '')).split())
    return re.split(r'(?<=[.!?])\s|\s[\u2014\u2013-]\s|;\s', text, maxsplit=1)[0][:240]


def _tool_text(tool, described):
    text = str(tool.get('name') or tool.get('id') or '')
    if id(tool) in described:
        text += ' ' + _tool_purpose(tool.get('description'))
    return text.lower().replace('_', ' ')


TOPIC_BOUNDARY = re.compile(r'\b(?:(?:and\s+)?(?:return|include|provide|output)|about|regarding|concerning|related to|with|for|on|from|to|into|in|across|throughout|that|which)\b', re.I)
# A leading "Search for papers" names the papers search itself, so its "for" is no topic
# boundary. "web search for AI news" (a search with its own object) and normalize_task's
# "academic paper search for <task>" keep the boundary.
# Sentence starts count too: normalized English is appended as ". Search for papers".
SEEK_PHRASE = re.compile(r'((?:^|[.!?]\s+)\s*(?:please\s+|(?:can|could|would) you\s+|i (?:want|need) to\s+)?'
                         r'(?:search(?:es|ing)?|look(?:s|ing)?|hunt(?:s|ing)?))\s+for\b', re.I)


HANGUL_WORD = re.compile(r'[\uac00-\ud7a3]{2,}')
# Particles and request endings carry no task content ("\ubc30\ud130\ub9ac\ub97c" -> "\ubc30\ud130\ub9ac").
KO_SUFFIXES = tuple(sorted(('\uc5d0\uc11c\ub294', '\uc5d0\uc11c', '\uc5d0\uac8c', '\uc73c\ub85c', '\uc5d0\ub294', '\uc5d0\ub3c4',
    '\uc5d0', '\uc744', '\ub97c', '\uc774', '\uac00', '\uc740', '\ub294', '\uc640', '\uacfc', '\uc758', '\ub85c', '\ub3c4', '\ub9cc',
    '\ud574\uc8fc\ub294', '\ud574\uc918', '\uc8fc\ub294', '\ud558\ub294', '\ud574'), key=len, reverse=True))
KO_FUNCTION_WORDS = set('''\ucc3e\uc544\uc918 \uc54c\ub824\uc918 \ud574\uc918 \ucd94\ucc9c\ud574\uc918 \ubcf4\uc5ec\uc918 \uac80\uc0c9\ud574\uc918
    \uc5d0\uc774\uc804\ud2b8 \ub3c4\uad6c \uc11c\ube44\uc2a4 \uad00\ud55c \ub300\ud55c \uad00\ub828 \uc704\ud55c \uc788\ub294 \ucd5c\uc2e0
    \uc624\ub298 \ub0b4\uc77c \uc9c0\uae08 \uadf8\ub9ac\uace0 \uc880 \ucc3e\uc544 \uc54c\ub824 \ucd94\ucc9c
    \uc870\ud68c \uc870\ud68c\ud574 \uc870\ud68c\ud560 \uc788\uc5b4 \uc218 \ud560 \ubb34\ub8cc \uc720\ub8cc \ub18d\ub3c4'''.split())


ALIAS_WORDS = frozenset(word for value in ALIASES.values() for word in value.split())


def untranslated_words(task):
    """Content words that no alias table covers; their meaning would otherwise be dropped.

    Korean words the aliases miss are always returned, even beside covered words, so a
    subject such as a product name is normalized rather than lost. Uncovered CJK
    subject words also need normalization even beside a recognized capability."""
    from .chat_task_spec import canonical_text
    found = []
    for word in HANGUL_WORD.findall(canonical_text(task)):
        stem = word
        for suffix in KO_SUFFIXES:
            if stem.endswith(suffix) and len(stem) - len(suffix) >= 2:
                stem = stem[:-len(suffix)]
                break
        if word in KO_SUFFIXES or word in KO_FUNCTION_WORDS or stem in KO_FUNCTION_WORDS or word in FILLER or stem in FILLER or len(stem) < 2 or search_terms(stem):
            continue
        found.append(stem)
    if found:
        return found
    uncovered = canonical_text(task)
    for alias in sorted(ALIASES, key=len, reverse=True):
        if re.search(r'[\u3040-\u30ff\u3400-\u9fff]', alias):
            uncovered = uncovered.replace(alias, ' ')
    subjects = [word for word in re.findall(r'[\u30a0-\u30ff\u3400-\u9fff]{2,}', uncovered)
                if word not in {'\u9053\u5177', '\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8', '\u30c4\u30fc\u30eb', '\u30b5\u30fc\u30d3\u30b9'}]
    if subjects:
        return subjects
    terms = search_terms(task)
    foreign = (re.search(r'[\u3040-\u30ff\u3400-\u9fff]', task)
               or re.search(r'\b(?:quiero|necesito|busca|buscar|traducir|resumir|encuentra|recomienda|agente\s+que)\b', task, re.I))
    if foreign:
        # Foreign words become literal terms; only a matched capability alias makes them searchable.
        return [] if set(terms) & ALIAS_WORDS else ['untranslated-language']
    return []


# "Is there an agent or API that can track a flight?" and "..., so we need a tool that can ..." (11-04):
# the lead may open the request, and may name two kinds of listing.
_LEAD_NOUN = r'(?:tool|agent|service|api|server|app)s?'
NARRATIVE_LEAD = re.compile(
    r'^(?:.*?(?:[;:.!?,]\s+|\b(?:and|so)\s+))?'
    r'(?:(?:we|i)\s+(?:need|want|am looking for|are looking for|would like)\s+|(?:is there|are there|do you have|do you know(?:\s+of)?)\s+)'
    r'(?:(?:a|an|any|some)\s+' + _LEAD_NOUN + r'(?:\s+or\s+(?:(?:a|an)\s+)?' + _LEAD_NOUN + r')?|something)'
    r'\s+(?:that|which)\s+(?:(?:can|could|will|gives?|provides?)\s+)?',
    re.I)
# After the lead, the capability ends with its sentence ("..., ideally without setup. It should be cheap.").
LEAD_CLAUSE_END = re.compile(r'[.!?;](?:\s|$)|,\s+(?:ideally|preferably)\b', re.I)


def capability_terms(task):
    """Terms naming the capability, not the subject it is applied to.

    In "research papers about battery recycling" a paper-search tool will not
    mention batteries; the subject after the boundary is a query, not a skill."""
    task = PRICE_CONDITION.sub(' ', str(task or ''))  # "costs under 1 cent" limits a listing; it names no capability
    focused_task = NARRATIVE_LEAD.sub('', task)
    if focused_task != task:
        focused_task = LEAD_CLAUSE_END.split(focused_task, maxsplit=1)[0]
    head = TOPIC_BOUNDARY.split(SEEK_PHRASE.sub(r'\1', focused_task), maxsplit=1)[0]
    terms = search_terms(head) or search_terms(focused_task) or search_terms(task)
    # Generic verbs match almost any tool ("Get an API key"), and modifiers such
    # as "research" in "research papers" do not name the capability; keep the nouns.
    # Negations ("A2A weather, not MCP") qualify the request; they are never a capability.
    terms = [term for term in terms if term not in NEGATIONS] or terms
    specific = [term for term in terms if term not in GENERIC_ACTIONS]
    specific = [term for term in specific if term not in CAPABILITY_MODIFIERS] or specific
    specific = [term for term in specific if term not in LANGUAGE_NAMES] or specific
    # The place, company or document is what the capability is applied to, not the capability.
    if set(specific).intersection({'weather','forecast','temperature','tide','tides','surf','surfing','swell','air','aqi'}):
        specific = [term for term in specific if term in WEATHER_TERMS] or specific
    if set(specific).intersection({'stock','stocks','equity','equities','shares'}):
        specific = [term for term in specific if term in STOCK_TERMS] or specific
    if specific and set(specific) <= CURRENCY_CODES:
        # "EUR to USD exchange rate": the boundary split at "to" left only the codes.
        specific = [term for term in search_terms(task) if term in CURRENCY_TERMS] or specific
    if {'exchange', 'rate'}.issubset(specific) or set(specific).intersection({'currency', 'currencies', 'forex'}):
        specific = [term for term in specific if term in CURRENCY_TERMS] or specific
    if set(specific).intersection({'convert', 'conversion'}) and set(search_terms(task)).intersection(UNIT_NAMES):
        specific = ['convert', 'unit']
    if specific and set(specific) <= {'extract', 'parse'} and 'pdf' in search_terms(task):
        specific = specific + ['pdf']
    if set(specific).intersection({'scrape', 'scraping', 'scraper', 'crawl', 'crawling', 'crawler'}):
        specific = [term for term in specific if term in SCRAPE_TERMS] or specific
    if set(specific).intersection({'translation','translate','translates','translator'}):
        specific = [term for term in specific if term not in DOCUMENT_SUBJECTS] or specific
    if 'news' in specific:
        from .task_requirements import NEWS_TOPICS
        specific=[term for term in specific if term not in NEWS_TOPICS]
    # "open source repositories": "source" qualifies the repositories; it is no capability.
    if 'repositories' in specific or 'repository' in specific:
        specific = [term for term in specific if term != 'source' or not OPEN_SOURCE.search(task)] or specific
    # "an illustration of a mountain landscape": what is drawn is the subject, not the capability.
    made = [term for term in specific if term in IMAGE_KINDS]
    if made:
        specific = made
    # "convert text to speech": the boundary split at "to" dropped the capability itself.
    if SPEECH_PHRASE.search(task):
        return ['speech']
    # "look up a topic on Wikipedia": a named reference source is the capability wherever it appears.
    sources = [term for term in search_terms(task) if term in REFERENCE_SOURCES]
    if sources:
        return sources
    return specific or terms


OPEN_SOURCE = re.compile(r'\bopen[\s-]+source\b', re.I)
IMAGE_KINDS = {'illustration', 'illustrations', 'drawing', 'drawings', 'painting', 'paintings', 'artwork', 'logo', 'logos'}
SPEECH_PHRASE = re.compile(r'\b(?:text[\s-]+to[\s-]+(?:speech|voice)|speech[\s-]+to[\s-]+text)\b', re.I)
REFERENCE_SOURCES = {'wikipedia', 'wikidata', 'wiktionary'}
PRICE_CONDITION = re.compile(r'\b(?:that\s+|which\s+)?(?:costs?|priced?(?:\s+at)?|for|at)?\s*(?:under|below|less than|cheaper than|at most|no more than|max(?:imum)?(?: of)?)\s*'
                             r'(?:\$|usd\s*|us\$)?\d[\d.,]*\s*(?:cents?|usd[c]?|dollars?|\$)?(?:\s+(?:per|a|each)\s+(?:call|request|query))?', re.I)
CURRENCY_TOOL = re.compile(r'\b(?:fx|forex|currenc\w*|exchange[- ]rates?|foreign exchange|[a-z]{3}[/-][a-z]{3})\b')
CURRENCY_CODES = set('usd eur jpy gbp krw cny chf cad aud inr hkd sgd'.split())
CURRENCY_TERMS = set('exchange rate rates currency currencies forex fx conversion convert'.split())
SCRAPE_TERMS = set('scrape scraping scraper crawl crawling crawler website websites web page pages html'.split())
WEATHER_TERMS = set('weather forecast forecasts temperature rainfall rain precipitation humidity wind snow storm alerts hourly daily tide tides surf surfing swell air aqi pollution pollutant index'.split())
STOCK_TERMS = set('stock stocks equity equities shares quote quotes price prices ticker tickers market'.split())
DOCUMENT_SUBJECTS = set('contract contracts paragraph paragraphs document documents sentence sentences letter letters article '
                        'articles page pages file files manual manuals text texts message messages'.split())
LANGUAGE_NAMES = set('english korean japanese chinese mandarin spanish french german italian portuguese russian arabic hindi vietnamese thai indonesian dutch turkish polish ingles ingl espanol'.split())
# Listings that serve one language family, and the languages that family covers (English pairs with every family).
REGIONAL_LANGUAGES = [
    (re.compile(r'\b(?:indic|indian languages|languages of india)\b'),
     set('hindi bengali tamil telugu marathi gujarati kannada malayalam punjabi odia urdu assamese sanskrit nepali indic'.split())),
]


def _regional_languages_cover(requested, text):
    """A listing limited to one language family serves only requests within that family."""
    wanted = set(requested).intersection(LANGUAGE_NAMES) - {'english', 'ingles', 'ingl'}
    if not wanted or re.search(r'\b(?:\d{3}\+? languages|any language|all major languages)\b', text):
        return True
    # "Arabic-first OCR and translation" is built around another language (rv3, 11-04).
    if any(lang in LANGUAGE_NAMES and lang not in requested for lang in LANGUAGE_FIRST.findall(text.lower())):
        return False
    return all(wanted <= family for scope, family in REGIONAL_LANGUAGES if scope.search(text))
LANGUAGE_FIRST = re.compile(r'\b([a-z]+)[- ](?:first|centric|focused|only)\b')
NEGATIONS = {'not', 'no', 'nor', 'without', 'except', 'excluding'}
CAPABILITY_MODIFIERS = set('research recent latest online live real realtime time free public simple quick best good new current '
                           'daily accurate reliable fast similar popular top'.split())
GENERIC_ACTIONS = set('get check make create run build show list return fetch give take put set see view open '
                      'text data information info result results item items line lines keyword keywords'.split())


# A demo/sample tool shows an output shape; it cannot perform the user's task.
DEMO_TOOL_NAME = re.compile(r'(?:^|[\s_.-])(?:demo|mock|sample|example)s?(?=$|[\s_.-])', re.I)
DEMO_TOOL_TEXT = re.compile(r'\b(?:demo|mock)\b|\bfixed (?:sample|example|input)\b|\bplaceholder\b|\bsample (?:data|output|response) only\b', re.I)
# Words that do not bind a tool to a different object ("translate_text", "get_weather").
GENERIC_TOOL_WORDS = set('''get set list search find run do make ai llm gpt text texts content data document documents doc docs
    file files message messages string strings any auto batch bulk fast quick live realtime multi api tool tools free pro basic
    simple smart advanced current now today by for to of the a an and with from into in on lookup fetch query check info
    detail details full one single new latest my your agent mcp v1 v2 v3 x402'''.split())


# A named platform in the request ("YouTube transcript") must be served by a tool for that platform.
PLATFORM_TERMS = set('''postgres postgresql youtube github gitlab bitbucket slack discord notion jira confluence whatsapp telegram twitter reddit
    linkedin instagram tiktok facebook arxiv pubmed spotify shopify stripe salesforce hubspot zendesk figma trello
    asana airtable dropbox gmail outlook wikipedia ethereum solana'''.split())


def _platform_served(platforms, resource, tool):
    text = ' '.join([str(resource.get('name') or ''), str(tool.get('name') or '').replace('_', ' '),
                     str(tool.get('description') or '')]).lower()
    return all(_term_in(platform, text) for platform in platforms)


def _real_tool(tool):
    # Usage examples in a description are documentation, not a demo; only explicit demo wording counts.
    description=str(tool.get('description')or'')
    return not (DEMO_TOOL_NAME.search(str(tool.get('name') or '')) or DEMO_TOOL_TEXT.search(_tool_purpose(description))
                or re.search(r'\bdemo mode\s+(?:is\s+)?on by default\b',description,re.I))


def _bound_elsewhere(core, terms, tool):
    """With one capability word, "translate_quiz" or "address_translate" serve another object than the request."""
    if len(core) != 1:
        return False
    # "agentbit.ai_translate": the dotted prefix is a provider namespace, not an object.
    segments = str(tool.get('name') or tool.get('id') or '').lower().split('.')
    split = lambda part: [t for t in re.split(r'[^a-z0-9]+', part) if t]
    named = [part for part in segments if any(_term_in(core[0], t) or _term_in(t, core[0]) for t in split(part))]
    if not named:
        return False
    tokens = split(named[-1])
    others = [t for t in tokens if not (_term_in(core[0], t) or _term_in(t, core[0]))
              and len(t) > 2 and t not in GENERIC_TOOL_WORDS and not t.isdigit()
              and not any(_term_in(term, t) or (len(t) >= 4 and term.startswith(t)) for term in terms)]
    return bool(others)


def _coverage(terms, tool):
    text = _tool_text(tool, {id(tool)})
    return sum(_term_in(term, text) for term in terms)


def _coherent_capability(terms, resource, tools):
    """One advertised tool, not a union of unrelated tools, must carry the task.

    A broad multi-tool listing whose agent description mentions the task words
    is not enough: its search tool is not a translation tool."""
    # Both capability words of a two-word task ("web search", "convert currency")
    # must name the same tool; one shared word ("web", "eur") is not the task.
    need = min(len(terms),2) if len(terms)<=3 else math.ceil(len(terms)*.75)
    described = {id(t) for t in _described_tools(resource, tools)}
    # The tool's own name must name the task; usage notes such as "send an email
    # to https://..." inside an unrelated tool's description do not. A single-tool
    # agent may name its task in that tool's first-sentence purpose instead.
    named = [t for t in tools if any(_term_in(term, _tool_text(t, set())) for term in terms)
             or (len(tools) == 1 and sum(_term_in(term, _tool_text(t, described)) for term in terms) >= need)]
    best = max((sum(_term_in(term, _tool_text(t, described)) for term in terms) for t in named), default=0)
    if best >= need:
        return True
    primary = (str(resource.get('name') or '') + ' ' + _tool_purpose(resource.get('description'))).lower()
    covered = sum(_term_in(term, primary) for term in terms)
    # A narrow agent (few skills) may state its capability once in its description.
    return covered >= need and len(tools) <= 3


def text_may_match(terms, resource, core=None):
    """Cheap necessary condition for task_scope_matches, checked before parsing contracts.

    Every admission path requires the coherence minimum of core words in the
    listing's own name, description or tool text; all of them are inside these
    raw fields, so a listing whose raw text lacks them cannot pass."""
    requested = set(terms)
    if not requested or requested.intersection({'discovery', 'marketplace', 'directory', 'catalog', 'routing'}):
        return True
    core = [term for term in (core or terms) if term in requested] or list(terms)
    need = min(len(core), 2) if len(core) <= 3 else math.ceil(len(core) * .75)
    # A stored capability text (name, description, advertised tool names and descriptions)
    # already contains every place an admission path reads; it is attached only when it
    # matches this row's current source exactly.
    raw = resource.get('_capability_text')
    if not isinstance(raw, str):
        raw = ' '.join(str(resource.get(key) or '') for key in
                       ('name', 'description', 'category', 'cap_tool_names', 'usage_tools', 'usage_full_tools',
                        'usage_guide', 'details')).lower().replace('_', ' ')
    found = 0
    for term in core:
        found += _term_in(term, raw)
        if found >= need:
            return True
    return False


GLOBAL_COVERAGE = re.compile(r'\b(?:worldwide|global(?:ly)?|international|any (?:city|location|place|address|country|point|region)|'
                             r'(?:all|every|most) (?:countries|cities|locations)|anywhere|around the world)\b', re.I)


def place_fit(terms, resource):
    """For a request that names a place, does the listing say it covers that place?

    A listing that names the place's region or global coverage fits; one without any
    coverage statement ("storm history by address") is kept but ranked after them."""
    from ..gateway.constraints import places_in_text
    target = set(places_in_text(' '.join(terms)))
    if not target:
        return True
    tools = _advertised_tools(resource)
    text = ' '.join([str(resource.get('name') or ''), str(resource.get('description') or '')] +
                    [str(t.get('name') or '').replace('_', ' ') + ' ' + str(t.get('description') or '')[:400] for t in tools[:40]])
    return bool(GLOBAL_COVERAGE.search(text) or target.intersection(places_in_text(text)))


def _service_focus(core, resource, terms=()):
    """Require the whole capability, rather than one platform word or a bundle inventory."""
    core = list(dict.fromkeys(core))
    if not core:
        return False
    name = str(resource.get('name') or '').lower().replace('_', ' ')
    lead = _tool_purpose(resource.get('description')).lower().replace('_', ' ')
    if set(core).intersection({'weather','forecast','temperature'}) and not _weather_scope_matches(terms or core, name+' '+lead):
        # A usable terrestrial tool inside a specialist bundle remains an alternative.
        return False
    covers = lambda text: all(_term_in(term, text) for term in core)
    if covers(name):
        return True
    tools = _advertised_tools(resource)
    domains = {'construction','renovation','remodeling','roofing','painting','decking','contractor','exterior'}
    requested_domain = set(terms).intersection(domains)
    if (set(core).intersection({'weather','forecast','temperature'}) and requested_domain
            and requested_domain.intersection(search_terms(name+' '+lead))
            and any(covers(str(tool.get('name') or '').replace('_',' ')+' '+_tool_purpose(tool.get('description'))) for tool in tools)):
        return True
    if resource.get('kind') == 'mcp' and 0 < len(tools) <= 3:
        # A small server qualifies when its tools actually perform this task.
        from .task_capability import matches
        if any(covers(str(tool.get('name') or '').replace('_', ' ')+' '+_tool_purpose(tool.get('description')))
               and matches(' '.join(core), tool, 'mcp', resource) for tool in tools):
            return True
    inventory = re.search(r'\b(?:\d+\+?\s+(?:[\w-]+\s+){0,4}tools?|all.in.one|toolkit|marketplace|directory|bundle|suite)\b', lead)
    return covers(name+' '+lead) and not inventory


def _weather_scope_matches(terms, text):
    """Check geographic and domain restrictions independently of task wording."""
    requested=set(terms)
    text=text.lower()
    if (re.search(r'\b(?:space weather|solar (?:wind|flares?|storms?)|geomagnetic|aurora|asteroids?|satellite passes|aviation|metar|taf)\b',text)
            and not requested.intersection({'space','solar','geomagnetic','aurora','asteroid','asteroids','satellite','aviation','metar','taf','airport','airports'})
            and not re.search(r'\b(?:current|local|hourly|daily|terrestrial|surface|city)[ -]weather\b|(?<!space )weather forecasts? (?:for|in)\b|\b(?:hourly|daily|7-day|5-day) forecasts?\b',text)):return False
    if re.search(r'\b(?:marine navigation|marine forecasts?|mediterranean)\b',text) and not requested.intersection({'marine','maritime','sea','sailing','tides','tide','surf','surfing','swell','coastal','ocean','mediterranean'}):return False
    if re.search(r'\bski\b|\bskiing\b|snowboard|snow conditions|\bsnow questions\b',text) and not requested.intersection({'ski','skiing','snow','snowboard','snowboarding','resort','resorts'}):return False
    from ..gateway.constraints import places_in_text
    # A focused gazetteer names the request's place and the listing's only coverage area.
    target=set(places_in_text(' '.join(terms)))
    us_only=bool(re.search(r'\bus weather\b|\bfor (?:a |an )?us (?:location|city)|national weather service|\bnws\b|\bnoaa\b|\bus[ -]only\b|united states only',text))
    worldwide=bool(re.search(r'worldwide|global|any (?:city|point|location)|anywhere',text))
    if target and 'us' not in target and us_only and not worldwide:return False
    scoped=set(places_in_text(text))
    if target and scoped and not target.intersection(scoped) and not worldwide:return False
    if 'kamchatka' not in requested and re.search(r'kamchatka|\u043a\u0430\u043c\u0447\u0430\u0442\u043a',text):return False
    if not requested.intersection({'prediction','kalshi','betting','odds','trading','market','forex','crypto'}) and re.search(r'\b(?:prediction[- ]markets?|kalshi|polymarket|cross-asset market data)\b',text):return False
    return True


def _coherence_possible(core, resource, tools):
    """Cheap necessary condition for _coherent_capability(core, resource, subset of tools).

    Coherence needs the listing's own name and leading sentence, or one tool's name plus
    its leading sentence, to carry the task words. Each text here contains the text that
    check reads, so a listing failing here fails it too. Gateway families repeat dozens of
    shared tools on every listing, and filtering those first cost seconds per search."""
    need = min(len(core), 2) if len(core) <= 3 else math.ceil(len(core) * .75)
    primary = (str(resource.get('name') or '') + ' ' + _tool_purpose(resource.get('description'))).lower()
    if sum(_term_in(term, primary) for term in core) >= need:
        return True
    for tool in tools:
        text = (str(tool.get('name') or tool.get('id') or '') + ' ' + _tool_purpose(tool.get('description'))).lower().replace('_', ' ')
        if sum(_term_in(term, text) for term in core) >= need:
            return True
    return False


def task_scope_matches(terms, resource, core=None, *, tools=None):
    """Require an advertised task capability, preserving restricted weather scope."""
    requested=set(terms)
    core=[term for term in (core or terms) if term in requested] or list(terms)
    tools=_advertised_tools(resource) if tools is None else tools
    # A directory's listed tools describe what it catalogs, not what it does.
    directory_request=bool(requested.intersection({'discovery','marketplace','directory','catalog','routing'}))
    # Both coherence checks below read a subset of these texts; reject before costly filtering.
    if not directory_request and not _coherence_possible(core, resource, tools):return False
    if tools and not directory_request:
        tools=_task_tools(tools, core)
        if not tools:return False
        if not _evidence_matches(core, resource, tools):return False
        if not _coherent_capability(core, resource, tools):return False
    if not tools and not _coherent_capability(core,resource,[]):return False
    if not _asset_class_matches(requested, resource, tools):return False
    primary=' '.join(str(resource.get(k) or '') for k in ('name','description')).lower()
    described=_described_tools(resource,tools)
    purpose_text=primary+' '+' '.join(_tool_purpose(t.get('description')).lower() for t in described)
    capability_text=primary+' '+str(resource.get('usage_tools') or '')+' '+str(resource.get('usage_guide') or '')
    from .task_requirements import news_scope_matches,documentation_scope_matches
    if 'news' in core and not news_scope_matches(terms,resource,tools):return False
    if not documentation_scope_matches(terms,resource):return False
    if 'wallet' in requested and not re.search(r'\b(?:wallet|address)(?:s|es)?\b',primary):return False
    if 'wallet' in requested and 'ethereum' in requested and not re.search(r'\b(?:ethereum|evm|erc.?20)\b',purpose_text):return False
    if requested.intersection({'monitor','monitoring'}) and 'wallet' in requested:
        if not re.search(r'\b(?:monitor\w*|activit\w*|transactions?|deltas?|changes?)\b',purpose_text):return False
        if requested.intersection({'token','tokens'}) and not re.search(r'\b(?:tokens?|erc.?20|portfolio|holdings)\b',_tool_purpose(primary)):return False
    if 'forecast' in requested and 'weather' in requested and (not re.search(r'\bforecast\w*\b',purpose_text) or not re.search(r'\bweather\w*\b',purpose_text)):return False
    if requested.intersection({'stock','stocks','equity','equities','shares'}) and requested.intersection({'price','prices','quote','quotes','ticker'}):
        # A quote request needs market prices, not equity-compensation or tax planning.
        if not re.search(r'\b(?:quotes?|prices?|bars|ohlcv?|tickers?|market data)\b',purpose_text):return False
        # "In stock" and shipping quotes are retail; a market quote names the market.
        if not re.search(r'\b(?:stock (?:market|quotes?|prices?|tickers?|exchanges?|data)|(?:us|listed|public|tokeni[sz]ed|global) stocks|'
                         r'stocks (?:and|&) (?:etfs|options|bonds)|equit(?:y|ies)|nasdaq|nyse|tickers?|'
                         r'market data|share prices?|listed companies|securities)\b',purpose_text):return False
        if re.search(r'\b(?:equity[- ]compensation|compensation planning|tax planning)\b',_tool_purpose(primary)):return False
    if {'exchange','rate'}.issubset(requested) or requested.intersection({'currency','currencies','forex'}):
        # A currency request needs currency rates, not crypto funding rates or an exchange listing.
        if not CURRENCY_TOOL.search(purpose_text):return False
    if 'unit' in requested and requested.intersection({'convert','conversion'}) and re.search(r'\b(?:public housing|housing authority|mortgage|rent)\b',purpose_text):return False
    if 'route' in requested and not requested.intersection({'flight','flights','aircraft','aviation','airport','airports','ferry','airline','airlines'}) and re.search(r'\b(?:ferry[- ]flight|aircraft|faa[- ]registry|aviation|live[- ]flight)\b',primary):return False
    if {'pull','requests'}.issubset(requested) or 'pr' in requested and requested.intersection({'github','gitlab','repository'}):
        # A pull request is code review on a hosting service, not a quote or data "pull request".
        if not re.search(r'\b(?:github|gitlab|bitbucket|git|repositor\w*|code review|merge requests?)\b',purpose_text+' '+capability_text):return False
    if requested.intersection({'security','vulnerability','vulnerabilities'}) and not re.search(r'\b(?:secur\w*|vulnerab\w*)\b',purpose_text):return False
    if requested.intersection({'timestamp','timestamps'}) and not re.search(r'\b(?:timestamps?|time[- ]?codes?|srt|vtt|subtitles?|captions?)\b',capability_text):return False
    if requested.intersection({'weather','forecast','temperature'}):
        weather_text=(primary+' '+' '.join(_tool_purpose(t.get('description')) for t in tools if re.search(r'weather|forecast',str(t.get('name') or ''),re.I))).lower()
        if not _weather_scope_matches(terms,weather_text):return False
    if 'news' in core and requested.intersection({'technology','tech','artificial','intelligence'}):
        if not re.search(r'\b(?:technology|tech|artificial intelligence|ai news|hacker ?news)\b',primary):
            from .task_requirements import queryable_news
            if not queryable_news(resource,tools):return False
    if requested.intersection({'flight','flights'}) and requested.intersection({'hotel','hotels'}):
        if not re.search(r'\b(?:flight|flights|airfare)\b',primary) or not re.search(r'\bhotels?\b',primary):return False
    if 'translation' in requested and re.search(r'\bdictionar(?:y|ies)\b',primary):
        if not re.search(r'\b(?:text|sentence|document|message) (?:translat|translation)',capability_text):return False
    if requested.intersection({'translation','translate','translator','audio','transcription'}):
        from ..gateway.constraints import unpack
        languages=set(unpack(resource.get('cap_languages')))
        explicitly=set()
        for code,names in [('en',r'english'),('ja',r'japanese'),('ko',r'korean'),('es',r'spanish'),('de',r'german'),('fr',r'french')]:
            if re.search(r'\b(?:'+names+r')\b',' '.join(terms)):explicitly.add(code)
        needed=explicitly or ({'en'} if requested.intersection({'audio','transcription'}) else set())
        if languages and needed and not needed.issubset(languages):return False
        if not languages and not _regional_languages_cover(requested, purpose_text):return False
    if requested.intersection({'documentation','docs'}):
        subjects=requested.intersection({'python','javascript','typescript','react','kubernetes','rust','postgresql','java','golang'})
        names={str(t.get('name') or '') for t in tools}
        broad=bool(re.search(r'any (?:library|framework)|(?:libraries|frameworks).{0,100}(?:documentation|docs)|(?:documentation|docs).{0,100}(?:libraries|frameworks)',purpose_text) or {'query-docs','resolve-library-id'}.issubset(names))
        if subjects and not broad and not any(_term_in(term,primary+' '+str(resource.get('usage_tools') or '')) for term in subjects):return False
    # A directory can describe another protocol's tools without executing those
    # tasks on this A2A connection. Do not promote discovery as task execution.
    if resource.get('kind')=='a2a' and not requested.intersection({'discovery','marketplace','directory','catalog','routing'}):
        if re.search(r'a2a (?:is )?discovery[- ]only|a2a.{0,40}never retrieves',capability_text,re.I):return False
        # Some A2A cards advertise downstream services but only return a catalog.
        concierge_only=re.search(r'\b(?:discovery agent|receptionist|(?:free )?concierge|marketplace for agent-purchasable capabilities|tool[- ]discovery card|not an a2a)\b|(?:returns?|replies with).{0,80}(?:matching (?:paid |specialist )?(?:tools?|endpoints?|agents?)|same guide)',primary)
        if concierge_only:return False
        discovery_only=re.search(r'(?:over|via|through) a2a.{0,240}(?:names? the tools|names? tools|lists? (?:the )?tools|returns? (?:matching )?listings|discover)',primary)
        if discovery_only:return False
        other_transport=re.search(r'(?:pay[- ]per[- ]call|calls?|execution|access).{0,40}(?:over|via|through|with)\s+(?:the\s+)?x402\b',primary)
        if other_transport and not re.search(r'\ba2a\b',primary):return False
    # A single coherent capability must cover the task. Joining unrelated
    # search, accounting and conversion tools creates false document matches.
    if requested.intersection({'pdf','invoice','invoices','receipt','receipts'}):
        if tools:
            if not any(_task_tool_matches(terms, tool) for tool in tools):return False
        elif not _document_capability_matches(requested, primary):return False
    if not requested.intersection({'weather','forecast','forecasts','temperature','rainfall'}):return True
    construction={'construction','renovation','remodeling','roofing','painting','decking','contractor','exterior'}
    if requested.intersection(construction):return True
    # A dedicated forecast provider may also mention construction customers.
    if re.search(r'\bweather\s+forecasts?\b|\b(?:weather|forecast)[-_ ](?:agent|service|api|server)\b',primary):return True
    if not construction.intersection(re.findall(r'[a-z]+',primary)):return True
    tools=_json(resource.get('usage_tools'),[])
    descriptions=' '.join(str(t.get('description') or '') for t in tools if isinstance(t,dict)).lower()
    restricted=re.search(r'weather.*(?:suitability|construction projects|roofing|painting|decking)',descriptions)
    return not bool(restricted)


class QualityRecommender(Recommender):
    """Task relevance and safety gate admission; successful verification recency ranks first."""

    @observed('recommendation')
    @contract_reads  # reuse immutable contract parsing across the candidates of one request
    def search(self, task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None):
        from .protocols import search_protocols
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 600 or not 0 <= offset < 600:
            return []
        if auth_pref not in (None, '', 'any', 'none', 'agent'):
            return []
        if (category is not None and (type(category) is not str or not category.strip()
                or len(category) > 256 or any(ord(c) < 32 for c in category))):
            return []
        if hint is not None and (type(hint) is not str or len(hint) > 500 or any(ord(c) < 32 for c in hint)):
            return []
        category = category.strip() if category is not None else None
        auth_pref = auth_pref if auth_pref in ('none', 'agent') else None
        if kind in (None, '', 'auto', 'any'):
            target = min(600, offset + limit)
            focused, incidental = [], []
            for protocol in search_protocols(kind):
                tiers = []
                found = self._search_protocol(task, kind=protocol, auth_pref=auth_pref,
                    limit=target, exclude=exclude, hint=hint, category=category, tiers=tiers)
                # A2A first, then MCP, within each tier: a listing about the task precedes
                # a bundle where one of many tools matches.
                focused.extend(item for item, focus in zip(found, tiers) if focus)
                incidental.extend(item for item, focus in zip(found, tiers) if not focus)
                if len(focused) >= target:
                    break
            return (focused + incidental)[offset:offset+limit]
        return self._search_protocol(task, kind, auth_pref, limit, offset, exclude, hint, category)

    def _search_protocol(self, task, kind, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None, tiers=None):
        if kind is not None and kind not in ('a2a', 'mcp', 'x402'):
            return []
        from .discovery import enabled,normalize_task,candidates
        from .chat_task_spec import parse, tool_fit, task_proof
        spec = parse(task)
        normalized=normalize_task(task)
        terms = search_terms(normalized) or search_terms(hint or '')
        if not terms:
            return []
        core = capability_terms(normalized) or capability_terms(hint or '')
        scope_terms=list(dict.fromkeys(terms+search_terms(task)))
        from .discovery import lexical_match
        match = lexical_match(terms, ' OR ')
        now = time.time()
        excluded = set(exclude or ())
        # The two indexed lookups also cover old reports linked by URL rather than resource_id.
        native = getattr(self.store, 'selection_candidates', None)
        bounded=getattr(self.store,'selection_candidates_for',None)
        if enabled(self.rag_engine) and callable(bounded):
            # Only ids and their order are used here; contracts are read lazily below.
            options = {'kind': kind, 'category': category, 'maximum': 600, 'ranking_only': True}
            if hint:
                options['retrieval_hint'] = hint
            shortlist=candidates(self.store,self.rag_engine,task,**options)
            rows=bounded([r['id'] for r in shortlist],kind,now-MAX_HEALTH_AGE)
        else:
            rows = (native(match, kind, now-MAX_HEALTH_AGE) if callable(native) else
                    self.store.query(_candidate_sql(), (match, kind, kind, now-MAX_HEALTH_AGE,
                        now-MAX_HEALTH_AGE, now-MAX_HEALTH_AGE)))
        # Broad questions can match tens of thousands of listings; read their
        # contracts in bounded batches, in the order they will be examined.
        bulk = getattr(self.store,'recommendation_resources',None)
        loaded = {}
        upcoming = {'ids':[], 'at':{}}
        def plan(ids):
            upcoming['ids'] = ids
            upcoming['at'] = {rid:index for index,rid in enumerate(ids)}
        def resource_at(rid):
            if not callable(bulk):
                return self.store.resource(rid)
            if rid not in loaded:
                start = upcoming['at'].get(rid)
                batch = [rid] if start is None else [i for i in upcoming['ids'][start:start+RESOURCE_BATCH] if i not in loaded]
                found = bulk(batch)
                loaded.update({i:found.get(i) for i in batch})
            return loaded[rid]
        plan([row['id'] for row in rows if row['report_at']])
        report_ids=list(dict.fromkeys(row['report_id']for row in rows if row['report_at'] and row['report_id']))
        batch_reports=getattr(self.store,'recommendation_report_evidence',None)
        reports,report_store=(batch_reports(report_ids) if callable(batch_reports) and len(report_ids)<=600
                              else (None,self.store))
        choices = []
        report_resources = {}
        for raw in rows:
            r = dict(raw)
            if r.get('kind') != kind or r['id'] in excluded or category is not None and r.get('category') != category:
                continue
            def stamp(value):
                value = _number(value)
                return value if 0 < value <= now+300 else 0
            report_at = stamp(r['report_at'])
            if report_at:
                subject = resource_at(r['id'])
                report = reports.get(r['report_id']) if reports is not None else self.store.get_test_report(r['report_id'])
                if subject and report and measured_report(report, subject, report_store, now):
                    report_resources[r['id']] = subject
                else:
                    # Keep the administrative record, but never promote a
                    # publication timestamp or an unrelated/versionless subject.
                    report_at = 0
                    for field in ('report_id','report_grade','report_score','report_success',
                                  'report_status','report_latency','report_tool','report_version'):
                        r[field] = None
            trial = _json(r['trial_info'], {})
            trial_at = stamp(trial.get('at'))
            report_status = 200 if r['report_status'] is None else _number(r['report_status'],-1)
            report_ok = bool(report_at and r['report_success'] == 1 and
                             (200 <= report_status < 300 or (r['kind']=='x402' and report_status==402)))
            success_at = max(report_at if report_ok else 0, trial_at if r['trial_ok'] == 1 else 0)
            failure_at = max(report_at if report_at and not report_ok else 0, trial_at if r['trial_ok'] == 0 else 0)
            execution_at=stamp(r['execution_at'])
            if execution_at and _number(r['execution_expires'])>now:
                if r['execution_outcome']=='succeeded':success_at=max(success_at,execution_at)
                else:failure_at=max(failure_at,execution_at)
            # A card/health handshake alone does not prove an A2A task works.
            if r['kind']=='a2a' and not success_at:
                continue
            if failure_at and failure_at >= success_at:
                continue
            if r['trial_ok'] == 0 and not trial_at and not report_ok:
                continue
            active_at = max(stamp(r['last_ok_at']), success_at)
            if active_at < now-MAX_HEALTH_AGE:
                continue
            resource_grade = str(r['eval_grade'] or '').upper()
            report_grade = str(r['report_grade'] or '').upper() if report_at else ''
            grade = report_grade if report_grade in 'ABCDF' and report_grade and report_at >= stamp(r['eval_at']) else resource_grade
            if grade not in ('A','B','C','D','F'):
                grade = report_grade if report_grade in ('A','B','C','D','F') else None
            if grade == 'F':
                continue
            score = min(100,max(0,_number(r['report_score'] if report_at >= stamp(r['eval_at']) and r['report_score'] is not None else r['eval_score'])))
            reliability = (_number(r['health_ok_24h'])+1)/(_number(r['health_n_24h'])+2)
            latency = _number(r['report_latency'] if report_ok else r['probe_latency_ms'], float('inf'))
            rank = (int(bool(success_at)), success_at, active_at,
                    (5-'ABCDF'.index(grade)) if grade else 0, score, reliability, -latency)
            choices.append((rank,r,grade,score,active_at,report_at,report_ok))
        # Verify relevance lazily in recency order. Safety and relevance still gate every candidate.
        # This preserves the exact ordering while avoiding tokenizing every matching listing on every question.
        choices.sort(key=lambda row:row[0],reverse=True)
        plan([choice[1]['id'] for choice in choices])
        seen_capabilities=set()
        focused, unplaced, incidental = [], [], []
        wanted = max(0, offset) + limit
        examined_after_fill = 0
        for _, group in itertools.groupby(choices,key=lambda row:row[0]):
            if len(focused) + len(unplaced) + len(incidental) >= wanted:
                # Enough places are filled; look a bounded distance further for a listing
                # that is about the task before settling for bundled matches.
                if examined_after_fill >= INCIDENTAL_LOOKAHEAD:
                    break
            matches = []
            for choice in group:
                evidence = choice[1]
                if not usable_endpoint(evidence['url']):
                    continue
                resource = report_resources.get(evidence['id']) or resource_at(evidence['id'])
                if not resource:
                    continue
                declared = next((resource.get(key) for key in ('auth_observed', 'auth_declared', 'auth_required')
                                 if resource.get(key) is not None), None)
                if auth_pref == 'none' and declared not in (None, False, 0):
                    continue
                if auth_pref == 'agent' and declared not in (None, False, 0) and resource.get('auth_autonomy') != 'agent_autonomous':
                    continue
                from .task_requirements import input_requirements_match,supported_discovery_connection
                if not text_may_match(scope_terms,resource,core):continue
                if not task_scope_matches(scope_terms,resource,core):continue
                if not input_requirements_match(task,resource):continue
                if not supported_discovery_connection(resource):continue
                supported_tools=[t for t in _advertised_tools(resource) if _task_tool_matches(terms,t)]
                if not set(terms).intersection({'discovery','marketplace','directory','catalog','routing'}):
                    supported_tools=_task_tools(supported_tools,core)
                if resource['kind']=='mcp':
                    usable=[]
                    for tool in supported_tools:
                        try:supported_schema(tool)
                        except ExecutionDenied:continue
                        usable.append(tool)
                    supported_tools=usable
                from .retrieval_metrics import count
                fitted = [(tool, tool_fit(spec, tool)) for tool in supported_tools]
                count('constraint_unknown', sum(fit['status'] == 'unknown' for _, fit in fitted))
                count('constraint_mismatch', sum(fit['status'] == 'mismatch' for _, fit in fitted))
                platforms = PLATFORM_TERMS.intersection(core + capability_terms(task))  # normalization may drop the platform
                if 'sql' in scope_terms:platforms.update({'postgres','postgresql'}.intersection(scope_terms))
                supported_tools = [tool for tool, fit in fitted if fit['status'] == 'match' and _real_tool(tool)
                                   and (not platforms or _platform_served(platforms, resource, tool))]
                from .task_capability import matches as action_matches, needs_specific_action
                supported_tools = [tool for tool in supported_tools if action_matches(task,tool,resource['kind'],resource)]
                if resource['kind']=='x402'and not supported_tools:
                    if not action_matches(task,{'name':resource.get('name'),'description':resource.get('description')},'x402',resource):continue
                elif needs_specific_action(task) and not supported_tools:continue
                # Show the tool that covers most of the request, not merely the first listed.
                supported_tools.sort(key=lambda tool: _coverage(scope_terms, tool), reverse=True)
                # Provider-wide coverage cannot make one regional/market tool
                # global, or make a company dossier a topical news search.
                if resource['kind'] == 'mcp':
                    from .task_requirements import news_scope_matches
                    scoped = []
                    for tool in supported_tools:
                        single = {'kind':'mcp', 'name':str(tool.get('name') or '').replace('_',' '),
                                  'description':tool.get('description') or '', 'usage_tools':[tool]}
                        if set(scope_terms).intersection({'weather','forecast','temperature'}):
                            if not _weather_scope_matches(scope_terms,single['name']+' '+single['description']):continue
                        if {'exchange','rate'}.issubset(scope_terms) or set(scope_terms).intersection({'currency','currencies','forex'}):
                            if not CURRENCY_TOOL.search((single['name']+' '+single['description']).lower()):continue
                        if 'news' in core:
                            properties = (tool.get('inputSchema') or {}).get('properties', {})
                            topic_input = set(properties).intersection({'query','q','keyword','keywords','search','topic'})
                            if not topic_input and not re.search(r'\b(?:news|headlines)\b', single['name'], re.I):continue
                            if not news_scope_matches(scope_terms, single, [tool]):continue
                        scoped.append(tool)
                    supported_tools = scoped
                # A provider-wide claim cannot substitute for a callable tool.
                if resource['kind'] == 'mcp':
                    scoped_resource = {**resource, 'name': '', 'description': ''}
                    supported_tools = [tool for tool in supported_tools
                                       if _coherent_capability(core, scoped_resource, [tool])
                                       and not _bound_elsewhere(core, scope_terms, tool)]
                    visible = []
                    for tool in supported_tools:
                        schema = {'name': clean_external(tool.get('name') or tool.get('id'), 140),
                                  'description': clean_external(tool.get('description'), 200)}
                        schema.update({key:value for key,value in tool.items() if key in ('required','inputSchema')})
                        if 'params' in tool: schema['parameters'] = tool['params']
                        projected = public_agent(public_recommendation({'id':resource['id'], 'kind':'mcp',
                            'tools':[schema['name']], 'tools_schema':[schema]}), resource,
                            create_connections=False)
                        if projected.get('tools_schema'): visible.append(tool)
                    supported_tools = visible
                if (resource['kind'] == 'mcp' or spec.required) and not supported_tools:
                    continue
                display_text=' '.join([str(resource.get('name') or ''),str(resource.get('description') or '')]+
                                      [str(t.get('name') or '').replace('_',' ')+' '+str(t.get('description') or '') for t in supported_tools]).lower()
                need=min(len(core),2) if len(core)<=3 else math.ceil(len(core)*.75)
                if sum(_term_in(term,display_text) for term in core)<need:continue
                ranking_terms=core
                relevance = _relevance(ranking_terms,dict.fromkeys(ranking_terms,1.0),resource)
                if relevance < 0.35:
                    # Legacy lexical scores do not stem translate/translation.
                    # A complete task match on one admitted tool is stronger
                    # evidence than a spelling mismatch in the listing index.
                    scoped_resource={**resource,'name':'','description':''}
                    if not supported_tools or not _coherent_capability(core,scoped_resource,supported_tools):continue
                    relevance=0.35
                # Ignored candidates must not create registry versions or acquire
                # writer locks before their task relevance has been established.
                from ..capability_registry import Registry
                registry=Registry(self.store);current=registry.current(resource,create=False)
                ready=registry.projection(resource,version=current) if current else {}
                readiness = ready.get('connection_readiness', {})
                if readiness.get('reason') == 'latest_failure': continue
                if evidence.get('report_version') and current and evidence['report_version']!=current['id']:continue
                matches.append((relevance,-resource['id'],choice,resource,supported_tools))
            from .task_requirements import provider_identity, recommendation_identity
            unique=[]
            for candidate in sorted(matches,key=lambda row:row[:2],reverse=True):
                identities={recommendation_identity(candidate[3]),provider_identity(candidate[3])}-{None}
                if identities & seen_capabilities:continue
                seen_capabilities.update(identities);unique.append(candidate)
            for candidate in unique:
                if not _service_focus(core, candidate[3], scope_terms):
                    incidental.append(candidate)
                elif place_fit(scope_terms, candidate[3]):
                    focused.append(candidate)
                else:
                    unplaced.append(candidate)
            if len(focused) >= wanted:
                break
            if len(focused) + len(unplaced) + len(incidental) >= wanted:
                examined_after_fill += 1  # recency groups; each usually holds one listing
        # A listing about the task that does not state coverage of the requested place
        # follows the ones that do, ahead of bundles where one tool matches.
        focused = focused + unplaced
        ordered = focused + incidental
        selections = ordered[max(0, offset):max(0, offset)+limit]
        focus_ids = {id(candidate) for candidate in focused}
        flags = [id(candidate) in focus_ids for candidate in selections]
        if tiers is not None:
            tiers.extend(flags)
        result = []
        for relevance, _, selected, resource, selected_tools in selections:
            _,evidence,grade,score,active_at,report_at,report_ok = selected
            item = self.item(Scored(resource, round(relevance,4)))
            score_value = evidence['report_score'] if report_at >= _number(evidence['eval_at']) and evidence['report_score'] is not None else evidence['eval_score']
            item.update(grade=grade, quality_score=score if grade and _number(score_value,None) is not None else None, active_checked_at=active_at,
                        verified_working=bool(report_ok or (resource.get('trial_ok') == 1 and
                            stamp(_json(resource.get('trial_info'), {}).get('at'))) or
                            (evidence.get('execution_outcome') == 'succeeded' and
                             _number(evidence.get('execution_expires')) > now)),
                        selection_policy='single_recent_verified_first')
            if not usable_endpoint(item.get('usage_endpoint')) or endpoint_origin(item['usage_endpoint']) != endpoint_origin(item['url']):
                item['usage_endpoint'] = item['url']
            item['test_report'] = ({'id':evidence['report_id'],'created_at':evidence['report_created_at'],
                                    'executed_at':evidence['report_executed_at'],
                                    'grade':evidence['report_grade'],'success':report_ok} if report_at else None)
            # Return one task-relevant tool schema, rather than a catalog-sized tool list.
            tools = list(selected_tools)
            if not set(terms).intersection({'discovery','marketplace','directory','catalog','routing'}):
                tools = _task_tools(tools, core)
            if resource['kind']=='mcp':
                supported=[]
                for tool in tools:
                    try:supported_schema(tool)
                    except ExecutionDenied:continue
                    supported.append(tool)
                tools=supported
                # The inherited catalog item may contain the same unsupported tool.
                # Do not advertise it when no locally supported MCP schema remains.
                item['tools']=[];item['tools_schema']=[]
            if tools:
                described = {id(t) for t in _described_tools(resource, tools)}
                tool = max(tools,key=lambda t:(
                    sum(_term_in(term, _tool_text(t, described)) for term in core),
                    sum(_term_in(term, _tool_text(t, described)) for term in terms),
                    t.get('name')==evidence['report_tool']))
                item['tools'] = [clean_external(tool.get('name') or tool.get('id'),140)]
                schema = {'name':item['tools'][0],'description':clean_external(tool.get('description'),200)}
                schema.update({k:v for k,v in tool.items() if k in ('required','inputSchema')})
                if 'params' in tool:
                    schema['parameters'] = tool['params']
                item['tools_schema'] = [schema]
                item['task_fit'] = tool_fit(spec, tool)
                item['task_verification'] = task_proof(item['tools'][0],
                    self.store.get_test_report(evidence['report_id']) if report_ok else None, report_ok)
                count('task_tool_verified' if item['task_verification']['status'] == 'verified' else 'task_tool_unverified', 1)
            # Why it was selected, stated only from the listing's own words.
            evidence_text = ' '.join([str(resource.get('name') or ''), str(resource.get('description') or '')] +
                                     [s.get('name','')+' '+s.get('description','') for s in item.get('tools_schema') or []]).lower()
            item['matched_terms'] = [term for term in core if _term_in(term, evidence_text)][:6]
            from .discovery_state import contract_summary
            item = public_recommendation(item)
            item['capability_contract'] = contract_summary(self.store, resource, item)
            item['revalidate_after_sec'] = 3600
            result.append(public_agent(item, resource,store=self.store,create_connections=not enabled(self.rag_engine)))
        for item, focus in zip(result, flags):
            # 'listing': the service itself is about the task; 'tool': one of its tools matches.
            item['match_basis'] = 'listing' if focus else 'tool'
        return result

    def improvements(self, vid, interests, failed):
        """A change of winner uses the same quality order as discovery, never the old price score."""
        improvements = []
        for interest in interests:
            candidates = self.search(interest['task'],exclude=failed)
            if not candidates:
                continue
            best = candidates[0]
            previous = {r['id']:r for r in interest['recommended']}
            old = previous.get(best['id'])
            reason = None
            if old is None:
                reason = 'new_better'
            elif best['grade'] and (not old.get('grade') or 'ABCDF'.index(best['grade']) < 'ABCDF'.index(old['grade'])):
                reason = 'grade_up'
            if reason:
                improvements.append({'interest_id':interest['id'],'task':interest['task'],
                                     'items':[{**best,'reason':reason,'previous_grade':old.get('grade') if old else None,
                                               'previous_best':interest.get('best_score')}],'all':candidates})
        return improvements
