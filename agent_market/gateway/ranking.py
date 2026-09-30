"""에이전트 점수 계산. API 키 없이 공개 지표와 자체 관측값만 사용한다.

점수(0~1) = 관련도 0.35 + 인기(30일 결제자 수) 0.20 + 가용성(프로브) 0.15 + 가격 0.15 + 최근 사용 0.10 + 고객 평가 0.05
각 항목은 절대 기준으로 계산해, 시간이 지나도 현재 에이전트와 새 후보를 공정하게 비교할 수 있다.
"""

import json
import math
import time
from dataclasses import dataclass, field

from .classify import tokens
from .store import Store

WEIGHTS = {"relevance": 0.35, "popularity": 0.20, "reliability": 0.15, "price": 0.15, "recency": 0.10, "feedback": 0.05}
POPULARITY_SATURATION = 1000  # 30일 결제자 1000명이면 만점
REFERENCE_PRICE = 10_000  # 0.01 USDC 이하면 가격 만점


@dataclass
class Scored:
    resource: dict
    score: float
    parts: dict = field(default_factory=dict)


def _relevance(task_terms: list[str], idf: dict[str, float], resource: dict) -> float:
    if not task_terms:
        return 0.5
    doc = set(tokens(f"{resource['name']} {resource['description']}"))
    total = sum(idf.get(t, 1.0) for t in task_terms)
    hit = sum(idf.get(t, 1.0) for t in task_terms if t in doc)
    return hit / total if total else 0.0


def _reliability(resource: dict) -> float:
    ok, fail = resource.get("probe_ok") or 0, resource.get("probe_fail") or 0
    reliability = (ok + 1) / (ok + fail + 2)
    latency = resource.get("probe_latency_ms")
    if latency is not None and latency > 2000:
        reliability *= 0.8
    return reliability


def refresh_reliability(s: Scored) -> None:
    """프로브 직후 가용성 점수만 다시 반영한다 (현재 에이전트와 같은 조건으로 비교하기 위해)."""
    new = _reliability(s.resource)
    s.score = round(s.score + WEIGHTS["reliability"] * (new - s.parts["reliability"]), 4)
    s.parts["reliability"] = round(new, 3)


def score_resource(resource: dict, task_terms: list[str], idf: dict[str, float], category: str, store: Store, now: float | None = None) -> Scored:
    now = now or time.time()
    parts = {}
    rel = _relevance(task_terms, idf, resource)
    parts["relevance"] = min(1.0, rel + (0.2 if resource["category"] == category else 0.0))

    payers = resource.get("payers_30d")
    parts["popularity"] = 0.3 if payers is None else min(1.0, math.log1p(payers) / math.log1p(POPULARITY_SATURATION))

    parts["reliability"] = _reliability(resource)

    price = resource.get("price_usdc")
    parts["price"] = 0.5 if price is None else (1.0 if price <= REFERENCE_PRICE else min(1.0, REFERENCE_PRICE / price) ** 0.5)

    last = resource.get("last_called")
    if last is None:
        parts["recency"] = 0.3
    else:
        days = max(0.0, (now - last) / 86400)
        parts["recency"] = 1.0 if days <= 7 else max(0.0, 1 - (days - 7) / 53)

    n, successes, avg_rating = store.feedback_stats(resource["id"])
    success_rate = (successes + 1) / (n + 2)
    rating = ((avg_rating or 3.5) - 1) / 4
    parts["feedback"] = (success_rate + rating) / 2 if n else 0.5

    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return Scored(resource, round(total, 4), {k: round(v, 3) for k, v in parts.items()})


def rank(store: Store, need: dict, limit: int = 5, include: int | None = None) -> tuple[list[Scored], Scored | None]:
    """need에 맞는 후보를 점수순으로. include(현재 에이전트 id)도 같은 기준으로 점수를 매겨 돌려준다."""
    terms = [t for t in dict.fromkeys(tokens(need["task"])) if len(t) > 1][:32]
    idf = store.idf(terms)
    candidates = store.search(need["task"], need["category"], need.get("max_price"), need["networks"], need["kinds"])
    scored = sorted((score_resource(r, terms, idf, need["category"], store) for r in candidates), key=lambda s: s.score, reverse=True)
    current = None
    if include is not None:
        res = store.resource(include)
        if res is not None:
            current = score_resource(res, terms, idf, need["category"], store)
            if not res["active"]:
                current.score = 0.0  # 목록에서 사라진 에이전트는 교체 대상
    return scored[:limit], current


def teaser(new: Scored, old: Scored | None) -> dict:
    """결제 전 공개 정보: 이름·URL은 숨기고 왜 더 좋은지만 알려준다."""
    r = new.resource
    reasons = []
    if old is not None:
        o = old.resource
        if old.score > 0:
            reasons.append(f"종합 점수 {round((new.score / old.score - 1) * 100)}% 향상")
        if r.get("payers_30d") and (o.get("payers_30d") or 0) and r["payers_30d"] > o["payers_30d"]:
            reasons.append(f"최근 30일 결제자 {r['payers_30d'] / o['payers_30d']:.1f}배")
        if r.get("price_usdc") is not None and o.get("price_usdc") and r["price_usdc"] < o["price_usdc"]:
            reasons.append(f"가격 {round((1 - r['price_usdc'] / o['price_usdc']) * 100)}% 저렴")
        if new.parts["reliability"] > old.parts["reliability"] + 0.1:
            reasons.append("응답 안정성 높음")
        if not o.get("active"):
            reasons.append("현재 에이전트가 목록에서 사라짐")
    return {
        "kind": r["kind"],
        "category": r["category"],
        "price_usdc": r.get("price_usdc"),
        "networks": [n for n in r["networks"].strip(",").split(",") if n],
        "payers_30d": r.get("payers_30d"),
        "score": new.score,
        "previous_score": old.score if old else None,
        "reasons": reasons,
    }


def reveal(s: Scored) -> dict:
    r = s.resource
    return {
        "resource_id": r["id"],
        "kind": r["kind"],
        "name": r["name"],
        "url": r["url"],
        "description": r["description"],
        "category": r["category"],
        "price_usdc": r.get("price_usdc"),
        "pay_to": r.get("pay_to"),
        "method": r.get("method"),
        "networks": [n for n in r["networks"].strip(",").split(",") if n],
        "calls_30d": r.get("calls_30d"),
        "payers_30d": r.get("payers_30d"),
        "details": json.loads(r["details"]),
        "score": s.score,
        "score_parts": s.parts,
    }
