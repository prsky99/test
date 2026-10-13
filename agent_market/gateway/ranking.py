"""에이전트 점수 계산. API 키 없이 공개 지표와 자체 관측값만 사용한다.

점수(0~1) = 관련도 0.30 + 인기(30일 결제자 수) 0.15 + 가용성(24시간 헬스체크 성공률) 0.15 + 가격 0.10 + 최근 사용 0.05
           + 조건 적합도(언어·지역·인증 없이 사용 가능) 0.10 + 품질 평가(collector/evaluation.py) 0.10 + 고객 평가 0.05
각 항목은 절대 기준으로 계산해, 시간이 지나도 현재 에이전트와 새 후보를 공정하게 비교할 수 있다.
"""

import json
import math
import time
from dataclasses import dataclass, field

from . import constraints as cons
from .classify import query_terms, tokens
from .store import Store

# 관련도가 가장 무겁다: 품질·인기가 높아도 작업과 관계없는 에이전트가 앞에 오지 않게 (2026-10 실측으로 0.30 → 0.45)
WEIGHTS = {"relevance": 0.45, "popularity": 0.10, "reliability": 0.12, "price": 0.07, "recency": 0.03, "fit": 0.08,
           "quality": 0.10, "feedback": 0.05}
POPULARITY_SATURATION = 1000  # 30일 결제자 1000명이면 만점
REFERENCE_PRICE = 10_000  # 0.01 USDC 이하면 가격 만점
MIN_RELEVANCE_OTHER_CATEGORY = 0.4  # 카테고리가 다르면 작업 설명과 이만큼은 겹쳐야 후보로 인정 (단어 겹침 50%에 해당)
PHRASE_SHARE = 0.25  # 관련도 중 구절 일치(질문의 이어진 두 단어가 설명에서도 이어져 나옴)의 몫


@dataclass
class Scored:
    resource: dict
    score: float
    parts: dict = field(default_factory=dict)


def _stem(word: str) -> str:
    """관련도 비교용 아주 가벼운 어간: 영어 복수형만 묶는다 (rates→rate, quotes→quote, searches→search)."""
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _relevance(task_terms: list[str], idf: dict[str, float], resource: dict) -> float:
    """작업 단어가 설명에 얼마나 들어 있는지(드문 단어일수록 무겁게) + 구절이 그대로 나오는지.
    'exchange rate'처럼 두 단어가 붙어 있어야 뜻이 되는 경우, 'Coinbase Exchange ... spot rate'처럼 따로 흩어진 설명과 구분한다."""
    if not task_terms:
        return 0.5
    words = [_stem(t) for t in tokens(f"{resource['name']} {resource['description']}")]
    doc, bigrams = set(words), set(zip(words, words[1:]))
    total = sum(idf.get(t, 1.0) for t in task_terms)
    overlap = sum(idf.get(t, 1.0) for t in task_terms if _stem(t) in doc) / total if total else 0.0
    stems = [_stem(t) for t in task_terms]
    pairs = list(zip(stems, stems[1:]))
    if not pairs:
        return overlap
    phrase = sum(1 for pair in pairs if pair in bigrams) / len(pairs)
    return (1 - PHRASE_SHARE) * overlap + PHRASE_SHARE * phrase


def _reliability(resource: dict) -> float:
    """최근 24시간 헬스체크 성공률 (수집 에이전트가 매시간 점검). 점검 기록이 없으면 0.5."""
    n, ok = resource.get("health_n_24h") or 0, resource.get("health_ok_24h") or 0
    reliability = (ok + 1) / (n + 2)
    latency = resource.get("probe_latency_ms")
    if latency is not None and latency > 2000:
        reliability *= 0.8
    return reliability


def refresh_reliability(s: Scored) -> None:
    """프로브 직후 가용성 점수만 다시 반영한다 (현재 에이전트와 같은 조건으로 비교하기 위해)."""
    new = _reliability(s.resource)
    s.score = round(s.score + WEIGHTS["reliability"] * (new - s.parts["reliability"]), 4)
    s.parts["reliability"] = round(new, 3)


def agent_languages(resource: dict) -> list[str]:
    return list(dict.fromkeys(cons.unpack(resource.get("cap_languages")) + ([resource["desc_lang"]] if resource.get("desc_lang") else [])))


def agent_regions(resource: dict) -> list[str]:
    return list(dict.fromkeys(cons.unpack(resource.get("regions")) + cons.unpack(resource.get("cap_regions"))))


def auth_required(resource: dict) -> bool | None:
    v = resource.get("auth_observed")
    v = resource.get("auth_declared") if v is None else v
    return None if v is None else bool(v)


def auth_details(resource: dict) -> dict:
    """소개할 때 함께 알려 주는 인증 정보: 필요 여부, 방법, 사람 개입 필요 여부, 따라 할 단계."""
    info = {}
    if resource.get("auth_info"):
        try:
            info = json.loads(resource["auth_info"])
        except ValueError:
            info = {}
    required = auth_required(resource)
    out = {"required": required, "method": resource.get("auth_method"), "autonomy": resource.get("auth_autonomy")}
    if resource.get("kind") == "x402":
        out.update(method="x402_payment", autonomy="agent_autonomous",
                   instructions=["No account needed: pay per call with USDC via the x402 protocol (HTTP 402)."])
    elif info:
        out.update({k: info[k] for k in ("instructions", "oauth", "api_key", "website") if info.get(k)})
    elif required:
        out["instructions"] = ["Authentication required; method not yet discovered."]
    return out


def _fit(resource: dict, need: dict | None) -> float:
    """요청 조건과 얼마나 맞는지. 언어(요청 시), 지역(요청 시), 계정 없이 바로 쓸 수 있는지의 평균."""
    need = need or {}
    parts = []
    if need.get("language"):
        langs = agent_languages(resource)
        parts.append(1.0 if need["language"] in langs else 0.5 if not langs else 0.4 if "en" in langs else 0.2)
    if need.get("region"):
        regions = agent_regions(resource)
        parts.append(1.0 if need["region"] in regions else 0.6)  # 지역 표시 없음 = 전 세계 공통
    auth = auth_required(resource)
    if auth and resource.get("auth_autonomy") == "agent_autonomous":
        parts.append(0.8)  # 인증은 필요하지만 에이전트 혼자 할 수 있음
    else:
        parts.append(0.6 if auth is None else 0.4 if auth else 1.0)
    if resource.get("trial_ok") is not None:  # 실제로 호출해 봤으면 반영 (실패는 예제 인자 탓일 수도 있어 약하게)
        parts.append(1.0 if resource["trial_ok"] else 0.5)
    return sum(parts) / len(parts)


def score_resource(resource: dict, task_terms: list[str], idf: dict[str, float], category: str, store: Store,
                   now: float | None = None, need: dict | None = None,
                   feedback: tuple[int, int, float | None] | None = None) -> Scored:
    """feedback: 미리 모아 둔 (평가 수, 성공 수, 평균 별점). 없으면 이 에이전트만 따로 조회한다."""
    now = now or time.time()
    parts = {}
    rel = _relevance(task_terms, idf, resource)
    # 같은 카테고리 보너스는 더하되 1.0에서 자르지 않게 비율로 섞는다 (자르면 0.85와 1.0이 같은 점수가 됨)
    parts["relevance"] = 0.8 * rel + (0.2 if resource["category"] == category else 0.0)

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

    parts["fit"] = _fit(resource, need)

    # 규칙 기반 품질 평가 점수. 평가가 없거나 인증이 필요해 정적 평가만 있으면 중립
    parts["quality"] = 0.5 if resource.get("eval_score") is None else resource["eval_score"] / 100

    n, successes, avg_rating = feedback if feedback is not None else store.feedback_stats(resource["id"])
    success_rate = (successes + 1) / (n + 2)
    rating = ((avg_rating or 3.5) - 1) / 4
    parts["feedback"] = (success_rate + rating) / 2 if n else 0.5

    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return Scored(resource, round(total, 4), {k: round(v, 3) for k, v in parts.items()})


def rank(store: Store, need: dict, limit: int = 5, include: int | None = None) -> tuple[list[Scored], Scored | None]:
    """need에 맞는 후보를 점수순으로. include(현재 에이전트 id)도 같은 기준으로 점수를 매겨 돌려준다."""
    terms = query_terms(need["task"])
    idf = store.idf(terms)
    candidates = store.search(need["task"], need["category"], need.get("max_price"), need["networks"], need["kinds"],
                              region=need.get("region"), auth_free=need.get("auth_pref") == "none",
                              agent_usable=need.get("auth_pref") == "agent", min_grade=need.get("min_grade"))
    feedback = store.feedback_stats_many([r["id"] for r in candidates])  # 후보마다 쿼리하지 않게 한 번에
    no_feedback = (0, 0, None)
    scored = sorted(
        (s for s in (score_resource(r, terms, idf, need["category"], store, need=need,
                                    feedback=feedback.get(r["id"], no_feedback)) for r in candidates)
         if s.resource["category"] == need["category"] or s.parts["relevance"] >= MIN_RELEVANCE_OTHER_CATEGORY),
        key=lambda s: s.score, reverse=True)
    current = None
    if include is not None:
        res = store.resource(include)
        if res is not None:
            current = score_resource(res, terms, idf, need["category"], store, need=need)
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
        if r.get("eval_grade") and (not o.get("eval_grade") or r["eval_grade"] < o["eval_grade"]):
            reasons.append(f"품질 평가 {r['eval_grade']}등급" + (f" (현재 {o['eval_grade']})" if o.get("eval_grade") else ""))
        if not o.get("active"):
            reasons.append("현재 에이전트가 목록에서 사라짐")
    return {
        "kind": r["kind"],
        "category": r["category"],
        "price_usdc": r.get("price_usdc"),
        "networks": [n for n in r["networks"].strip(",").split(",") if n],
        "payers_30d": r.get("payers_30d"),
        "quality_grade": r.get("eval_grade"),
        "score": new.score,
        "previous_score": old.score if old else None,
        "reasons": reasons,
    }


def evaluation_summary(r: dict, findings: int = 5) -> dict | None:
    if not r.get("eval_info"):
        return None
    try:
        ev = json.loads(r["eval_info"])
    except ValueError:
        return None
    return {k: ev.get(k) for k in ("kind", "score", "grade", "percentile", "static_score", "security", "coverage", "task_verified",
                                   "dimensions", "at")} | {
        "findings": [{k: f.get(k) for k in ("severity", "code", "tool", "message")} for f in (ev.get("findings") or [])[:findings]]}


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
        "usage": json.loads(r["usage_guide"]) if r.get("usage_guide") else None,  # 연결 방법·도구별 사용법·검증된 예제
        "usage_updated_at": r.get("usage_updated_at"),
        "verified_working": None if r.get("trial_ok") is None else bool(r["trial_ok"]),  # 실제 호출 시험 결과
        "evaluation": evaluation_summary(r),  # 규칙 기반 품질 평가 (축별 점수·주요 발견 사항)
        "constraints": {
            "auth_required": auth_required(r),  # None = 모름
            "auth": auth_details(r),  # 인증 방법과 따라 할 단계
            "languages": agent_languages(r),  # 도구 파라미터 + 설명문 언어
            "regions": agent_regions(r),  # 비어 있으면 전 세계 공통
            "currencies": cons.unpack(r.get("cap_currencies")),
            "tool_count": r.get("cap_tool_count"),
        },
        "score": s.score,
        "score_parts": s.parts,
    }
