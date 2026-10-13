"""API 키 없이 동작하는 키워드 기반 카테고리 분류기 (영어·한국어, 14개 주제).

설명에 등장한 주제별 키워드 수로 점수를 매겨 가장 높은 주제를 고른다. 동점이면 더 구체적인 주제가 이긴다
(PRIORITY 순서). "for AI agents"처럼 거의 모든 설명에 붙는 일반어는 AI 모델 주제의 키워드로 쓰지 않는다.
"""

import re

from ..broker.categories import CATEGORIES

OTHER = "other"
VERSION = 5  # 키워드가 바뀌면 올린다 → 저장된 에이전트를 다시 분류 (3: agent_infra 추가, 4: A2A는 스킬 포함,
#              5: agent_infra 약한 표현·제외 문맥)

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
        "reputation oracle", "agent trust", "trust layer", "trust registry", "trust engine", "agent attestation",
        "erc-8004 identity", "erc-8004 registry", "erc-8004 agents", "erc-8004 registration", "register your ai agent",
        "know your agent", "kya", "verifiable credential", "verifiable credentials", "agent negotiation",
        "agent matchmaking", "agent messaging", "agent inbox", "message board", "bulletin board",
        "agent hosting", "agent runtime", "agent observability", "agent monitoring",
        "agent memory", "agent payments", "agent router", "agent escrow", "agent governance", "agent due diligence",
        "due-diligence check on an agent", "trust badge", "agent dids", "task coordination", "task orchestration",
        "multi-agent settlement", "multi-agent consensus", "multi-agent escrow", "multi-agent governance",
        "multi-agent coordination", "multi-agent task", "hub for autonomous agents", "ai service discovery",
        "에이전트 인프라", "에이전트 검색", "에이전트 등록", "에이전트 마켓", "오케스트레이션", "멀티 에이전트", "에이전트 평판", "에이전트 신원",
    ],
    "security": [
        "security", "vulnerability", "vulnerabilities", "cve", "threat", "threats", "malware", "pentest", "osint",
        "phishing", "exploit", "firewall", "보안", "취약점", "해킹", "악성코드",
    ],
    "travel_maps_weather": [
        "weather", "forecast weather", "travel", "flight", "flights", "hotel", "hotels", "maps", "map", "geocoding",
        "geocode", "location", "places", "airport", "날씨", "여행", "항공", "호텔", "지도", "위치",
    ],
    "database_analytics": [
        "database", "databases", "sql", "postgres", "postgresql", "mysql", "supabase", "mongodb", "bigquery",
        "snowflake", "analytics", "dashboard", "metrics", "warehouse", "데이터베이스", "분석", "대시보드",
    ],
    "docs_knowledge": [
        "docs", "documentation", "knowledge", "knowledge base", "wiki", "notion", "rag", "retrieval", "confluence",
        "obsidian", "notes", "semantic search", "문서", "지식", "위키", "노트",
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
        "edgar", "법률", "법원", "판례", "규제", "특허", "세금", "공공",
    ],
    "dev_tools": [
        "github", "gitlab", "git", "code", "coding", "repo", "repository", "ci", "deploy", "deployment", "devops",
        "kubernetes", "docker", "sdk", "npm", "developer", "developers", "debug", "terminal", "cli", "vercel",
        "cloudflare", "code review", "코드", "코드 리뷰", "개발", "배포", "깃허브",
    ],
    "commerce_marketing": [
        "shopify", "ecommerce", "e-commerce", "product", "products", "seo", "marketing", "ads", "advertising",
        "amazon", "marketplace", "product reviews", "app reviews", "store", "쇼핑", "상품", "마케팅", "광고", "상품 리뷰",
    ],
    "web_search": [
        "search", "web", "scrape", "scraping", "crawl", "crawler", "serp", "browser", "web page", "webpage", "website",
        "extract", "enrich", "enrichment", "lead", "leads", "contact", "contacts", "news", "google search",
        "검색", "크롤", "스크래핑", "웹", "뉴스", "연락처",
    ],
    "finance_crypto": [
        "crypto", "token", "tokens", "wallet", "wallets", "blockchain", "onchain", "on-chain", "defi", "bitcoin",
        "ethereum", "solana", "erc20", "nft", "stock", "stocks", "trading", "finance", "financial", "payment",
        "payments", "usdc", "price", "prices", "market data", "polymarket", "kalshi", "prediction market",
        "probability", "forecast", "odds", "지갑", "토큰", "코인", "블록체인", "주식", "시세", "결제", "예측",
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
    hits = [k for k, p in zip(KEYWORDS["agent_infra"], _PATTERNS["agent_infra"]) if p.search(text)]
    weak = sum(1 for k in hits if k in INFRA_WEAK)
    strong = len(hits) - weak + sum(1 for p in INFRA_PATTERNS if p.search(text))
    return strong + weak if strong or weak >= 2 else 0


def scores(text: str) -> dict[str, int]:
    text = text.lower()
    out = {cat: sum(1 for p in pats if p.search(text)) for cat, pats in _PATTERNS.items() if cat != "agent_infra"}
    out["agent_infra"] = _infra_score(text)
    return out


def classify(text: str) -> str:
    """가장 많은 키워드가 일치한 주제. 동점이면 PRIORITY 앞쪽. 일치가 없으면 'other'."""
    s = scores(text)
    best = max(PRIORITY, key=lambda c: (s[c], -PRIORITY.index(c)))
    return best if s[best] > 0 else OTHER


STOPWORDS = set(
    "a an and any are as at be by can do for from get i in into is it its me my of on or our please that the this "
    "to us we with you your api apis agent agents ai tool tools service data mcp server 해줘 주세요 해주세요 좀".split()
)


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def query_terms(text: str, limit: int = 32) -> list[str]:
    """검색·관련도 계산용 단어: 중복·한 글자·흔한 단어(불용어) 제외."""
    return [t for t in dict.fromkeys(tokens(text)) if len(t) > 1 and t not in STOPWORDS][:limit]
