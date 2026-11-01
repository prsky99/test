"""Read-only operator additions for every category in the public workflow hub."""

from copy import deepcopy

from .owned_data_agents.catalog import SPECS
from .owned_data_agents.service import PREFIX
from .owned_data_agents.staging import origin
from .workflow_templates import agent

VERSION = "operator-category-templates-v1"
CATEGORY_NAMES = {
    "travel_maps_weather": "Travel & Weather",
    "dev_tools": "Developer Tools",
    "data_utility": "Data & Utility",
    "finance_crypto": "Finance & DeFi",
    "automation": "Automation",
    "sports_health": "Sports & Health",
    "business_productivity": "Productivity",
    "docs_knowledge": "Docs & Knowledge",
}


def definitions(base_url="https://agentconcierge.biz"):
    base_url = origin(base_url)

    def node(nid, identity, label, arguments):
        value = agent(
            nid,
            label,
            base_url + PREFIX + "/" + identity + "/mcp",
            SPECS[identity]["tool"],
            arguments,
            {"path": "content.0.text", "max_text": 12000},
            1,
        )
        value["data"]["operator_agent_id"] = identity
        return value

    def ref(parent, field):
        return "{{$node['" + parent + "'].output.structuredContent.data." + field + "}}"

    def country(nid, code):
        return node(
            nid, "country-profile", code + " Country Profile", {"country_code": code}
        )

    def metric(nid, parent, code, label):
        return node(
            nid,
            "economic-indicators",
            label,
            {
                "country_code": ref(parent, "country_code"),
                "indicator": code,
                "limit": 3,
            },
        )

    def papers(nid, query, label):
        return node(nid, "research-papers", label, {"query": query, "limit": 3})

    def news(nid, query, label):
        return node(nid, "technology-news", label, {"query": query, "limit": 3})

    def package(nid, name):
        return node(
            nid, "package-metadata", name + " Release Metadata", {"package": name}
        )

    def advisories(nid, parent):
        return node(
            nid,
            "package-advisories",
            "Exact-Version Security Advisories",
            {
                "package": ref(parent, "package"),
                "version": ref(parent, "version"),
                "limit": 3,
            },
        )

    recipes = [
        (
            "destination-country-research",
            "Destination Country & Tourism Research",
            "travel_maps_weather",
            "Prepare a Japan destination brief with official country facts and cited sustainable-tourism research.",
            [
                country("country", "JP"),
                papers(
                    "tourism", "Japan sustainable tourism", "Tourism Research Records"
                ),
            ],
        ),
        (
            "destination-country-comparison",
            "Three-Destination Country Comparison",
            "travel_maps_weather",
            "Compare official Japan, South Korea and Singapore country names, capitals and regions before planning a multi-country trip.",
            [
                country("japan", "JP"),
                country("korea", "KR"),
                country("singapore", "SG"),
            ],
        ),
        (
            "accessible-travel-research",
            "Accessible Travel Evidence Pack",
            "travel_maps_weather",
            "Collect cited research on accessible tourism and public-transport accessibility for trip preparation. These are research records, not live access guarantees.",
            [
                papers(
                    "tourism",
                    "accessible tourism mobility",
                    "Accessible Tourism Studies",
                ),
                papers(
                    "transport",
                    "tourism public transport accessibility",
                    "Transport Accessibility Studies",
                ),
            ],
        ),
        (
            "macro-economic-context",
            "Annual Economic Context Brief",
            "finance_crypto",
            "Read official US GDP and population observations with source years. Annual statistics are separate from market quotes or investment advice.",
            [
                country("country", "US"),
                metric("gdp", "country", "NY.GDP.MKTP.CD", "GDP in Current USD"),
                metric(
                    "population", "country", "SP.POP.TOTL", "Population Observations"
                ),
            ],
        ),
        (
            "fintech-evidence",
            "Financial Technology Evidence Digest",
            "finance_crypto",
            "Combine technology-community reporting about fintech with bibliographic records on financial-technology risk. Original source links remain visible.",
            [
                news("news", "fintech", "Fintech Technology Stories"),
                papers("papers", "financial technology risk", "Fintech Risk Research"),
            ],
        ),
        (
            "financial-risk-research",
            "Financial Risk Research Board",
            "finance_crypto",
            "Build separate cited reading lists for financial-market risk models and bank stress testing without generating trading recommendations.",
            [
                papers(
                    "market", "financial market risk models", "Market Risk Research"
                ),
                papers("banking", "bank stress testing", "Bank Stress-Test Research"),
            ],
        ),
        (
            "release-signal-pipeline",
            "Package Release Security Evidence Pipeline",
            "automation",
            "Run a manual collection pipeline: resolve the current Vite version, check exact-version security advisories, and collect software supply-chain research with source links.",
            [
                package("package", "vite"),
                advisories("advisories", "package"),
                papers(
                    "references",
                    "JavaScript software supply chain security",
                    "Software Supply Chain Research",
                ),
            ],
        ),
        (
            "javascript-release-inventory",
            "JavaScript Toolchain Release Inventory",
            "automation",
            "Collect current TypeScript, ESLint and Vite release metadata into one manual inventory run. No package code is downloaded or executed.",
            [
                package("typescript", "typescript"),
                package("eslint", "eslint"),
                package("vite", "vite"),
            ],
        ),
        (
            "research-news-enrichment",
            "Research-to-News Enrichment Pipeline",
            "automation",
            "Find workflow-automation research, forward the reviewed topic into technology-story search, and retrieve current workflow-automation package metadata in one manual run.",
            [
                papers(
                    "research", "workflow automation", "Workflow Automation Research"
                ),
                news("news", ref("research", "query"), "Matching Technology Stories"),
                package("tool", "n8n"),
            ],
        ),
        (
            "population-health-context",
            "Population Health Context Brief",
            "sports_health",
            "Read official US population and life-expectancy observations with their source years. Aggregate statistics do not provide personal medical guidance.",
            [
                country("country", "US"),
                metric(
                    "life", "country", "SP.DYN.LE00.IN", "Life Expectancy Observations"
                ),
                metric(
                    "population", "country", "SP.POP.TOTL", "Population Observations"
                ),
            ],
        ),
        (
            "longevity-comparison",
            "Two-Country Longevity Comparison",
            "sports_health",
            "Collect Japan and US country profiles and latest available life-expectancy records. Compare source years; this workflow does not infer causes.",
            [
                country("japan", "JP"),
                metric(
                    "japan_life", "japan", "SP.DYN.LE00.IN", "Japan Life Expectancy"
                ),
                country("us", "US"),
                metric("us_life", "us", "SP.DYN.LE00.IN", "US Life Expectancy"),
            ],
        ),
        (
            "sports-science-reading",
            "Sports Science Reading Pack",
            "sports_health",
            "Collect bibliographic records about exercise recovery and wearable-activity validation. Review the studies before making health or training decisions.",
            [
                papers(
                    "recovery",
                    "exercise recovery meta analysis",
                    "Exercise Recovery Research",
                ),
                papers(
                    "wearables",
                    "wearable physical activity validation",
                    "Wearable Validation Research",
                ),
            ],
        ),
        (
            "technology-meeting-brief",
            "Technology Meeting Research Brief",
            "business_productivity",
            "Prepare public background reading for an AI-governance meeting using technology stories and cited research. No invitations or messages are sent.",
            [
                news(
                    "news",
                    "artificial intelligence regulation",
                    "AI Regulation Technology Stories",
                ),
                papers(
                    "papers",
                    "artificial intelligence governance",
                    "AI Governance Research",
                ),
            ],
        ),
        (
            "frontend-evaluation-pack",
            "Frontend Technology Evaluation Pack",
            "business_productivity",
            "Collect React release metadata, exact-version security advisories and related technology stories before a team evaluation.",
            [
                package("package", "react"),
                advisories("advisories", "package"),
                news("news", ref("package", "package"), "React Technology Stories"),
            ],
        ),
        (
            "startup-background-pack",
            "Startup Market Background Pack",
            "business_productivity",
            "Collect US country facts, annual GDP records, startup technology stories and cited startup-survival research as a meeting preparation pack.",
            [
                country("country", "US"),
                metric("gdp", "country", "NY.GDP.MKTP.CD", "Annual GDP Records"),
                news("news", "startup", "Startup Technology Stories"),
                papers("papers", "startup survival", "Startup Survival Research"),
            ],
        ),
        (
            "knowledge-base-research",
            "Knowledge Base Research Pack",
            "docs_knowledge",
            "Build separate cited reference lists for retrieval-augmented generation, knowledge-graph retrieval and information-retrieval evaluation.",
            [
                papers(
                    "rag", "retrieval augmented generation", "RAG Reference Records"
                ),
                papers(
                    "graphs", "knowledge graph retrieval", "Knowledge Graph References"
                ),
                papers(
                    "evaluation",
                    "information retrieval evaluation",
                    "Retrieval Evaluation References",
                ),
            ],
        ),
        (
            "software-licensing-reference",
            "Software Licensing Reference Pack",
            "docs_knowledge",
            "Retrieve React and Lodash registry license metadata and cited open-source licensing research. Registry labels are references, not a legal compliance decision.",
            [
                package("react", "react"),
                package("lodash", "lodash"),
                papers(
                    "papers",
                    "open source software licensing",
                    "Licensing Research References",
                ),
            ],
        ),
    ]
    result = []
    for slug, name, category, description, nodes in recipes:
        trigger = {
            "id": "start",
            "type": "trigger",
            "kind": "trigger",
            "name": "Manual Trigger",
            "position": {"x": 60, "y": 160},
            "data": {},
        }
        for i, n in enumerate(nodes, 1):
            n["position"] = {"x": 60 + 280 * i, "y": 160}
        result.append(
            {
                "seed_key": VERSION + ":" + slug,
                "name": name,
                "description": "Operator-provided workflow: " + description,
                "category": category,
                "trigger_type": "manual",
                "is_active": 1,
                "is_template": 0,
                "author": "Agent Concierge Operations",
                "rating_avg": 0,
                "tags": "operator-provided,read-only," + slug,
                "nodes": [trigger, *nodes],
                "edges": [
                    {
                        "id": "edge-" + str(i),
                        "source": left["id"],
                        "target": right["id"],
                    }
                    for i, (left, right) in enumerate(zip([trigger, *nodes], nodes))
                ],
            }
        )
    return deepcopy(result)
