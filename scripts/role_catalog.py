"""Every role the pearl tests use: tool-name pattern to find members, a public input, and default checks whose answers
can be confirmed from a public source (PM 11-14: 30 roles by 11-21, one list of role names).

Roles with a workflow role task (agent_market/necklaces/role_tasks) are judged by that task; the checks here are the
fallback. Names are contract ids (`*.v1`), the same list the workflow team uses.
"""
import re

ROLES = {
    # roles that already have workflow role tasks (pattern finds members; input/checks come from the task)
    'papers.search.v1': {'tools': r'^(?:search_papers|paper_search|search_arxiv|arxiv_search|search_literature|openalex_search\w*|search_research_papers|academic_search)$'},
    'encyclopedia.summary.v1': {'tools': r'^(?:wikipedia_\w*summary|wiki_?summary|get_wikipedia\w*|get_article_summary|wiki\w*_summary|wikipedia_search|encyclopedia\w*)$'},
    'news.search.v1': {'tools': r'^(?:search_news|news_search|get_news|latest_news|get_headlines|top_headlines|search_articles)$'},
    'package.advisories.v1': {'tools': r'^(?:osv_query\w*|query_osv|search_vulnerabilities|get_vulnerabilities|scan_package\w*|check_package_vulnerabilit\w*|package_vulnerabilit\w*|check_software)$'},
    'package.health.v1': {'tools': r'^(?:get_package\w*|package_info|lookup_package|lookup_npm_package|npm_package\w*|pypi_package\w*|package_metadata|get_package_profile|depsdev\w*)$'},
    'cve.exploited.v1': {'tools': r'^(?:kev\w*|get_kev\w*|cisa_kev\w*|cve_kev\w*|check_kev|is_exploited)$'},
    'cve.record.v1': {'tools': r'^(?:get_cve|cve_lookup|lookup_cve|cve_details|search_cve\w*|cve_search|nvd\w*)$'},
    'company.registry.v1': {'tools': r'^(?:lookup_company|search_company|company_profile|get_company\w*|company_register_search|verify_business|corporate_kyb\w*|lei_lookup|get_lei\w*)$'},
    'web.grounding.v1': {'tools': r'^(?:ask\w*grounded|grounded_answer|answer_question|web_answer|search_and_answer|ask_web)$'},
    'country.indicator.v1': {'tools': r'^(?:\w*country_indicator\w*|get_indicator|world_bank\w*|worldbank\w*|get_gdp|country_stats|get_country_data|get_country_stats)$'},
    'fx.rate.v1': {'tools': r'^(?:convert|convert_currency|currency_convert\w*|fx_get_rate|get_exchange_rates?|get_rates?|exchange_rate|get_fx_rate|fx_rate)$'},
    'weather.forecast.v1': {'tools': r'^(?:get_forecast|weather_forecast|get_weather|forecast|weather|current_weather|get_weather_forecast)$'},
    'events.search.v1': {'tools': r'^(?:search_events|find_events|events_search|get_events|festivals\w*|concerts\w*)$'},
    'software.incident.v1': {'tools': r'^(?:latest_incidents|search_incidents|get_incidents|incident_search)$'},
    'website.ai_readiness.v1': {'tools': r'^(?:\w*ai_readiness\w*|check_llms_txt|audit_site|scan_site)$'},
    'package.risk.v1': {'tools': r'^(?:\w*openssf_scorecard\w*|scorecard|get_scorecard|repo_scorecard)$',
                        'input': {'repo': 'github.com/facebook/react', 'repository': 'github.com/facebook/react', 'package': 'react', 'ecosystem': 'npm'},
                        'checks': [('react named', r'react'), ('a score', r'score')]},
    # RAG default-check roles (11-14): public answers, checked with fields and words
    'domain.lookup.v1': {'tools': r'^(?:whois\w*|lookup_domain|domain_lookup|domain_info|get_domain_info|rdap\w*)$',
                         'input': {'domain': 'python.org'},
                         'checks': [('domain echoed', r'python\.org'),
                                    ('registrar or a date', r'registrar|created|creation|registered|expir|\b(?:19|20)\d{2}-\d{2}-\d{2}')]},
    'place.search.v1': {'tools': r'^(?:search_places|find_places|get_place|place_search|search_poi\w*|geocode_place)$',
                        'input': {'query': 'Eiffel Tower'},
                        'checks': [('Paris', r'paris'), ('address or coordinates', r'48\.85|2\.29|champ|avenue|address|latitude|"lat')]},
    'book.search.v1': {'tools': r'^(?:search_books|find_books|book_search|lookup_book|search_book|get_book_by_title)$',
                       'input': {'query': 'Pride and Prejudice', 'title': 'Pride and Prejudice'},
                       'checks': [('author', r'austen')]},
    # Prices move: judged by format, a time stamp and a range against a public reference at the same time
    # (PM 11-14: +-2%), never by an exact number.
    'crypto.price.v1': {'tools': r'^(?:get_crypto_price|crypto_price|get_coin_price|get_token_price|coin_price|get_bitcoin_price|price_of_coin)$',
                        'input': {'symbol': 'BTC', 'coin': 'bitcoin', 'id': 'bitcoin', 'query': 'bitcoin'},
                        'checks': [('bitcoin named', r'bitcoin|\bbtc\b'), ('USD stated', r'\busd\b|\$'),
                                   ('a time stamp', r'\b(?:19|20)\d{2}-\d{2}-\d{2}|\b\d{1,2}:\d{2}|timestamp|updated|as of|"time')],
                        'live': {'reference': 'https://api.coinbase.com/v2/prices/BTC-USD/spot', 'tolerance': 0.02,
                                 'terms_ok': False, 'note': 'Coinbase API terms on commercial reuse not confirmed (11-14)'}},
    'stock.quote.v1': {'tools': r'^(?:get_quote|get_stock_quote|stock_quote|get_stock_price|quote_stock)$',
                       'input': {'symbol': 'AAPL', 'ticker': 'AAPL'},
                       'checks': [('AAPL named', r'\baapl\b|apple'), ('USD or a price field', r'\busd\b|\$|price|close|last'),
                                  ('a time stamp', r'\b(?:19|20)\d{2}-\d{2}-\d{2}|\b\d{1,2}:\d{2}|timestamp|updated|as of|"time')],
                       'live': {'reference': 'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d', 'tolerance': 0.02,
                                'terms_ok': False, 'note': 'Yahoo chart endpoint is unofficial and for personal use'}},
    'geocode.address.v1': {'tools': r'^(?:geocode|geocode_address|forward_geocode|address_to_coordinates)$',
                           'input': {'address': '1600 Pennsylvania Avenue NW, Washington, DC', 'query': '1600 Pennsylvania Avenue NW, Washington, DC'},
                           'checks': [('latitude 38.89', r'38\.89'), ('longitude -77.03', r'-77\.0[34]')]},
    'ip.lookup.v1': {'tools': r'^(?:ip_lookup|lookup_ip|get_ip_info|ip_info|geolocate_ip|ip_geolocation|whois_ip|ip_intel\w*)$',
                     'input': {'ip': '8.8.8.8', 'ip_address': '8.8.8.8', 'query': '8.8.8.8'},
                     'checks': [('8.8.8.8 echoed', r'8\.8\.8\.8'), ('Google or AS15169', r'google|15169')]},
    'timezone.time.v1': {'tools': r'^(?:get_time|current_time|get_current_time|time_in|world_time|get_timezone|timezone_info|convert_time|time_now)$',
                         'input': {'timezone': 'America/New_York', 'tz': 'America/New_York', 'city': 'New York', 'location': 'New York'},
                         'checks': [('a clock time', r'\b\d{1,2}:\d{2}'), ('zone named', r'new.?york|america/new_york|\be[sd]t\b|utc-0?[45]|-0[45]:00')]},
    'dictionary.define.v1': {'tools': r'^(?:define|get_definition|define_word|lookup_word|dictionary\w*|word_definition|get_word)$',
                             'input': {'word': 'serendipity', 'term': 'serendipity', 'query': 'serendipity'},
                             'checks': [('word echoed', r'serendipity'), ('a definition', r'chance|accident|fortunate|luck|unexpected')]},
    'translate.text.v1': {'tools': r'^(?:translate|translate_text|translation)$',
                          'input': {'text': 'Good morning', 'target': 'fr', 'target_language': 'fr', 'target_lang': 'fr', 'to': 'fr'},
                          'checks': [('French greeting', r'bonjour')]},
    'github.repo.v1': {'tools': r'^(?:get_repo|get_repository|repo_info|search_repositories|search_repos|github_repo\w*|get_github_repo)$',
                       'input': {'repo': 'facebook/react', 'repository': 'facebook/react', 'owner': 'facebook', 'name': 'react', 'query': 'react'},
                       'checks': [('react named', r'facebook/react|\breact\b'), ('license or stars', r'\bmit\b|stars?|stargazers')]},
    'holiday.calendar.v1': {'tools': r'^(?:get_holidays|list_holidays|public_holidays|holidays|get_public_holidays)$',
                            'input': {'country': 'US', 'country_code': 'US', 'countryCode': 'US', 'year': 2026},
                            'checks': [('Independence Day', r'independence day|2026-07-0[34]'), ('Thanksgiving', r'thanksgiving')]},
    'sec.filings.v1': {'tools': r'^(?:get_filings|search_filings|sec_filings|get_company_filings|list_filings|edgar\w*)$',
                       'input': {'ticker': 'AAPL', 'cik': '320193', 'company': 'Apple Inc', 'query': 'Apple'},
                       'checks': [('Apple or CIK 320193', r'apple|320193'), ('a form type', r'10-k|10-q|8-k')]},
    'airport.lookup.v1': {'tools': r'^(?:get_airport|airport_info|lookup_airport|search_airports|airport_lookup)$',
                          'input': {'code': 'ICN', 'iata': 'ICN', 'iata_code': 'ICN', 'query': 'ICN'},
                          'checks': [('Incheon', r'incheon')]},
    'unit.convert.v1': {'tools': r'^(?:convert_units?|unit_convert\w*|convert_unit|units_convert)$',
                        'input': {'value': 10, 'amount': 10, 'from': 'mile', 'to': 'kilometer', 'from_unit': 'mile', 'to_unit': 'kilometer'},
                        'checks': [('16.09', r'16\.09')]},
    'earthquake.feed.v1': {'tools': r'^(?:get_earthquakes|earthquakes|recent_earthquakes|list_earthquakes|search_earthquakes)$',
                           'input': {'min_magnitude': 5, 'minmagnitude': 5, 'magnitude': 5},
                           'checks': [('magnitude', r'\bmag'), ('M5 or more', r'\b[5-9]\.\d\b')]},
}

COMPILED = {role: re.compile(spec['tools'], re.I) for role, spec in ROLES.items()}


def roles_for_tool(name):
    return [role for role, pattern in COMPILED.items() if pattern.match(str(name or ''))]


def default_checks(role):
    return ROLES.get(role, {}).get('checks') or []


def live_spec(role):
    return ROLES.get(role, {}).get('live')


def catalog_input(role):
    return dict(ROLES.get(role, {}).get('input') or {})
