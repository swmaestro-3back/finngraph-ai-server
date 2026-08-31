"""호재 트랙 — expand_supply(Cypher, LLM 없음) / filter_supply(LLM#2).

각 상장 루트 기업의 유입 SUPPLIES_TO 1-hop 을 모아 총량 절단 → gid 부여까지
결정적으로 처리한다(스펙 §4.2). 시장·상장 필터(market·is_active)는 Cypher 가
노드 필드로 끝낸다 — 이 노드는 Neo4j 만 읽는다. 매칭은 name 기반 — 그래프의
자연키가 name 이고 노드 ticker 는 시드 지연으로 빌 수 있다.
"""

from __future__ import annotations

import asyncio
import logging

from beneficiary import repository
from beneficiary.models import SupplyChainCandidate
from beneficiary.agent.nodes.common import derive_exclusions
from beneficiary.agent.tracks.supply.state import SupplyTrackState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_supply_filter_context
from beneficiary.agent.utils.postprocess import apply_filter_output

logger = logging.getLogger(__name__)

SUPPLY_POOL_CAP = 200  # LLM#2 입력 보호 — 초과분은 (dc+nc) desc, ticker asc 로 절단


def build_edge_candidates(rows_by_root: list[tuple[int, str, list[dict]]]) -> list[SupplyChainCandidate]:
    """(root_index, root_name, rows) → SupplyChainCandidate — (subject, object) 중복 제거."""

    seen: set[tuple[str, str]] = set()
    edges: list[SupplyChainCandidate] = []
    for root_index, root_name, rows in rows_by_root:
        for row in rows:
            key = (row["subject_name"], row["object_name"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(SupplyChainCandidate(
                gid=None,
                root_name=root_name,
                subject_name=row["subject_name"],
                object_name=row["object_name"],
                ticker=row["ticker"],
                name=row["name"],
                company_id=row["company_id"],
                market=row["market"],
                disclosure_items=list(row["disclosure_items"] or []),
                news_items=list(row["news_items"] or []),
                disclosure_count=row["disclosure_count"],
                news_mention_count=row["news_mention_count"],
                last_mentioned_at=(str(row["last_mentioned_at"])
                                   if row["last_mentioned_at"] is not None else None),
                root_index=root_index,
            ))
    return edges


def truncate_and_assign_gids(edges: list[SupplyChainCandidate]) -> list[SupplyChainCandidate]:
    """총량 절단(상한 200) 후 최종 정렬·gid 부여 — 전부 결정적.

    절단: (disclosure+news) 내림차순, 동점 ticker 오름차순.
    최종 정렬: 루트 기업 순 → disclosure_count 내림차순 → ticker 오름차순.
    """

    if len(edges) > SUPPLY_POOL_CAP:
        logger.info("공급 간선 절단: %d → %d", len(edges), SUPPLY_POOL_CAP)
        edges = sorted(
            edges,
            key=lambda e: (-(e.disclosure_count + e.news_mention_count), e.ticker),
        )[:SUPPLY_POOL_CAP]

    edges = sorted(edges, key=lambda e: (e.root_index, -e.disclosure_count, e.ticker))
    for index, edge in enumerate(edges, start=1):
        edge.gid = f"g{index:02d}"
    return edges


async def expand_supply(state: SupplyTrackState) -> dict:
    root_companies = state["root_companies"]
    exclude_names, exclude_tickers = derive_exclusions(root_companies, state["relation_lines"])

    # 루트 기업별 1-hop 조회는 서로 독립이다 — 순차 await 하지 않는다.
    # gather 는 입력 순서를 보존하므로 root_index 기반 정렬은 그대로 결정적이다.
    names, tickers = sorted(exclude_names), sorted(exclude_tickers)
    rows_per_root = await asyncio.gather(
        *(repository.fetch_supply_neighbors_by_name(root.name, names, tickers)
          for root in root_companies)
    )
    rows_by_root = [
        (index, root.name, rows)
        for index, (root, rows) in enumerate(zip(root_companies, rows_per_root))
    ]

    edges = build_edge_candidates(rows_by_root)
    if not edges:
        return {"edges": []}

    return {"edges": truncate_and_assign_gids(edges)}


async def filter_supply(state: SupplyTrackState) -> dict:
    """LLM#2(호재 트랙) — 아이템 연관성 선별. 실패는 그래프가 error 로 강등한다."""

    edges = state["edges"]
    plan = state["plan"]

    # 핵심 품목이 없으면 연관성을 판정할 기준 자체가 없다 — 카운트로 때우지 않는다.
    if not plan.core_items:
        return {"status": "no_candidates",
                "reason": "사건의 핵심 품목을 특정하지 못해 공급사를 선별할 수 없습니다."}

    output = await llm.filter_supply(pack_supply_filter_context(plan, edges))
    cap_weak_ids = {edge.gid for edge in edges
                    if not edge.disclosure_items and not edge.news_items}
    strong_ids, weak_ids = apply_filter_output(
        output, {edge.gid: edge for edge in edges}, cap_weak_ids
    )
    return {"edges": edges, "strong_ids": strong_ids, "weak_ids": weak_ids}
