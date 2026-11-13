"""Fallback agents, the necklace contract each one fills, and their public sources.

Input and output schemas are the necklace slot contracts themselves
(``agent_market/necklaces/contracts``), so a fallback answer can stand in a slot
without any mapping. Each agent publishes exactly one read-only tool.
"""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parent.parent / "necklaces" / "contracts"
USER_AGENT = "AgentValCon-FallbackAgents/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)"

NVD = {"name": "NVD (National Vulnerability Database), NIST", "url": "https://nvd.nist.gov/",
       "license": "U.S. Government work, not subject to copyright in the United States",
       "notice": "This product uses data from the NVD API but is not endorsed or certified by the NVD."}
CVE_ORG = {"name": "CVE Program (CVE Services API)", "url": "https://www.cve.org/",
           "license": "CVE Program Terms of Use (https://www.cve.org/Legal/TermsOfUse)",
           "notice": "CVE is a registered trademark of The MITRE Corporation. Record content is "
                     "provided by the assigning CNA and ADPs."}
KEV = {"name": "CISA Known Exploited Vulnerabilities Catalog",
       "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
       "license": "U.S. Government work (CISA), public domain in the United States",
       "notice": "A CVE absent from the catalog is not known to CISA as exploited; it is not a safety claim."}
EPSS = {"name": "FIRST EPSS", "url": "https://www.first.org/epss/",
        "license": "Free to use with attribution to FIRST (https://www.first.org/epss/)",
        "notice": "EPSS is a probability of exploitation activity in the next 30 days, not a severity score."}
GHSA = {"name": "GitHub Advisory Database", "url": "https://github.com/advisories",
        "license": "CC BY 4.0 (https://github.com/github/advisory-database)",
        "notice": "Reviewed advisories only. An empty list means no reviewed advisory matched; "
                  "it is not a security guarantee."}

NPM = {"name": "npm public registry", "url": "https://registry.npmjs.org/",
       "license": "npm Open-Source Terms (https://docs.npmjs.com/policies/open-source-terms); "
                  "metadata as published by package authors",
       "notice": "Registry facts only; no scripts, maintainers or emails are returned."}
PYPI = {"name": "PyPI JSON API", "url": "https://pypi.org/",
        "license": "PyPI Terms of Use (https://policies.python.org/pypi.org/Terms-of-Use/); "
                   "metadata as published by package authors",
        "notice": "PyPI has no deprecation flag: deprecated=true only for a yanked release or an "
                  "'Inactive' development status; otherwise the field is left out."}
DEPSDEV = {"name": "Open Source Insights (deps.dev), Google", "url": "https://deps.dev/",
           "license": "Generated data CC BY 4.0; API use under the Google APIs Terms of Service "
                      "(https://docs.deps.dev/api/v3/)",
           "notice": "The scorecard value is the OpenSSF Scorecard aggregate as served by deps.dev, with its date."}

GLEIF = {"name": "GLEIF LEI records (Global Legal Entity Identifier Foundation)", "url": "https://www.gleif.org/",
         "license": "CC0 1.0 (GLEIF LEI data, https://www.gleif.org/en/meta/lei-data-terms-of-use)",
         "notice": "Only an exact legal-name match is returned; several equal matches are reported as ambiguous, not guessed."}
SEC = {"name": "SEC EDGAR (U.S. Securities and Exchange Commission)", "url": "https://www.sec.gov/edgar",
       "license": "U.S. Government public data; SEC fair-access policy (declared User-Agent, at most 10 requests per second)",
       "notice": "Covers companies with SEC tickers. Not endorsed by the SEC."}

WIKIPEDIA = {"name": "Wikipedia (English), Wikimedia Foundation", "url": "https://en.wikipedia.org/",
             "license": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/); text by Wikipedia contributors",
             "notice": "Summary text is the article's lead section; reuse must credit Wikipedia contributors and "
                       "keep the CC BY-SA 4.0 license, with the article link given in url."}
ARXIV = {"name": "arXiv API (Cornell University)", "url": "https://arxiv.org/",
         "license": "arXiv metadata CC0 1.0 (https://info.arxiv.org/help/api/tou.html); paper texts keep their own licenses",
         "notice": "Thank you to arXiv for use of its open access interoperability. At most one request every 3 seconds."}

WORLDBANK = {"name": "World Bank Open Data (World Development Indicators)", "url": "https://data.worldbank.org/",
             "license": "CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses#cc-by)",
             "notice": "Source: World Bank, World Development Indicators. The latest value is the latest published "
                       "observation, not a current-year measurement."}

MET = {"name": "MET Norway Locationforecast 2.0 (Norwegian Meteorological Institute)", "url": "https://api.met.no/",
       "license": "CC BY 4.0 and NLOD 2.0 (https://api.met.no/doc/License); Data from MET Norway",
       "notice": "Model forecast for the given coordinates (rounded to 0.01 degree), not a station observation."}

HOLIDAYS = {"name": "holidays (Python library, Vacanza team)", "url": "https://github.com/vacanza/holidays",
            "license": "MIT (https://github.com/vacanza/holidays/blob/main/LICENSE)",
            "notice": "National public holidays only, computed offline from the library's published rules. "
                      "Festivals, concerts and other events are not covered; regional holidays are not included."}

SCORECARD = {"name": "OpenSSF Scorecard API", "url": "https://scorecard.dev/",
             "license": "CDLA-Permissive-2.0 (https://github.com/ossf/scorecard)",
             "notice": "Automated heuristic checks of the source repository, not a security audit."}

SITE = {"name": "The website's own public files (robots.txt, llms.txt, sitemap.xml)", "url": "https://www.rfc-editor.org/rfc/rfc9309",
        "license": "Facts read from the site's public files; no page content is copied",
        "notice": "The score is a simple AgentValCon heuristic over these files, not a search-engine ranking."}

SPECS = {
    "nvd-cve": {
        "name": "AgentValCon NVD CVE Record", "tool": "get_cve_record", "contract": "cve.record.v1",
        "description": "Look up one CVE in the NVD: CVSS score, version and vector, English description, "
                       "publication date and HTTPS references. Answers from a local NVD feed snapshot "
                       "refreshed every two hours; read-only.",
        "sources": [NVD],
        # NVD asks keyless clients for at most 5 requests per rolling 30 seconds.
        "rate": "NVD feeds: one download per 6.5 s; live API only for snapshot misses, 5 per 30 s",
    },
    "cve-org": {
        "name": "AgentValCon CVE.org Record", "tool": "get_cve_org_record", "contract": "cve.record.v1",
        "description": "Look up one CVE Record from the CVE Program: CNA or ADP CVSS score, English "
                       "description, release date and HTTPS references. Rejected records and IDs "
                       "without a record are not returned; read-only.",
        "sources": [CVE_ORG],
        "rate": "1 request per second, cached 6 hours",
    },
    "cisa-kev": {
        "name": "AgentValCon CISA KEV and EPSS", "tool": "check_kev", "contract": "cve.exploited.v1",
        "description": "Check whether one CVE is in the CISA Known Exploited Vulnerabilities catalog "
                       "(with the date it was added) and add its FIRST EPSS probability; read-only.",
        "sources": [KEV, EPSS],
        "rate": "KEV catalog: one download per hour; EPSS: 2 requests per second, cached 6 hours",
    },
    "github-advisory": {
        "name": "AgentValCon GitHub Advisories", "tool": "list_package_advisories",
        "contract": "package.advisories.v1",
        "description": "List reviewed GitHub Security Advisories that affect one npm or PyPI package "
                       "(optionally an exact version), with aliases, severity and affected range; read-only.",
        "sources": [GHSA],
        # Unauthenticated GitHub REST allows 60 requests per hour per address.
        "rate": "at most 50 requests per hour, cached 1 hour",
    },
    "package-registry": {
        "name": "AgentValCon Package Registry Facts", "tool": "get_package_release",
        "contract": "package.health.v1",
        "description": "Read the latest version of one npm or PyPI package straight from its public "
                       "registry: version, deprecation or yanked flag, source repository, and the "
                       "release time on PyPI; read-only.",
        "sources": [NPM, PYPI],
        "rate": "5 requests per second per registry, cached 1 hour",
    },
    "depsdev-package": {
        "name": "AgentValCon deps.dev Package Health", "tool": "get_package_scorecard",
        "contract": "package.health.v1",
        "description": "Look up one npm or PyPI package in Open Source Insights (deps.dev): default "
                       "version and its release time, deprecation, source repository and the OpenSSF "
                       "Scorecard aggregate; read-only.",
        "sources": [DEPSDEV],
        "rate": "5 requests per second, cached 6 hours",
    },
    "gleif-lei": {
        "name": "AgentValCon GLEIF LEI Lookup", "tool": "find_lei_record", "contract": "company.registry.v1",
        "description": "Find the Legal Entity Identifier (LEI) record of one company by its exact legal "
                       "name (optional ISO country): legal name, LEI, company number, entity and LEI status "
                       "and city; read-only.",
        "sources": [GLEIF],
        "rate": "1 request per second (GLEIF allows 60 per minute), cached 6 hours",
    },
    "sec-edgar": {
        "name": "AgentValCon SEC EDGAR Company", "tool": "find_sec_company", "contract": "company.registry.v1",
        "description": "Find one SEC filer with a stock ticker by its name: legal name, SEC CIK, tickers, "
                       "exchange, filer category and business city from EDGAR; read-only.",
        "sources": [SEC],
        "rate": "at most 5 requests per second (SEC allows 10); ticker list cached 24 hours",
    },
    "wikipedia-summary": {
        "name": "AgentValCon Wikipedia Summary", "tool": "get_wikipedia_summary", "contract": "encyclopedia.summary.v1",
        "description": "Read the lead section of one English Wikipedia article by title (redirect titles resolve; "
                       "disambiguation pages are not answered), with the article link and CC BY-SA attribution; read-only.",
        "sources": [WIKIPEDIA],
        "rate": "5 requests per second, cached 6 hours",
    },
    "arxiv-search": {
        "name": "AgentValCon arXiv Search", "tool": "search_arxiv_papers", "contract": "papers.search.v1",
        "description": "Search arXiv for papers matching keywords: title, arXiv id, abstract link and year, "
                       "ranked by how many query words the title holds; read-only.",
        "sources": [ARXIV],
        "rate": "1 request every 3 seconds (arXiv API terms), cached 24 hours",
    },
    "worldbank-indicator": {
        "name": "AgentValCon World Bank Country Indicator", "tool": "get_country_indicator",
        "contract": "country.indicator.v1",
        "description": "Get one World Bank indicator value for a country (ISO2 or ISO3) and an optional year: "
                       "common names such as population, gdp, gdp per capita, gdp growth, inflation, "
                       "unemployment, life expectancy, area or capital, or a World Bank indicator code; "
                       "states the year and unit; read-only.",
        "sources": [WORLDBANK],
        "rate": "5 requests per second, cached 6 hours",
    },
    "met-weather": {
        "name": "AgentValCon MET Norway Weather", "tool": "get_weather_forecast", "contract": "weather.forecast.v1",
        "description": "Get the current-hour temperature and a short forecast for any latitude and longitude "
                       "worldwide from MET Norway Locationforecast; read-only.",
        "sources": [MET],
        "rate": "under 20 requests per second; a place is asked again only after the source's Expires time",
    },
    "public-holidays": {
        "name": "AgentValCon National Public Holidays", "tool": "list_public_holidays", "contract": "events.search.v1",
        "description": "List the national public holidays of one country (place = country name or ISO code) for a "
                       "year and optional month, optionally filtered by words in the holiday name. National public "
                       "holidays only: no festivals, concerts or local events; read-only.",
        "sources": [HOLIDAYS],
        "rate": "no network calls; rules ship with the pinned library version",
    },
    "holiday-calendar": {
        "name": "AgentValCon National Holiday Calendar", "tool": "get_holidays", "contract": "holiday.calendar.v1",
        "description": "List the national public holidays of one country (ISO code or English name) for a year, "
                       "with dates. National public holidays only: no festivals or local events; read-only.",
        "sources": [HOLIDAYS],
        "rate": "no network calls; rules ship with the pinned library version",
    },
    "sec-filings": {
        "name": "AgentValCon SEC EDGAR Filings", "tool": "list_sec_filings", "contract": "sec.filings.v1",
        "description": "List the recent EDGAR filings (form type and date) of one SEC filer by ticker, CIK or exact "
                       "company name, with the periodic and current reports picked out; read-only.",
        "sources": [SEC],
        "rate": "at most 5 requests per second (SEC allows 10); cached 1 hour",
    },
    "software-incident": {
        "name": "AgentValCon Advisory Fix Lookup", "tool": "find_fix_guidance", "contract": "software.incident.v1",
        "description": "Find reviewed security advisories for a CVE id or an exact package name, with the first "
                       "fixed version and the advisory link, shown as data only; read-only.",
        "sources": [GHSA, NVD],
        "rate": "GitHub: at most 50 requests per hour, cached 1 hour; NVD from the local snapshot",
    },
    "scorecard": {
        "name": "AgentValCon OpenSSF Scorecard", "tool": "get_scorecard", "contract": "package.risk.v1",
        "description": "Get the OpenSSF Scorecard aggregate and lowest checks for a GitHub repository, or for an npm "
                       "or PyPI package through its listed source repository; read-only.",
        "sources": [SCORECARD],
        "rate": "5 requests per second, cached 6 hours",
    },
    "site-readiness": {
        "name": "AgentValCon Website Agent Readiness", "tool": "check_site_files", "contract": "website.ai_readiness.v1",
        "description": "Read one public website's robots.txt, llms.txt and sitemap.xml: whether they exist, which AI "
                       "crawlers robots.txt allows or blocks, and a simple readiness score; read-only.",
        "sources": [SITE],
        "rate": "0.3 s apart and at most 30 a minute per website, cached 6 hours; files robots.txt disallows are not read",
    },
}


@lru_cache(maxsize=None)
def _contract(contract_id: str) -> dict:
    return json.loads((CONTRACTS / f"{contract_id}.json").read_text(encoding="utf-8"))


def contract(contract_id: str) -> dict:
    return deepcopy(_contract(contract_id))


def tool_spec(agent_id: str) -> dict:
    spec = SPECS[agent_id]
    c = _contract(spec["contract"])
    return deepcopy({"name": spec["tool"], "description": spec["description"],
                     "inputSchema": c["input_schema"], "outputSchema": c["output_schema"],
                     "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                     "idempotentHint": True, "openWorldHint": True}})
