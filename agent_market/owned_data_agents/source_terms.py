"""Source licenses and suspensions of the owned data agents (PM 11-15 16:52 and 17:02).

Kept out of catalog.py, engine.py and dispatch.py on purpose: those files are hashed whole into the research/news
adapter digest (owned_capability_adapter.IMPLEMENTATION) that saved workflows and contract evidence pin, and dispatch.py
is also in the registered SQL file list. Licenses are "name (https address)", or None when no license was found
(never invented). Verdicts with their sources are in agent_market/necklaces/member_terms.json and
reports/necklace-terms-2026-11-15/README.md.
"""

LICENSES = {
    # 133018: YC Terms of Use forbid commercial display and redistribution without authorization; no data license found
    'technology-news': None,
    'research-papers': ('Bibliographic metadata: facts not subject to copyright; Crossref-generated data CC0 '
                        '(https://www.crossref.org/documentation/retrieve-metadata/)'),
    'country-profile': 'CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses#cc-by)',
    'package-metadata': ('npm Open-Source Terms (https://docs.npmjs.com/policies/open-source-terms); '
                         'metadata as published by package authors'),
    'economic-indicators': 'CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses#cc-by)',
    'package-advisories': ("Each advisory under its source's license as listed by OSV; npm advisories from the GitHub "
                           'Advisory Database are CC BY 4.0 (https://google.github.io/osv.dev/data/)'),
    'github-issues': ('Public issue metadata under the GitHub Terms of Service, API Terms '
                      '(https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms); '
                      "each issue's text stays with its author"),
    # Context7 is no longer called (its Addendum allows internal development, educational and evaluation use only)
    'technical-docs': ('MDN Web Docs: CC BY-SA 2.5, Mozilla Contributors '
                       '(https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Attrib_copyright_license)'),
}

# Agents taken down until their source can be replaced: the public endpoint answers tools/call with this notice and
# calls no source. tools/list stays the same so the registered definition does not change.
SUSPENDED = {
    'technology-news': ('This agent is suspended: the terms of its data source (Hacker News) do not allow reuse here. '
                        'No source was called.'),
}
