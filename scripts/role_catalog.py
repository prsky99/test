"""Every role the pearl tests use: tool-name pattern to find members, a public input, and default checks whose answers
can be confirmed from a public source (PM 11-14: 30 roles by 11-21, one list of role names).

Roles with a workflow role task (agent_market/necklaces/role_tasks) are judged by that task; the checks here are the
fallback. Names are contract ids (`*.v1`), the same list the workflow team uses.
"""
import re

NEVER = r'(?!)'   # a pattern that matches no tool name: the role is listed but not queued

ROLES = {
    # roles that already have workflow role tasks (pattern finds members; input/checks come from the task)
    'papers.search.v1': {'tools': r'^(?:search_papers|paper_search|arxiv_search|search_arxiv|pubmed_search|semantic_scholar_search|crossref_search|openalex_search\w*|searchPapers|search_literature|academic_search|fetch_arxiv_research_digest)$'},
    'encyclopedia.summary.v1': {'tools': r'^(?:wikipedia_summary|wiki_summary|wikipedia_get_summary|get_wikipedia_summary|encyclopedia_summary|wikipedia_article|wikipedia_search)$'},
    'news.search.v1': {'tools': r'^(?:get_latest_news|search_news|news_search|get_news|fetch_news|latest_news|gdelt_news|search_articles|search-news)$'},
    'package.advisories.v1': {'tools': r'^(?:osv_query\w*|query_osv|search_vulnerabilities|get_vulnerabilities|scan_package\w*|check_package_vulnerabilit\w*|package_vulnerabilit\w*|check_software|vulnerability_check|vulnerabilities|find_package_advisories|check_package|query_package)$'},
    'package.health.v1': {'tools': r'^(?:package_info|lookup_package|lookup_npm_package|npm_package\w*|pypi_package\w*|package_metadata|get_package_profile|depsdev\w*|read_package_info|package_status|package_health)$'},
    'cve.exploited.v1': {'tools': r'^(?:latest_kev|check_cisa_kev|cisa_search_kev|cisa_kev_lookup|kev_lookup|is_cve_exploited|search_kev|check_kev|cve_kev_lookup)$'},
    'cve.record.v1': {'tools': r'^(?:get_cve|lookup_cve|cve_lookup|cve_details|fetch_cve|get_cve_record|check_cve|get_vulnerability|osv_get_vulnerability)$'},
    'company.registry.v1': {'tools': r'^(?:lookup_company|search_company|search_companies|company_register_search|corporate_kyb\w*|lei_lookup|get_lei\w*|lei_kyb_check|validate_lei|find_company|company_search|verify_company_record)$'},
    # company.profile.v1 (PM 11-16, 53a620cc): one company's filing-based profile, input 'company'; profile names leave
    # company.registry.v1 so one member is not queued under both roles
    'company.profile.v1': {'tools': r'^(?:(?!get_french_company_profile)\w*company_profile|sec_company\w*)$'},
    'web.grounding.v1': {'tools': r'^(?:ask\w*grounded|grounded_answer|web_answer|search_and_answer|ask_web|\w+_web_grounding|\w+_grounding)$'},
    'country.indicator.v1': {'tools': r'^(?:\w*country_indicator\w*|country_profile|get_indicator|get_historical_indicators|world_bank\w*|worldbank\w*|get_gdp|country_stats|get_country_data|get_country_stats|get_economic_indicators)$'},
    'fx.rate.v1': {'tools': r'^(?:convert|get_exchange_rate|exchange_rate|fx_rate|get_fx_rate|fx_get_rate|convert_currency|currency_convert|currency_latest|fx_rates|exchange_rates)$'},
    'weather.forecast.v1': {'tools': r'^(?:get_forecast|weather_forecast|get_weather|forecast|weather|current_weather|get_weather_forecast)$'},
    'events.search.v1': {'tools': r'^(?:search_events|find_events|events_search|festivals\w*|concerts\w*)$'},
    'software.incident.v1': {'tools': r'^(?:latest_incidents|search_incidents|get_security_incidents|breach_history|search_public_cve_records|search_cves|incident_search)$'},
    'website.ai_readiness.v1': {'tools': r'^(?:check_ai_readiness|check_agent_readiness|check_ai_search_readiness|website_ai_readiness|audit_ai_readiness|ai_crawler_check|check_llms_txt|test_robots_txt|grade_website|robots_txt_check|scan_site|sitemap_urls|check_ai_crawlers?|check_ai_crawler_access|ai_crawler_audit|check_store_ai_readiness|check_clinic_website_ai_readiness)$'},
    'package.risk.v1': {'tools': r'^(?:\w*openssf_scorecard\w*|get_scorecard|repo_scorecard|get_repo_scorecard|package_risk|check_package_risk)$',
                        'input': {'repo': 'github.com/facebook/react', 'repository': 'github.com/facebook/react', 'package': 'react', 'ecosystem': 'npm'},
                        'checks': [('react named', r'react'), ('a score', r'score')]},
    # PM 11-15 16:13: website and domain checks (demand: website monitoring 60, DNS and mail auth 28 in our records)
    'dns.mail_auth.v1': {'tools': r'^(?:dns_lookup|dns-lookup|lookup_dns|check_dns|dns_records|get_dns_records|domain_dns|'
                                  r'check_spf|spf_check|check_dmarc|dmarc_check|check_dkim|dkim_check|check_email_auth\w*|'
                                  r'email_auth\w*|dossier_(?:dns|spf|dmarc|dkim))$',
                         'input': {'domain': 'python.org', 'record_type': 'TXT', 'type': 'TXT'},
                         'checks': [('domain echoed', r'python\.org'), ('an SPF or DMARC record', r'v=spf1|v=dmarc1|\bspf\b|\bdmarc\b')]},
    'tls.certificate.v1': {'tools': r'^(?:check_ssl|ssl_check|ssl-cert|ssl_cert\w*|check_certificate|check_tls_certificate|'
                                    r'verify_certificate|get_certificate|get_ssl_certificate|check_tls_configuration|tls_check|'
                                    r'dossier_tls|devops_check_certs)$',
                           'input': {'domain': 'python.org', 'host': 'python.org', 'hostname': 'python.org', 'url': 'https://python.org'},
                           'checks': [('domain echoed', r'python\.org'),
                                      ('issuer or expiry', r'issuer|expir|not ?after|valid (?:until|to)|globalsign|sectigo|digicert|let.?s encrypt')]},
    # Contracts the agent team proposed for the library-usage necklace (PM 11-15 16:12: ab205afc, a36293e8)
    'package.releases.v1': {'tools': r'^(?:get_package_releases|package_releases|npm_releases|get_package_versions|'
                                     r'package_versions|list_package_versions|get_latest_version|latest_version|'
                                     r'get_package_changelog|package_changelog|read_package_info|package_status)$',
                            'input': {'package': 'lodash', 'ecosystem': 'npm'},
                            'checks': [('lodash named', r'lodash'), ('a version', r'\b\d+\.\d+\.\d+\b')]},
    'github.releases.v1': {'tools': r'^(?:github_releases|get_github_releases|list_github_releases|extract_changelog|depwatch_preview|list_project_release_notes|repo_releases|get_repo_releases)$',
                           'input': {'repo': 'psf/requests', 'repository': 'https://github.com/psf/requests'},
                           'checks': [('requests named', r'requests'), ('a version', r'\bv?\d+\.\d+(?:\.\d+)?\b')]},
    'mcp.registry.lookup.v1': {'tools': r'^(?:search_mcp_servers|search_mcp_registry|mcp_registry\w*|find_mcp_servers|'
                                        r'get_mcp_server|lookup_mcp_server|registry_search)$',
                               'input': {'name': 'biz.agentconcierge/agent-concierge', 'query': 'agent concierge'},
                               'checks': [('agent concierge named', r'agent.?concierge')]},
    # RAG default-check roles (11-14): public answers, checked with fields and words
    'domain.lookup.v1': {'tools': r'^(?:whois_lookup|rdap_lookup|domain_whois|lookup_domain|domain_info|check_domain|domain_lookup|lookup_domain_whois|whois_domain)$',
                         'input': {'domain': 'python.org'},
                         'checks': [('domain echoed', r'python\.org'),
                                    ('registrar or a date', r'registrar|created|creation|registered|expir|\b(?:19|20)\d{2}-\d{2}-\d{2}')]},
    'place.search.v1': {'tools': r'^(?:search_places|find_places|get_place|place_search|search_poi\w*|geocode_place)$',
                        'input': {'query': 'Eiffel Tower'},
                        'checks': [('Paris', r'paris'), ('address or coordinates', r'48\.85|2\.29|champ|avenue|address|latitude|"lat')]},
    'book.search.v1': {'tools': r'^(?:search_books|book_search|openlibrary_search|lookup_book|find_books)$',
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
    'stock.quote.v1': {'tools': r'^(?:get_stock_quote|stock_quote|get_stock_price|quote_stock|get_ticker_snapshot|get_stock_snapshot|get_stock|stock_price)$',
                       'input': {'symbol': 'AAPL', 'ticker': 'AAPL'},
                       'checks': [('AAPL named', r'\baapl\b|apple'), ('USD or a price field', r'\busd\b|\$|price|close|last'),
                                  ('a time stamp', r'\b(?:19|20)\d{2}-\d{2}-\d{2}|\b\d{1,2}:\d{2}|timestamp|updated|as of|"time')],
                       'live': {'reference': 'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d', 'tolerance': 0.02,
                                'terms_ok': False, 'note': 'Yahoo chart endpoint is unofficial and for personal use'}},
    'geocode.address.v1': {'tools': r'^(?:geocode|geocode_address|address_to_coordinates|forward_geocode|search_address|find_address)$',
                           'input': {'address': '1600 Pennsylvania Avenue NW, Washington, DC', 'query': '1600 Pennsylvania Avenue NW, Washington, DC'},
                           'checks': [('latitude 38.89', r'38\.89'), ('longitude -77.03', r'-77\.0[34]')]},
    'ip.lookup.v1': {'tools': r'^(?:ip_lookup|lookup_ip|ip_info|get_ip_info|geoip_lookup|ip_geolocation|lookup_ip_location|check_ip)$',
                     'input': {'ip': '8.8.8.8', 'ip_address': '8.8.8.8', 'query': '8.8.8.8'},
                     'checks': [('8.8.8.8 echoed', r'8\.8\.8\.8'), ('Google or AS15169', r'google|15169')]},
    'timezone.time.v1': {'tools': r'^(?:convert_timezone|get_current_time|current_time|time_now|world_clock|timezone_time|get_local_time|time_by_coordinates)$',
                         'input': {'timezone': 'America/New_York', 'tz': 'America/New_York', 'city': 'New York', 'location': 'New York'},
                         'checks': [('a clock time', r'\b\d{1,2}:\d{2}'), ('zone named', r'new.?york|america/new_york|\be[sd]t\b|utc-0?[45]|-0[45]:00')]},
    'dictionary.define.v1': {'tools': r'^(?:define_word|dictionary_lookup|word_definition|get_definition|lookup_dictionary_entry|dictionary_define)$',
                             'input': {'word': 'serendipity', 'term': 'serendipity', 'query': 'serendipity'},
                             'checks': [('word echoed', r'serendipity'), ('a definition', r'chance|accident|fortunate|luck|unexpected')]},
    'translate.text.v1': {'tools': r'^(?:translate\.text|translate_lines|translator|translate_english_text|translate_text|translate|text_translate|localize_text)$',
                          'input': {'text': 'Good morning', 'target': 'fr', 'target_language': 'fr', 'target_lang': 'fr', 'to': 'fr'},
                          'checks': [('French greeting', r'bonjour')]},
    'github.repo.v1': {'tools': r'^(?:get_repo|get_repository|repo_info|search_repositories|search_repos|github_repo\w*|get_github_repo|repo_health_check)$',
                       'input': {'repo': 'facebook/react', 'repository': 'facebook/react', 'owner': 'facebook', 'name': 'react', 'query': 'react'},
                       'checks': [('react named', r'facebook/react|\breact\b'), ('license or stars', r'\bmit\b|stars?|stargazers')]},
    'holiday.calendar.v1': {'tools': r'^(?:get_public_holidays|public_holidays|holiday_calendar|get_holidays|holidays_list|get_next_public_holidays|list_public_holidays|list_federal_holidays)$',
                            'input': {'country': 'US', 'country_code': 'US', 'countryCode': 'US', 'year': 2026},
                            'checks': [('Independence Day', r'independence day|2026-07-0[34]'), ('Thanksgiving', r'thanksgiving')]},
    'sec.filings.v1': {'tools': r'^(?:get_sec_filings|sec_filings|company_filings|get_company_filings|get_latest_filings|edgar_filings|search_sec_filings|search_sec_edgar|get_filings|list_filings)$',
                       'input': {'ticker': 'AAPL', 'cik': '320193', 'company': 'Apple Inc', 'query': 'Apple'},
                       'checks': [('Apple or CIK 320193', r'apple|320193'), ('a form type', r'10-k|10-q|8-k')]},
    'airport.lookup.v1': {'tools': r'^(?:lookup_airport|get_airport(?:_info)?|airport_lookup|airport_info|search_airports|find_airports?)$',
                          'input': {'code': 'ICN', 'iata': 'ICN', 'iata_code': 'ICN', 'query': 'ICN'},
                          'checks': [('Incheon', r'incheon')]},
    'unit.convert.v1': {'tools': r'^(?:convert_units|unit_convert|convert_measurement|calc_units)$',
                        'input': {'value': 10, 'amount': 10, 'from': 'mile', 'to': 'kilometer', 'from_unit': 'mile', 'to_unit': 'kilometer'},
                        'checks': [('16.09', r'16\.09')]},
    'earthquake.feed.v1': {'tools': r'^(?:get_earthquakes|earthquakes|recent_earthquakes|usgs_earthquakes|search_earthquakes|earthquake_feed|earthquake_search_events)$',
                           'input': {'min_magnitude': 5, 'minmagnitude': 5, 'magnitude': 5},
                           'checks': [('magnitude', r'\bmag'), ('M5 or more', r'\b[5-9]\.\d\b')]},
    # Pearl scout W3 review (검색과 RAG with the workflow team, PM 11-17): roles a necklace draft or plan uses
    # (company-sanctions-screen, regulation-brief cases, cve-incident-brief v2, website-trust v2, entity checks);
    # tool names narrowed from Antigravity's patterns after reading the grade A snapshot; tasks in role-tasks-rag-v1.
    'sanctions.screen.v1': {'tools': r'^(?:screen_sanctions(?:_name)?|screen_restricted_party|check_sanctions(?!_wallet)\w*|search_sanctions\w*|sanctions_(?:screen|search|check)(?!.*_preview$)\w*|ofac_(?:search|screen|check)(?!.*_preview$)\w*)$'},
    'court.case.v1': {'tools': r'^(?:search_case_law|search_court_cases|get_case_brief|courtlistener_(?:search_opinions|get_opinion|lookup_citation|get_citations))$'},
    'cve.epss.v1': {'tools': r'^(?!get_epss_movers$)(?:get_epss\w*|epss_\w+|check_epss\w*|exploit_probability\w*)$'},
    'http.headers.v1': {'tools': r'^(?:check_security_headers|security_headers\w*|inspect_security_headers|http_security_headers\w*|analyze_security_headers)$'},
    'email.deliverability.v1': {'tools': r'^(?:check_mx\w*|mx_lookup\w*|check_email_deliverability)$'},
    'wikidata.entity.v1': {'tools': r'^(?:wikidata_search_entities|wikidata_get_entity|wikidata_get_labels|get_entity_profile)$'},
    # Contracts our own substitutes fill (PM 11-17 22:2x: the one list must name every contract). None has a role task
    # or default checks yet, so a pearl test would judge it on nothing: NEVER (matches no tool name) keeps them out of
    # the pearl queue until a role task with public answers is written; then give the role a real pattern.
    # agent.record.v1 is our own record of an agent, so it has no outside member at all.
    'docs.readme.v1': {'tools': NEVER, 'queue': 'blocked: no role task yet (package README, npm/PyPI)'},
    'sun.times.v1': {'tools': NEVER, 'queue': 'blocked: no role task yet (computed by our substitute)'},
    'site.reachability.v1': {'tools': NEVER, 'queue': 'blocked: no role task yet (one HTTPS GET by our substitute)'},
    'agent.record.v1': {'tools': NEVER, 'queue': 'never: our own record, no outside member'},
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
