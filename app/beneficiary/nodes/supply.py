"""호재 트랙 — expand_supply(Cypher, LLM 없음) / filter_supply(LLM#2)는 Task 10.

각 상장 앵커의 유입 SUPPLIES_TO 1-hop 을 모아 시장 필터 → 총량 절단 → gid
부여까지 결정적으로 처리한다(스펙 §4.2). 매칭은 name 기반 — 그래프의 자연키가
name 이고 노드 ticker 는 시드 지연으로 빌 수 있다.
"""

from __future__ import annotations

import logging

from beneficiary import repository
from beneficiary.models import SupplyChainCandidate
from beneficiary.nodes.common import apply_market_filter, derive_exclusions
from beneficiary.state import GraphState
from core import postgres_database

logger = logging.getLogger(__name__)

SUPPLY_POOL_CAP = 200  # LLM#2 입력 보호 — 초과분은 (dc+nc) desc, ticker asc 로 절단


def build_edge_candidates(rows_by_anchor: list[tuple[int, str, list[dict]]]) -> list[SupplyChainCandidate]:
    """(anchor_index, anchor_name, rows) → SupplyChainCandidate — (subject, object) 중복 제거."""

    seen: set[tuple[str, str]] = set()
    edges: list[SupplyChainCandidate] = []
    for anchor_index, anchor_name, rows in rows_by_anchor:
        for row in rows:
            key = (row["subject_name"], row["object_name"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(SupplyChainCandidate(
                gid=None,
                anchor_name=anchor_name,
                subject_name=row["subject_name"],
                object_name=row["object_name"],
                ticker=row["ticker"],
                name=row["name"],
                company_id=row["company_id"],
                disclosure_items=list(row["disclosure_items"] or []),
                news_items=list(row["news_items"] or []),
                disclosure_count=row["disclosure_count"],
                news_mention_count=row["news_mention_count"],
                last_mentioned_at=(str(row["last_mentioned_at"])
                                   if row["last_mentioned_at"] is not None else None),
                anchor_index=anchor_index,
            ))
    return edges


def truncate_and_assign_gids(edges: list[SupplyChainCandidate]) -> list[SupplyChainCandidate]:
    """총량 절단(상한 200) 후 최종 정렬·gid 부여 — 전부 결정적.

    절단: (disclosure+news) 내림차순, 동점 ticker 오름차순.
    최종 정렬: 앵커 순 → disclosure_count 내림차순 → ticker 오름차순.
    """

    if len(edges) > SUPPLY_POOL_CAP:
        logger.info("공급 간선 절단: %d → %d", len(edges), SUPPLY_POOL_CAP)
        edges = sorted(
            edges,
            key=lambda e: (-(e.disclosure_count + e.news_mention_count), e.ticker),
        )[:SUPPLY_POOL_CAP]

    edges = sorted(edges, key=lambda e: (e.anchor_index, -e.disclosure_count, e.ticker))
    for index, edge in enumerate(edges, start=1):
        edge.gid = f"g{index:02d}"
    return edges


async def expand_supply(state: GraphState) -> dict:
    try:
        return await _expand_supply(state)
    except Exception as error:
        logger.exception("공급망 확장 실패")
        return {"edges": [], "error": str(error)}


async def _expand_supply(state: GraphState) -> dict:
    anchors = state["anchors"]
    exclude_names, exclude_tickers = derive_exclusions(anchors, state["relation_lines"])

    rows_by_anchor = []
    for index, anchor in enumerate(anchors):
        rows = await repository.fetch_supply_neighbors_by_name(
            anchor.name, sorted(exclude_names), sorted(exclude_tickers)
        )
        rows_by_anchor.append((index, anchor.name, rows))

    edges = build_edge_candidates(rows_by_anchor)
    if not edges:
        return {"edges": []}

    async with postgres_database.connection() as conn:
        market_rows = await repository.fetch_market_info(
            conn, sorted({edge.ticker for edge in edges})
        )
    edges = apply_market_filter(edges, market_rows)
    return {"edges": truncate_and_assign_gids(edges)}
