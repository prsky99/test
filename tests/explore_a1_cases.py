"""Fixed, reviewable task judgments; 10 intents, 200 surface-form queries."""

import json
from agent_market.collector.usage import compact_tools
from agent_market.capability_registry import digest

TASKS = (
    (
        "weather forecast",
        "Weather Forecast",
        "Get worldwide weather forecast and temperature for any city.",
        "get_weather_forecast",
    ),
    (
        "text translation",
        "Text Translation",
        "Translate text and documents between languages.",
        "translate_text",
    ),
    (
        "github issues",
        "GitHub Issues",
        "Search GitHub issues and pull requests in repositories.",
        "search_github_issues",
    ),
    (
        "technology news",
        "Technology News",
        "Search technology news and artificial intelligence stories.",
        "search_technology_news",
    ),
    (
        "research papers",
        "Research Papers",
        "Search academic research papers and scholarly articles.",
        "search_research_papers",
    ),
    (
        "currency exchange rate",
        "Currency Exchange Rate",
        "Get currency exchange rates and forex market data.",
        "get_currency_exchange_rate",
    ),
    (
        "stock price quotes",
        "Stock Price Quotes",
        "Get stock market prices and equity ticker quotes for listed companies.",
        "get_stock_price_quotes",
    ),
    (
        "audio transcription",
        "Audio Transcription",
        "Transcribe audio and speech recordings into text.",
        "transcribe_audio",
    ),
    (
        "pdf extraction",
        "PDF Extraction",
        "Extract structured text and tables from PDF documents using OCR.",
        "extract_pdf",
    ),
    (
        "python documentation",
        "Python Documentation",
        "Search Python library documentation and API references.",
        "search_python_documentation",
    ),
)
PREFIXES = (
    "",
    "Find ",
    "Please find ",
    "I need ",
    "Show me ",
    "Search for ",
    "Recommend ",
    "Looking for ",
    "Find agents for ",
    "Find a service for ",
)
CASES = tuple(
    {
        "case_id": f"a1-{index:02}-{prefix_index:02}-{ending_index}",
        "query": prefix + task[0] + ending,
        "task": index,
        "expected_match": True,
        "unrelated_expected_match": False,
    }
    for index, task in enumerate(TASKS)
    for prefix_index, prefix in enumerate(PREFIXES)
    for ending_index, ending in enumerate(("", "."))
)


def listing(index, *, large=False):
    task, name, description, tool_name = TASKS[index]
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    if large:
        schema["properties"]["query"]["description"] = "Schema documentation. " * 500
    tools = [
        {
            "name": tool_name,
            "description": description,
            "inputSchema": schema,
            "annotations": {"readOnlyHint": True},
        }
    ]
    return {
        "id": index + 1,
        "kind": "mcp",
        "name": name,
        "description": description,
        "url": f"https://a1-{index}.example/mcp",
        "category": "general",
        "active": 1,
        "health_status": "healthy",
        "eval_security": "ok",
        "auth_observed": 0,
        "usage_tools": json.dumps(compact_tools(tools)),
        "usage_full_tools": json.dumps(tools),
        "usage_full_hash": digest(tools),
        "usage_guide": "{}",
    }
