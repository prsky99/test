"""Fill the "Run here" arguments from the task when the value is certain (PM 11-16 08:2x, connect-gap plan B1).

The recommended tool's call line used typed placeholders (`{"location":"<location>"}`), so a caller had to fill it in
and call again before seeing a result (reports/connect-gap-2026-11-16). fill(task, tool, arguments) replaces only
placeholders ('<name>' strings that connections.example_arguments wrote) and only when:
- the argument's name says what kind of value it takes (city, domain, url, ip, cve, date, doi, symbol, ...), and
- the task holds exactly one value of that kind, in a form that is certain by itself (a domain, an IPv4 address, a
  CVE id, an ISO date, a DOI, a currency code from a fixed list, a city from a fixed list, a listed ticker).
Anything else stays a placeholder: no guessed values, no model, no database, no network (PM: no added latency).
Enum, default and number examples are left as they are. Placeholders are filled all or none (검색과 RAG 08:4x: one
call should give a result), each value at most 200 characters on one line, never an e-mail address.
"""
import re

PLACEHOLDER = re.compile(r'^<[\w-]{1,40}>$')
MAX_VALUE = 200
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')

# Cities by the name a task uses; the value is the usual English name. States, regions and words that are also
# ordinary English words are left out.
CITIES = {name: name.title() for name in (
    'seoul', 'busan', 'incheon', 'daegu', 'daejeon', 'gwangju', 'ulsan', 'suwon', 'tokyo', 'osaka', 'kyoto',
    'yokohama', 'sapporo', 'nagoya', 'fukuoka', 'kobe', 'beijing', 'shanghai', 'shenzhen', 'guangzhou', 'chengdu',
    'hangzhou', 'wuhan', 'new york', 'chicago', 'los angeles', 'san francisco', 'seattle', 'boston', 'miami',
    'denver', 'atlanta', 'las vegas', 'honolulu', 'london', 'manchester', 'liverpool', 'edinburgh', 'glasgow',
    'paris', 'lyon', 'marseille', 'berlin', 'munich', 'hamburg', 'frankfurt', 'cologne', 'sydney', 'melbourne',
    'brisbane', 'adelaide', 'toronto', 'vancouver', 'montreal', 'ottawa', 'calgary', 'delhi', 'mumbai', 'bangalore',
    'bengaluru', 'chennai', 'kolkata', 'hyderabad', 'bangkok', 'chiang mai', 'jakarta', 'hanoi', 'ho chi minh city',
    'manila', 'kuala lumpur', 'singapore', 'hong kong', 'taipei', 'dubai', 'riyadh', 'doha', 'istanbul', 'cairo',
    'sao paulo', 'rio de janeiro', 'mexico city', 'buenos aires', 'bogota', 'lima', 'santiago', 'madrid',
    'barcelona', 'rome', 'milan', 'amsterdam', 'vienna', 'zurich', 'stockholm', 'oslo', 'copenhagen', 'helsinki',
    'dublin', 'lisbon', 'prague', 'warsaw', 'athens', 'moscow', 'johannesburg', 'nairobi', 'lagos', 'auckland')}
CITIES.update({'서울': 'Seoul', '부산': 'Busan', '인천': 'Incheon', '대구': 'Daegu', '대전': 'Daejeon', '광주': 'Gwangju',
               '도쿄': 'Tokyo', '오사카': 'Osaka', '교토': 'Kyoto', '베이징': 'Beijing', '상하이': 'Shanghai',
               '뉴욕': 'New York', '런던': 'London', '파리': 'Paris', '베를린': 'Berlin', '시드니': 'Sydney',
               '싱가포르': 'Singapore', '홍콩': 'Hong Kong', '방콕': 'Bangkok'})
_CITY = re.compile(r'(?<![\w])(' + '|'.join(sorted((re.escape(c).replace(r'\ ', r'\s+') for c in CITIES), key=len,
                                                   reverse=True)) + r')(?![\w])', re.I)

CURRENCIES = frozenset('''USD EUR JPY GBP KRW CNY AUD CAD CHF HKD SGD INR BRL MXN SEK NOK DKK NZD ZAR TRY THB TWD IDR
    PHP VND MYR PLN CZK HUF ILS AED SAR RUB'''.split())
STOCKS = frozenset('''AAPL MSFT GOOGL GOOG AMZN NVDA TSLA META NFLX AMD INTC IBM ORCL CRM ADBE PYPL UBER ABNB SHOP
    COIN PLTR SNOW BABA TSM ASML JPM BAC WMT DIS KO PEP NKE'''.split())
CRYPTO = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'solana': 'SOL', 'dogecoin': 'DOGE', 'cardano': 'ADA',
          'ripple': 'XRP', 'litecoin': 'LTC', 'polkadot': 'DOT', 'chainlink': 'LINK', 'tron': 'TRX'}
CRYPTO_IDS = {symbol: name for name, symbol in CRYPTO.items()}
CRYPTO_IDS['XRP'] = 'ripple'

_URL = re.compile(r'https?://[^\s<>"\'),]+', re.I)
_DOMAIN = re.compile(r'(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|org|net|io|ai|dev|app|co|biz|'
                     r'info|me|xyz|gov|edu|uk|de|fr|jp|kr|cn|in|us|ca|au|eu|tech|site|online|cloud))(?![\w.-]*@)(?![\w-])',
                     re.I)
_IPV4 = re.compile(r'(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])')
_CVE = re.compile(r'\bCVE-\d{4}-\d{4,7}\b', re.I)
_DATE = re.compile(r'(?<!\d)(20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))(?!\d)')
_DOI = re.compile(r'\b(10\.\d{4,9}/[^\s"<>]+[^\s"<>.,;)])')
_GITHUB = re.compile(r'github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100})', re.I)
_UPPER = re.compile(r'(?<![A-Za-z$])\$?([A-Z]{2,5})(?![A-Za-z])')
_PAIR = re.compile(r'\b([A-Za-z]{3})\s*(?:/|to|->|→|into|in)\s*([A-Za-z]{3})\b')

# Argument names by the kind of value they take (lower case, whole name).
KINDS = {
    'city': ('city', 'city_name', 'cityname', 'location', 'place', 'town'),
    'domain': ('domain', 'domain_name', 'hostname', 'host'),
    'url': ('url', 'uri', 'link', 'page_url', 'website_url', 'site_url', 'website', 'target_url'),
    'ip': ('ip', 'ip_address', 'ipaddress', 'ipv4'),
    'cve': ('cve', 'cve_id', 'cveid', 'vuln_id', 'vulnerability_id'),
    'date': ('date', 'day', 'on_date'),
    'doi': ('doi',),
    'repo': ('repo', 'repository', 'repo_name', 'full_name'),
    'owner': ('owner', 'org', 'organization', 'repo_owner'),
    'symbol': ('symbol', 'ticker', 'stock_symbol', 'ticker_symbol', 'coin_symbol'),
    'coin_id': ('coin_id', 'ids', 'coin'),
    'from_currency': ('from', 'from_currency', 'base', 'base_currency', 'source_currency', 'source'),
    'to_currency': ('to', 'to_currency', 'target', 'target_currency', 'quote', 'quote_currency', 'symbols'),
}
_KIND_OF = {name: kind for kind, names in KINDS.items() for name in names}


def _one(values):
    """The value when the task holds exactly one distinct value of the kind, else None."""
    distinct = list(dict.fromkeys(values))
    return distinct[0] if len(distinct) == 1 else None


def _currency_pair(task):
    pairs = [(a.upper(), b.upper()) for a, b in _PAIR.findall(task) if a.upper() in CURRENCIES and b.upper() in CURRENCIES]
    return _one(pairs)


def _symbol(task):
    found = [t for t in _UPPER.findall(task) if t in STOCKS or t in CRYPTO_IDS]
    lower = task.lower()
    found += [symbol for name, symbol in CRYPTO.items() if re.search(r'\b' + name + r'\b', lower)]
    return _one(found)


def values(task):
    """{kind: value} for every kind the task holds exactly one certain value of."""
    if not isinstance(task, str) or not task.strip():
        return {}
    task = task[:2000]
    out = {}
    urls = _URL.findall(task)
    rest = _URL.sub(' ', task)
    domains = [d.lower() for d in _DOMAIN.findall(rest)] + [re.sub(r'^https?://', '', u, flags=re.I).split('/')[0].lower()
                                                           for u in urls]
    found = {
        'city': _one(CITIES[re.sub(r'\s+', ' ', m.lower())] if m.lower() in CITIES else CITIES.get(m, m)
                     for m in _CITY.findall(task)),
        'url': _one(u.rstrip('.') for u in urls),
        'domain': _one(d for d in domains if not _IPV4.fullmatch(d)),
        'ip': _one(_IPV4.findall(task)),
        'cve': _one(c.upper() for c in _CVE.findall(task)),
        'date': _one(_DATE.findall(task)),
        'doi': _one(_DOI.findall(task)),
        'symbol': _symbol(task),
    }
    github = _one(_GITHUB.findall(task))
    if github:
        found['owner'], found['repo_name'] = github[0], re.sub(r'\.git$', '', github[1])
    pair = _currency_pair(task)
    if pair:
        found['from_currency'], found['to_currency'] = pair
    if found.get('symbol') in CRYPTO_IDS:
        found['coin_id'] = CRYPTO_IDS[found['symbol']]
    return {k: v for k, v in found.items() if v}


def fill(task, tool, arguments):
    """ARGUMENTS with the placeholders whose value the task makes certain filled in; a new dict, the rest unchanged.
    Returns the same arguments (equal dict) when nothing is certain."""
    if not isinstance(arguments, dict) or not any(isinstance(v, str) and PLACEHOLDER.match(v) for v in arguments.values()):
        return arguments
    found = values(task)
    if not found:
        return arguments
    out = dict(arguments)
    for name, value in arguments.items():
        if not (isinstance(value, str) and PLACEHOLDER.match(value)):
            continue
        kind = _KIND_OF.get(str(name).lower())
        filled = None
        if kind == 'repo':
            # "owner/name" when the argument is the only repository input, the bare name beside an owner argument
            owner_beside = any(_KIND_OF.get(str(n).lower()) == 'owner' for n in arguments if n != name)
            if 'owner' in found:
                filled = found['repo_name'] if owner_beside else found['owner'] + '/' + found['repo_name']
        elif kind and kind in found:
            filled = found[kind]
        if not _safe(filled):
            # 검색과 RAG 08:4x: fill only when every placeholder is certain, so one call gives a result
            return arguments
        out[name] = filled
    return out


def _safe(value):
    """A value that may go into the answer text: short, one line, no control characters, never an e-mail address."""
    return (isinstance(value, str) and 0 < len(value) <= MAX_VALUE and not _CONTROL.search(value)
            and '@' not in value)
