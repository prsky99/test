"""API 키 없이 동작하는 키워드 기반 카테고리 분류기 (영어·한국어)."""

import re

from ..broker.categories import CATEGORIES

OTHER = "other"

KEYWORDS: dict[str, list[str]] = {
    "web_data": [
        "search", "scrape", "scraping", "crawl", "crawler", "web", "serp", "google", "enrich", "enrichment", "lead",
        "leads", "people", "company", "companies", "contact", "linkedin", "email", "domain", "news", "browser",
        "page", "url", "website", "extract", "검색", "크롤", "스크래핑", "웹", "리드", "회사", "연락처", "뉴스",
    ],
    "llm_inference": [
        "llm", "gpt", "claude", "model", "models", "summarize", "summary", "translate", "translation", "chat",
        "completion", "inference", "text", "writing", "rewrite", "code", "review", "embedding", "embeddings",
        "reasoning", "prompt", "요약", "번역", "코드", "리뷰", "글쓰기", "추론", "텍스트",
    ],
    "onchain_intel": [
        "wallet", "token", "tokens", "erc20", "blockchain", "onchain", "on-chain", "defi", "eth", "ethereum",
        "solana", "base", "tx", "transaction", "transactions", "nft", "crypto", "balance", "ens", "whale",
        "smart money", "dex", "swap", "price", "prices", "chain", "block", "contract", "지갑", "토큰", "온체인",
        "코인", "시세", "트랜잭션", "블록체인",
    ],
    "prediction": [
        "predict", "prediction", "forecast", "forecasting", "probability", "odds", "polymarket", "kalshi",
        "market outcome", "예측", "전망", "확률",
    ],
    "social_data": [
        "twitter", "tweet", "tweets", "x.com", "social", "reddit", "farcaster", "sentiment", "instagram",
        "tiktok", "youtube", "followers", "influencer", "트위터", "소셜", "감성", "유튜브",
    ],
    "media_generation": [
        "image", "images", "video", "videos", "audio", "tts", "speech", "voice", "music", "3d", "render",
        "photo", "picture", "animation", "이미지", "영상", "음성", "그림", "사진", "음악",
    ],
}

_WORD = re.compile(r"[^\W_]+")
_PATTERNS = {
    cat: [re.compile(r"(?<![0-9a-z])" + re.escape(k) + (r"(?![0-9a-z])" if k.isascii() else "")) for k in kws]
    for cat, kws in KEYWORDS.items()
}
assert set(KEYWORDS) == set(CATEGORIES)


def classify(text: str) -> str:
    """가장 많은 키워드가 일치한 카테고리. 일치가 없으면 'other'."""
    text = text.lower()
    scores = {cat: sum(1 for p in pats if p.search(text)) for cat, pats in _PATTERNS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else OTHER


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())
