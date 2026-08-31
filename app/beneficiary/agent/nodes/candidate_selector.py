"""candidate_selector 노드 (LLM 없음) — 기업 접기·쿼터 게이트·weak 승격·풀 확정.

승격은 원 분류(relevance)를 바꾸지 않고 promoted 로만 추적한다. 재탐색은
없다 — 쿼터 미달이어도 있는 만큼으로 확정하고 evaluator 가 caveats 에 명시한다.
"""

from __future__ import annotations

import logging

from beneficiary.models import Candidate, SupplyChainCandidate
from core import MARKETS
from beneficiary.agent.state import GraphState

logger = logging.getLogger(__name__)

QUOTA_PER_MARKET = 2  # 쿼터 판정 기준 (strong 기업 수)
POOL_PER_MARKET = 3  # 심사 풀 시장당 상한
MATCHED_ITEMS_CAP = 5


def _edge_items(edges: list[SupplyChainCandidate]) -> list[str]:
    merged: dict[str, None] = {}
    for edge in edges:
        for item in [*edge.disclosure_items, *edge.news_items]:
            if item:
                merged.setdefault(item, None)
    return list(merged)[:MATCHED_ITEMS_CAP]


def _fold_supply(edges: list[SupplyChainCandidate]) -> dict[str, dict]:
    """티커 단위 접기 — strong/weak 간선을 나눠 들고 시장은 간선에서 승계."""

    folded: dict[str, dict] = {}
    # gid 는 g01…g200 — 문자열 정렬은 "g100" < "g99" 라 수치로 정렬한다.
    for edge in sorted(edges, key=lambda e: int(e.gid[1:])):
        if edge.relevance not in ("strong", "weak"):
            continue
        entry = folded.setdefault(edge.ticker, {
            "name": edge.name, "company_id": edge.company_id,
            "market": edge.market,
            "strong": [], "weak": [],
        })
        entry[edge.relevance].append(edge)
    return folded


def _supply_sort_key(entry: dict):
    constituents = entry["strong"] or entry["weak"]
    count_sum = sum(e.disclosure_count + e.news_mention_count for e in constituents)
    return (-len(entry["strong"]), -count_sum, constituents[0].ticker)


def _build_supply_candidate(ticker: str, entry: dict, promoted: bool) -> Candidate:
    constituents = entry["strong"] if entry["strong"] else entry["weak"]
    lines = list(dict.fromkeys(
        f"{e.subject_name} →공급→ {e.object_name}" for e in constituents
    ))
    return Candidate(
        ticker=ticker, name=entry["name"], company_id=entry["company_id"],
        track="supply", relation_lines=lines, matched_items=_edge_items(constituents),
        relevance="strong" if entry["strong"] else "weak", promoted=promoted,
        source_edges=constituents, market=entry["market"],
    )


def select_supply_candidates(edges: list[SupplyChainCandidate]) -> list[Candidate]:
    folded = _fold_supply(edges)
    strong_entries = {t: e for t, e in folded.items() if e["strong"]}
    weak_entries = {t: e for t, e in folded.items() if not e["strong"] and e["weak"]}

    selected: list[Candidate] = []
    for market in MARKETS:
        base = sorted(
            [(t, e) for t, e in strong_entries.items() if e["market"] == market],
            key=lambda pair: _supply_sort_key(pair[1]),
        )
        pool = [_build_supply_candidate(t, e, promoted=False) for t, e in base]
        if len(pool) < QUOTA_PER_MARKET:
            promotables = sorted(
                [(t, e) for t, e in weak_entries.items() if e["market"] == market],
                key=lambda pair: _supply_sort_key(pair[1]),
            )
            for ticker, entry in promotables:
                if len(pool) >= POOL_PER_MARKET:
                    break
                pool.append(_build_supply_candidate(ticker, entry, promoted=True))
        selected.extend(pool[:POOL_PER_MARKET])
    return selected


async def select_candidates(state: GraphState) -> dict:
    if state.get("edges"):
        candidates = select_supply_candidates(state["edges"])
    else:
        candidates = []
    logger.info("후보 확정: %d개", len(candidates))
    if not candidates:
        return {"candidates": [], "status": "no_candidates",
                "reason": "선별 결과 심사할 만한 후보 기업이 남지 않았습니다."}
    return {"candidates": candidates}
