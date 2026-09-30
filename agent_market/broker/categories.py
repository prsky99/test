"""브로커가 중개하는 서비스 카테고리.

2025~2026년 에이전트 간 거래 데이터(x402 상위 서비스, Olas Mech 요청 수, Virtuals ACP 수익,
MCP 인기 서버 등)를 조사해, 에이전트가 다른 에이전트를 실제로 많이 찾는 분야를 수요 순으로 골랐다.
근거와 출처는 AGENT_BROKER.md 참고.

제외: 매매 실행(스왑·포지션 개설). 거래량은 가장 크지만 수수료율이 낮고(약 0.1~0.3%),
자금 위탁·규제 위험이 커서 이 브로커는 다루지 않는다.
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
        Category(
            "web_data",
            "웹 검색·스크래핑·리드 보강",
            "Web search, page scraping/crawling, and company or contact lookups (lead enrichment) that return fresh external data.",
            "$0.02~0.16",
        ),
        Category(
            "llm_inference",
            "LLM 추론·텍스트 작업",
            "Delegated reasoning and text work by another model: summarization, translation, code review, writing, extraction.",
            "~$0.03",
        ),
        Category(
            "onchain_intel",
            "온체인·크립토 분석",
            "Wallet tracking, smart-money flows, DeFi analytics, token and protocol research.",
            "$0.02~0.05",
        ),
        Category(
            "prediction",
            "예측·전망",
            "Probability estimates and forecasts for questions or markets (e.g. prediction-market questions).",
            "~$0.01",
        ),
        Category(
            "social_data",
            "소셜·실시간 피드",
            "Real-time social media data such as X/Twitter posts, profiles, trends and sentiment.",
            "~$0.01",
        ),
        Category(
            "media_generation",
            "이미지·영상 생성",
            "Image, video or audio generation and captioning.",
            "가격 데이터 부족",
        ),
    ]
}

# 중개 수수료 정책: 추천된 최상위 서비스 가격의 FEE_BPS(1/10000), 최소 MIN_FEE.
DEFAULT_FEE_BPS = 500  # 5%
DEFAULT_MIN_FEE = usdc("0.001")


def match_fee(top_price: int, fee_bps: int = DEFAULT_FEE_BPS, min_fee: int = DEFAULT_MIN_FEE) -> int:
    return max(min_fee, -(-top_price * fee_bps // 10_000))  # 올림
