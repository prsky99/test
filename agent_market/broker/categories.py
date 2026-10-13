"""게이트웨이·브로커·수집 에이전트가 함께 쓰는 서비스 카테고리 (13개 주제).

수집 에이전트가 모은 실제 MCP 서버 2.7만 개와 x402 유료 엔드포인트 3.3만 개의 설명을 분석해
에이전트가 실제로 제공·탐색하는 주제 13개로 나눴다 (2026-10, COLLECTOR.md / AGENT_BROKER.md 참고).
어느 주제에도 맞지 않으면 'other'.

이전 6개 카테고리 ID는 LEGACY_ALIASES로 새 ID에 대응시켜, 예전 클라이언트·판매자 agent card도 그대로 동작한다.
매매 실행(스왑·포지션)은 자금 위탁·규제 위험 때문에 중개하지 않는다.
"""

from dataclasses import dataclass

from ..config import usdc


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str
    typical_price: str  # 조사된 1회 호출 가격대 (참고용)


CATEGORIES = {
    c.id: c
    for c in [
        Category("ai_models", "AI 모델·에이전트 도구",
                 "Delegated LLM work and agent tooling: other models, summarization, translation, writing, embeddings, agent memory, prompts.",
                 "~$0.03"),
        Category("finance_crypto", "금융·결제·크립토",
                 "Wallets, tokens, on-chain and DeFi analytics, crypto and stock prices, payments, trading data, prediction markets and forecasts.",
                 "$0.01~0.05"),
        Category("web_search", "웹 검색·스크래핑",
                 "Web search, page scraping and crawling, browser automation, lead and company enrichment that returns fresh external data.",
                 "$0.02~0.16"),
        Category("dev_tools", "개발 도구",
                 "Code, Git repositories, CI/CD, deployment, cloud infrastructure, package registries, debugging and code review.",
                 "-"),
        Category("public_legal", "공공·법률·규제 데이터",
                 "Government and official registers, laws and regulations, courts, patents and trademarks, tax and compliance lookups.",
                 "-"),
        Category("commerce_marketing", "커머스·마케팅",
                 "E-commerce stores and products, marketplaces, reviews, SEO, advertising and marketing data.",
                 "-"),
        Category("media_generation", "미디어 생성",
                 "Image, video, audio, speech and music generation, transcription and captioning.", "-"),
        Category("productivity", "업무·생산성 SaaS",
                 "Email, calendar, chat (Slack, Teams), CRM, project and task management, spreadsheets and office documents.", "-"),
        Category("docs_knowledge", "문서·지식·RAG",
                 "Documentation lookup, knowledge bases, wikis and notes, retrieval-augmented generation and semantic search over documents.", "-"),
        Category("social", "소셜·커뮤니티",
                 "Social media and community data: X/Twitter, Reddit, LinkedIn, YouTube, Discord, Telegram, sentiment.", "~$0.01"),
        Category("database_analytics", "데이터베이스·분석",
                 "Databases and SQL, data warehouses, analytics dashboards and metrics.", "-"),
        Category("travel_maps_weather", "여행·지도·날씨",
                 "Weather, maps and geocoding, places, flights, hotels and travel booking data.", "-"),
        Category("security", "보안",
                 "Security scanning, vulnerabilities and CVEs, threat intelligence, OSINT, phishing and malware analysis.", "-"),
    ]
}

# 이전 6개 카테고리 → 새 13개 주제
LEGACY_ALIASES = {
    "web_data": "web_search",
    "llm_inference": "ai_models",
    "onchain_intel": "finance_crypto",
    "prediction": "finance_crypto",
    "social_data": "social",
}


def normalize_category(category: str | None) -> str | None:
    """예전 카테고리 ID도 받아서 새 ID로 바꾼다. 모르는 값은 그대로 돌려준다(호출 측에서 검증)."""
    if category is None:
        return None
    return LEGACY_ALIASES.get(category, category)


# 중개 수수료 정책: 추천된 최상위 서비스 가격의 FEE_BPS(1/10000), 최소 MIN_FEE.
DEFAULT_FEE_BPS = 500  # 5%
DEFAULT_MIN_FEE = usdc("0.001")


def match_fee(top_price: int, fee_bps: int = DEFAULT_FEE_BPS, min_fee: int = DEFAULT_MIN_FEE) -> int:
    return max(min_fee, -(-top_price * fee_bps // 10_000))  # 올림
