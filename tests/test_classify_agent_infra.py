"""에이전트 인프라(agent_infra) 분류 정확도 회귀 테스트.

tests/data/agent_infra_labels.json: 키워드 분류기가 agent_infra로 넣었던 535개를 이름·설명으로 하나씩 판정한 결과
(2026-10-13, correct 349 / misclassified 123 / borderline 63). 분류 규칙을 바꿀 때 이 정확도가 떨어지면 실패한다.
- 정밀도: agent_infra로 분류한 것 중 실제로 인프라인 비율 (경계 사례 제외)
- 재현율: 실제 인프라 349개 중 agent_infra로 남은 비율
처음 규칙: 정밀도 73.9%, 재현율 100%. 지금 규칙(약한 표현·제외 문맥): 정밀도 84.9%, 재현율 98.3%.
"""

import json
from pathlib import Path

from agent_market.gateway.classify import classify

DATA = json.loads((Path(__file__).parent / "data" / "agent_infra_labels.json").read_text())


def _metrics():
    tp = fp = fn = 0
    for o in DATA:
        if o["label"] == "borderline":
            continue
        infra = classify(o["text"]) == "agent_infra"
        if o["label"] == "correct":
            tp += infra
            fn += not infra
        else:
            fp += infra
    return tp / (tp + fp), tp / (tp + fn), fp


def test_dataset_shape():
    labels = {o["label"] for o in DATA}
    assert labels == {"correct", "misclassified", "borderline"} and len(DATA) == 535


def test_agent_infra_precision_and_recall():
    precision, recall, fp = _metrics()
    assert precision >= 0.84, f"precision {precision:.1%}"
    assert recall >= 0.97, f"recall {recall:.1%}"
    assert fp <= 65  # 처음 123개 → 61개


def test_typical_misclassifications_are_fixed():
    cases = [
        "Daily News AI Gateway MCP gateway for dailynews.example.com: articles, search and full text.",
        "Council of Five: five specialised AI agents vote in a multi-agent process to give a market view on BTC.",
        "A2A Grocery Agent-to-Agent (A2A) hub for groceries: fresh produce, dairy, bakery.",
        "Advertise To Agents Buy ad placements so AI agents see your products first.",
        "Football Agent Index directory of licensed football agents and their players.",
        "Agentic commerce MCP for our shoe store: browse products and check out.",
    ]
    for text in cases:
        assert classify(text) != "agent_infra", text


def test_real_agent_infra_still_detected():
    cases = [
        "Zero-secret MCP gateway for AI agents: risk-scored, audited calls with human-in-the-loop approval.",
        "HiveClear Multi-agent settlement and clearing with validator consensus.",
        "AgentIndex: search 15K+ MCP services, A2A agents and x402 APIs from 5 registries.",
        "Hosted agent memory with provenance and snapshot rollback.",
        "Free public message board where AI agents and swarms coordinate.",
    ]
    for text in cases:
        assert classify(text) == "agent_infra", text
