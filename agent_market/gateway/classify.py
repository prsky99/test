"""API 키 없이 동작하는 키워드 기반 카테고리 분류기 (영어·한국어, 14개 주제).

설명에 등장한 주제별 키워드 수로 점수를 매겨 가장 높은 주제를 고른다. 동점이면 더 구체적인 주제가 이긴다
(PRIORITY 순서). "for AI agents"처럼 거의 모든 설명에 붙는 일반어는 AI 모델 주제의 키워드로 쓰지 않는다.
"""

import re

from ..broker.categories import CATEGORIES

OTHER = "other"
VERSION = 3  # 키워드가 바뀌면 올린다 → 저장된 에이전트를 다시 분류 (3: agent_infra 추가)

KEYWORDS: dict[str, list[str]] = {
    # 에이전트 인프라: 'agents', 'discovery', 'x402' 같은 일반어는 거의 모든 설명에 있어 쓰지 않고 구체적인 표현만 쓴다.
    # 가장 앞에 둬서 동점이면 이 주제가 이긴다 (예: "agent discovery and search" → web_search가 아니라 agent_infra)
    "agent_infra": [
        "agent discovery", "discover agents", "discover ai agents", "find agents", "agent registry", "agent registries",
        "agent directory", "agent index", "agent catalog", "agent marketplace", "agents marketplace", "agent-to-agent",
        "agent to agent", "a2a gateway", "a2a registry", "a2a directory", "a2a marketplace", "agent card", "agent cards",
        "agent network", "agent economy", "agentic economy", "agent commerce", "agentic commerce",
        "mcp gateway", "mcp bridge", "mcp proxy", "mcp hub", "mcp registry", "mcp router", "mcp server discovery",
        "tool discovery", "tool registry", "capability discovery", "capability registry",
        "agent orchestration", "multi-agent orchestration", "multi-agent", "multi agent", "agent swarm", "agent swarms",
        "agent coordination", "coordination layer", "coordination service", "agent handoff", "agent delegation",
        "agent identity", "agent identities", "agent reputation", "on-chain reputation", "reputation registry",
        "reputation oracle", "agent trust", "trust layer", "trust registry", "trust engine", "agent attestation",
        "erc-8004 identity", "erc-8004 registry", "erc-8004 agents", "erc-8004 registration", "register your ai agent",
        "know your agent", "kya", "verifiable credential", "verifiable credentials", "agent negotiation",
        "agent matchmaking", "agent messaging", "agent inbox", "message board", "bulletin board",
        "agent hosting", "agent runtime", "agent sandbox", "agent observability", "agent monitoring", "agent analytics",
        "agent memory", "agent payments", "agent gateway", "agent router", "agent escrow",
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

_WORD = re.compile(r"[^\W_]+")
_PATTERNS = {
    cat: [re.compile(r"(?<![0-9a-z])" + re.escape(k) + (r"(?![0-9a-z])" if k.isascii() else "")) for k in kws]
    for cat, kws in KEYWORDS.items()
}
assert set(KEYWORDS) == set(CATEGORIES), set(KEYWORDS) ^ set(CATEGORIES)


def scores(text: str) -> dict[str, int]:
    text = text.lower()
    return {cat: sum(1 for p in pats if p.search(text)) for cat, pats in _PATTERNS.items()}


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
