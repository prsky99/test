"""API 키 없이 동작하는 키워드 기반 카테고리 분류기 (영어·한국어, 14개 주제).

설명에 등장한 주제별 키워드 수로 점수를 매겨 가장 높은 주제를 고른다. 동점이면 더 구체적인 주제가 이긴다
(PRIORITY 순서). "for AI agents"처럼 거의 모든 설명에 붙는 일반어는 AI 모델 주제의 키워드로 쓰지 않는다.
"""

import re

from ..broker.categories import CATEGORIES

OTHER = "other"
VERSION = 10  # 10(2026-10-31): 도구 설명이 8,000자 넘는 공통 묶음이면 이름·설명이 판단(묶음이 설명을 덮어 Twilio가 docs_knowledge가 되던 문제), 보안 권고(osv) 추가. 모든 목록에 설명 우선·가중치를 주거나 식별자 낱말을 빼면 20% 표본 변경이 439→1,300~2,700건으로 늘고 품질이 섞여 채택 안 함. 9(2026-10-31): 날씨는 단독 "forecast" 대신 날씨 전용 낱말(weather forecast, hurricane, nws, noaa 등)로 판단, 예측 시장 "forecast"는 금융. 2026-10-27: 결제 방식 설명 문장 제외·날씨 예보 어휘 추가는 버전을 올리지 않음 (저장된 분류 일괄 갱신은 별도 승인 후 9로). 키워드가 바뀌면 올린다 → 저장된 에이전트를 다시 분류 (3: agent_infra 추가, 4: A2A는 스킬 포함,
#              5: agent_infra 약한 표현·제외 문맥, 6: 20개 카테고리 확장, 7: A2A 도구 추출 강화 및 고빈도 도메인 어휘 대폭 확충)

KEYWORDS: dict[str, list[str]] = {
    # 에이전트 인프라: 'agents', 'discovery', 'x402' 같은 일반어는 거의 모든 설명에 있어 쓰지 않고 구체적인 표현만 쓴다.
    # 가장 앞에 둬서 동점이면 이 주제가 이긴다. 약한 표현(INFRA_WEAK)과 제외 문맥(INFRA_BLOCK)은 아래 참고.
    # 535개 수동 판정(tests/data/agent_infra_labels.json)으로 키워드별 정확도를 재서 골랐다.
    "agent_infra": [
        "agent discovery", "discover agents", "discover ai agents", "find agents", "agent registry", "agent registries",
        "agent directory", "agent index", "agent catalog", "agent marketplace", "agents marketplace", "agent-to-agent",
        "agent to agent", "a2a gateway", "a2a registry", "a2a directory", "a2a marketplace", "agent card", "agent cards",
        "agent network", "agent economy", "agentic economy", "agent commerce",
        "mcp gateway", "mcp bridge", "mcp proxy", "mcp hub", "mcp registry", "mcp router", "mcp server discovery",
        "tool registry", "capability discovery", "capability registry",
        "agent orchestration", "multi-agent orchestration", "multi-agent", "multi agent", "agent swarm", "agent swarms",
        "agent coordination", "coordination layer", "coordination service", "agent handoff", "agent delegation",
        "agent identity", "agent identities", "agent reputation", "on-chain reputation", "reputation registry",
        "reputation oracle", "agent trust", "trust layer", "trust-layer", "trust registry", "trust engine", "agent attestation",
        "erc-8004 identity", "erc-8004 registry", "erc-8004 agents", "erc-8004 registration", "register your ai agent",
        "know your agent", "kya", "verifiable credential", "verifiable credentials", "agent negotiation",
        "agent matchmaking", "agent messaging", "agent inbox", "message board", "bulletin board",
        "agent hosting", "agent runtime", "agent observability", "agent monitoring", "agent health", "agent notary",
        "trust gate", "economic dry run", "dry-run simulator", "karma economy for ai agents", "reputation for ai agents",
        "agent memory", "agent payments", "agent router", "agent escrow", "agent governance", "agent due diligence",
        "due-diligence check on an agent", "trust badge", "agent dids", "task coordination", "task orchestration",
        "multi-agent settlement", "multi-agent consensus", "multi-agent escrow", "multi-agent governance",
        "multi-agent coordination", "multi-agent task", "hub for autonomous agents", "ai service discovery",
        "settlement and clearing layer", "settlement and clearing with validator consensus",
        "clearing layer with validator consensus",
        "에이전트 인프라", "에이전트 검색", "에이전트 등록", "에이전트 마켓", "오케스트레이션", "멀티 에이전트", "에이전트 평판", "에이전트 신원",
    ],
    "security": [
        "security", "vulnerability", "vulnerabilities", "cve", "threat", "threats", "malware", "pentest", "osint",
        "phishing", "exploit", "firewall", "osv", "security advisory", "security advisories", "보안", "취약점", "해킹", "악성코드",
    ],
    "health_science": [
        "health", "healthcare", "medical", "medicine", "clinical", "patient", "patients", "drug", "drugs", "pharma",
        "pharmaceutical", "disease", "diseases", "hospital", "doctor", "physician", "physicians", "genomics", "genome",
        "dna", "gene", "protein", "proteins", "biotech", "uniprot", "pubmed", "ncbi", "fda", "의료", "병원", "건강", "의약품",
        "환자", "생명과학", "유전자",
    ],
    "trading_derivatives": [
        "perp", "perps", "perpetual", "funding rate", "funding rates", "arbitrage", "orderbook", "order book", "deribit",
        "gex", "gamma exposure", "liquidation", "liquidations", "slippage", "long short ratio", "long/short", "spread",
        "bybit", "hyperliquid", "volatility regime", "atr", "cftc", "macro", "nasdaq", "s&p", "commodities", "commodity",
        "open-interest", "open interest", "yield curve", "crude oil", "gold spot", "futures", "ohlcv", "candle", "candles",
        "ticker", "tickers", "bbo", "order depth", "market depth", "vwap", "twap", "차트", "트레이딩", "무기한 선물", "펀딩비",
        "오더북", "차익거래", "청산", "변동성", "선물", "원자재",
    ],
    "network_ops": [
        "dns", "domain", "domains", "ssl", "tls", "certificate", "certificates", "whois", "ip lookup", "uptime",
        "icmp", "ping test", "ping latency", "traceroute", "nameserver", "port scan", "reverse dns", "host probe", "ipv6", "prefix", "http status",
        "latency", "asn", "bgp", "remote hop", "ip address", "도메인", "네트워크", "인증서", "핑", "서버 상태", "아이피", "대기시간",
    ],
    "data_utility": [
        "convert", "converter", "conversion", "csv to json", "json to csv", "canonicalize", "format conversion",
        "pdf to text", "html to markdown", "markdown to html", "qrcode", "qr code", "barcode", "base64", "hash",
        "sha256", "jwt", "uuid", "randomness", "validate", "validator", "validation", "validating", "normalize",
        "normalizer", "normalization", "parse", "parser", "parsing", "sanitize", "sanitizer", "checksum",
        "calculator", "math", "diff", "json schema", "json fix", "schema validator", "iban", "isbn", "timestamp",
        "timestamps", "epoch", "iso8601", "upload", "download", "file upload", "file download", "time in utc",
        "변환", "포맷", "인코딩", "해시", "유틸리티", "검증", "정규화", "파싱", "타임스탬프", "업로드", "다운로드",
    ],
    "communication_messaging": [
        "sms", "mms", "phone", "phone number", "telephony", "voice call", "whatsapp", "notification", "notifications",
        "push notification", "push notifications", "alert", "alerts", "twilio", "webhook", "webhooks", "messaging",
        "otp", "2fa", "문자", "전화", "알림", "메시징", "통신",
    ],
    "travel_maps_weather": [
        "weather", "weather forecast", "weather forecasts", "forecast weather", "hourly forecast", "daily forecast", "precipitation", "rainfall", "hurricane", "hurricanes", "tropical storm", "tornado", "severe weather", "noaa", "nws", "national weather service", "meteorological", "weather warnings", "weather alerts", "travel", "flight", "flights", "hotel", "hotels", "maps", "map", "geocoding",
        "geocode", "location", "places", "airport", "open-meteo", "latitude", "longitude", "timezone", "hourly weather",
        "daily weather", "elevation", "surf conditions", "surf report", "ocean safety", "volcano", "tide times", "tide table",
        "tide tables", "tide predictions", "sunrise and sunset", "sunrise sunset", "trail conditions", "hiking", "snow report", "날씨", "여행", "항공", "호텔", "지도", "위치", "위도", "경도", "타임존",
    ],
    "database_analytics": [
        "database", "databases", "sql", "postgres", "postgresql", "mysql", "supabase", "mongodb", "bigquery",
        "snowflake", "analytics", "dashboard", "metrics", "warehouse", "데이터베이스", "분석", "대시보드",
    ],
    "docs_knowledge": [
        "docs", "documentation", "knowledge", "knowledge base", "wiki", "notion", "rag", "retrieval", "confluence",
        "obsidian", "notes", "semantic search", "research", "researcher", "brief", "briefs", "research brief",
        "citation", "fact check", "fact-checking", "synthesis", "paper", "papers", "academic", "scholar", "arxiv",
        "literature", "research report", "whitepaper", "white paper", "문서", "지식", "위키", "노트", "연구", "논문", "리포트", "브리프", "자료조사",
    ],
    "productivity": [
        "email", "gmail", "outlook", "calendar", "slack", "teams", "crm", "hubspot", "salesforce", "jira", "asana",
        "trello", "linear", "todo", "to-do", "task management", "project management", "zendesk", "invoice", "google drive", "sheets",
        "spreadsheet", "메일", "이메일", "캘린더", "일정", "업무", "슬랙",
    ],
    "social": [
        "twitter", "tweet", "tweets", "x.com", "reddit", "linkedin", "youtube", "instagram", "tiktok", "discord",
        "telegram", "farcaster", "social", "sentiment", "followers", "influencer", "트위터", "소셜", "유튜브", "감성",
    ],
    "media_generation": [
        "image", "images", "video", "videos", "audio", "speech", "voice", "tts", "music", "photo", "3d", "render",
        "transcription", "transcribe", "animation", "이미지", "영상", "음성", "그림", "사진", "음악",
    ],
    "public_legal": [
        "government", "regulation", "regulations", "legal", "law", "laws", "court", "courts", "tribunal", "patent",
        "patents", "trademark", "registry", "register", "official-source", "compliance", "tax", "sec filings",
        "edgar", "grant", "grants", "sbir", "sam.gov", "grants.gov", "baa", "procurement", "법률", "법원", "판례", "규제",
        "특허", "세금", "공공", "공공조달", "정부지원", "보조금",
    ],
    "education_culture": [
        "book", "books", "library", "libraries", "literature", "author", "authors", "novel", "novels", "fiction",
        "cinema", "film", "films", "movie", "movies", "history", "historical", "archive", "archives", "audiobook",
        "museum", "art", "humanities", "도서", "책", "문학", "영화", "역사", "아카이브", "교육", "예술",
    ],
    "dev_tools": [
        "github", "gitlab", "git", "code", "coding", "repo", "repository", "ci", "deploy", "deployment", "devops",
        "kubernetes", "docker", "sdk", "npm", "developer", "developers", "debug", "terminal", "cli", "vercel",
        "cloudflare", "code review", "openapi", "swagger", "json schema", "regex", "linter", "formatter", "compiler",
        "ast", "deployer", "deployed", "deploying", "pull request", "git commit", "commits", "webhook handler", "faas",
        "scim", "sso", "코드", "코드 리뷰", "개발", "배포", "깃허브", "정규식", "컴파일러", "린터",
    ],
    "commerce_marketing": [
        "shopify", "ecommerce", "e-commerce", "product", "products", "seo", "marketing", "ads", "advertising",
        "amazon", "marketplace", "product reviews", "app reviews", "store", "쇼핑", "상품", "마케팅", "광고", "상품 리뷰",
    ],
    "web_search": [
        "search", "web", "scrape", "scraping", "crawl", "crawler", "serp", "browser", "web page", "webpage", "website",
        "extract", "enrich", "enrichment", "lead", "leads", "contact", "contacts", "news", "google search", "exa",
        "exa.ai", "tavily", "brave search", "perplexity", "sitemap", "검색", "크롤", "스크래핑", "웹", "뉴스", "연락처",
    ],
    "finance_crypto": [
        "crypto", "token", "tokens", "wallet", "wallets", "blockchain", "onchain", "on-chain", "defi", "bitcoin",
        "ethereum", "solana", "erc20", "nft", "stock", "stocks", "trading", "finance", "financial", "payment",
        "payments", "usdc", "price", "prices", "market data", "polymarket", "kalshi", "prediction market",
        "probability", "forecast", "odds", "dex", "swap", "swaps", "liquidity", "lending", "yield", "aave",
        "compound", "uniswap", "base chain", "arbitrum", "optimism", "evm", "web3", "coingecko", "coinmarketcap",
        "cross-chain", "erc-20", "erc-721", "gas", "gas fee", "gas fees", "crypto transaction", "tx hash", "txid",
        "transfer", "transfers", "coin", "coins", "mainnet", "testnet", "block number", "balance", "balances",
        "exchange rate", "exchange rates", "forex", "fx", "hbar", "hedera", "smart contract", "smart contracts",
        "지갑", "토큰", "코인", "블록체인", "주식", "시세", "결제", "예측", "스왑", "유동성", "렌딩", "디파이", "송금", "잔액",
        "환율", "가스비",
    ],
    "ai_models": [
        "llm", "llms", "gpt", "claude", "openai", "anthropic", "gemini", "model", "models", "prompt", "prompts",
        "inference", "embedding", "embeddings", "reasoning", "summarize", "summary", "translate", "translation",
        "memory", "chatbot", "요약", "번역", "추론", "언어모델",
    ],
}
# 동점일 때 우선순위 (구체적인 주제 → 일반적인 주제)
PRIORITY = list(KEYWORDS)

# 에이전트 인프라의 약한 표현: 혼자 나오면 자기 분야 서비스가 에이전트를 언급만 한 경우가 많다
# (수동 판정 정확도 43~58%: 내부에서 multi-agent로 분석하는 서비스, 한 업체 상품 설명에 공통으로 붙은 문구 등).
# 강한 표현과 함께 나오거나 약한 표현이 둘 이상일 때만 센다.
# 정확도가 0~9%였던 표현(agentic commerce, agent gateway, tool discovery, agent sandbox, agent analytics)은 뺐다.
INFRA_WEAK = {"multi-agent", "multi agent", "mcp hub", "capability discovery", "mcp router"}
# 에이전트 인프라로 세지 않는 문맥 (매칭 전에 지운다)
INFRA_BLOCK = [
    # 사이트 하나의 자체 게이트웨이: "MCP gateway for example.com", "the site's own MCP server", "<사이트> AI Gateway"
    r"(mcp|ai) gateway for [\w.-]+\.[a-z]{2,}", r"site'?s own mcp server", r"\bai gateway\b",
    # 한 제품·업종만 여는 게이트웨이·허브: "MCP gateway for WhatsApp", "official ... MCP gateway", "A2A hub for cosmetics"
    r"(mcp|ai|unified) gateway (for|to) (?!(ai |autonomous )?agents\b|any\b|all\b|multiple\b|many\b|your\b|\d)[^.:;]{0,60}",
    r"official [\w .-]{0,30}mcp gateway", r"mcp gateway with \d+ tools for [^.]{0,60}",
    r"(agent-to-agent|a2a)( \(a2a\))?( \+ [^.]{0,40})? hub for [^.]{0,60}",
    # 상점·상품 노출: 에이전트가 쓰는 인프라가 아니라 판매자의 판로
    r"storefront[^.]{0,60}", r"(make (a |your )?products? discoverable|product listings?|listed in agent|placement in agent discovery)[^.]{0,80}",
    # 'agent'가 다른 뜻: 선수·부동산·여행·보험 에이전트
    r"(football|soccer|sports?|player|real[ -]estate|realtor|travel|insurance|talent|booking) agents?\b[\w -]{0,20}",
    # 판매자가 에이전트에게 노출되려는 광고·SEO (고객은 사람)
    r"(advertis\w*|ad placements?|billboard|sponsored listings?|generative engine optimi[sz]ation|\bgeo\b|ai visibility)"
    r"[^.]{0,80}",
    # 에이전트·MCP 대응 점검 도구 (개발자용)
    r"(agent|ai)[ -]readiness (audit|score|check|scan)s? (of|for) (an? |your )?(website|site|domain|store|business)",
    r"(health|readiness) (check|scan)s? (for|of) (your )?(mcp servers?|agent cards?)",
]
_INFRA_BLOCK = [re.compile(p) for p in INFRA_BLOCK]
# 강한 표현(정규식): MCP 서버·A2A 에이전트·x402 API를 찾아 주는 탐색 서비스 ("search 15K+ MCP servers and A2A agents")
# '... for AI agents'는 거의 모든 설명에 붙으므로 대상에 넣지 않는다
INFRA_PATTERNS = [re.compile(
    r"(search|discover|find|browse|index(es|ing)?|director(y|ies)|catalog(ue)?|registr(y|ies)|list(s|ing)?)\b[^.]{0,50}"
    r"\b(mcp (servers|services)|a2a agents|x402 (apis|services|endpoints)|agent cards)\b")]  # 'as MCP tools'는 자기 서비스 설명이라 뺌

_WORD = re.compile(r"[^\W_]+")
_PATTERNS = {
    cat: [re.compile(r"(?<![0-9a-z])" + re.escape(k) + (r"(?![0-9a-z])" if k.isascii() else "")) for k in kws]
    for cat, kws in KEYWORDS.items()
}
assert set(KEYWORDS) == set(CATEGORIES), set(KEYWORDS) ^ set(CATEGORIES)


def _infra_score(text: str) -> int:
    for p in _INFRA_BLOCK:
        text = p.sub(" ", text)
    hits = [k for k, p in zip(KEYWORDS["agent_infra"], _PATTERNS["agent_infra"]) if k in text and p.search(text)]
    weak = sum(1 for k in hits if k in INFRA_WEAK)
    strong = len(hits) - weak + sum(1 for p in INFRA_PATTERNS if p.search(text))
    return strong + weak if strong or weak >= 2 else 0


# How a listing is billed ("pay-per-call over the x402 payment protocol, USDC on Base") says
# nothing about what it does; such sentences must not turn a weather API into finance.
_BILLING = re.compile(r"[^.;\n]*(?:pay[- ]per[- ](?:call|request|use)|x402 payment protocol|usdc on (?:base|polygon|solana)"
                      r"|paid (?:in|with|via) usdc|payments? (?:via|with|over) x402)[^.;\n]*", re.I)


def _scores(text: str) -> dict[str, int]:
    out = {cat: sum(1 for k, p in zip(KEYWORDS[cat], pats) if k in text and p.search(text))
           for cat, pats in _PATTERNS.items() if cat != "agent_infra"}
    out["agent_infra"] = _infra_score(text)
    return out


def scores(text: str) -> dict[str, int]:
    text = text.lower()
    without_billing = _scores(_BILLING.sub(" ", text))
    # A listing that is only about payments (a payment gateway) keeps its own words.
    return without_billing if any(without_billing.values()) else _scores(text)


def classify(text: str) -> str:
    """가장 많은 키워드가 일치한 주제. 동점이면 PRIORITY 앞쪽. 일치가 없으면 'other'."""
    s = scores(text)
    best = max(PRIORITY, key=lambda c: (s[c], -PRIORITY.index(c)))
    return best if s[best] > 0 else OTHER


# Tool text longer than this is a publisher's shared tool bundle (the 14k-character packs), not this listing's own.
BUNDLE_TOOL_CHARS = 8000


def classify_listing(text: str, tool_text: str = "") -> str:
    """Name, description and tool descriptions are read together, as before, except when the tool text
    is a large shared bundle: then the listing's own description decides and the bundle only breaks ties
    ("Twilio MCP Pack — send SMS" otherwise became docs_knowledge from the pack's research tools).
    Weighting every description over its tools moved ~6x more listings with mixed results, so this stays narrow."""
    if len(tool_text) <= BUNDLE_TOOL_CHARS:
        return classify(text + (" " + tool_text if tool_text else ""))
    own = scores(text)
    if not any(own.values()):
        return classify(text + " " + tool_text)
    tools = scores(tool_text)
    return max(PRIORITY, key=lambda c: (own[c], tools[c], -PRIORITY.index(c)))


STOPWORDS = set(
    "a an and any are as at be by can do for from get i in into is it its me my of on or our please that the this "
    "to us we with you your api apis agent agents ai tool tools service data mcp server 해줘 주세요 해주세요 좀".split()
)


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def query_terms(text: str, limit: int = 32) -> list[str]:
    """검색·관련도 계산용 단어: 중복·한 글자·흔한 단어(불용어) 제외."""
    return [t for t in dict.fromkeys(tokens(text)) if len(t) > 1 and t not in STOPWORDS][:limit]
