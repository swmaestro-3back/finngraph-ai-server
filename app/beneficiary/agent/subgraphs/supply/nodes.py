"""
1. 간선 조회
2. 간선 기준으로 필터링
3. 기업 기준으로 간선들을 묶어 부모에게 반환
"""

from __future__ import annotations

import asyncio
import logging

from beneficiary import repository
from beneficiary.models import SupplyCandidate, SupplyEdgeCandidate
from beneficiary.agent.nodes.common import derive_exclusions
from beneficiary.agent.subgraphs.supply.state import SupplyTrackState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_supply_filter_context
from beneficiary.agent.utils.postprocess import apply_filter_output

logger = logging.getLogger(__name__)

EDGE_POOL_CAP = 20  # 기업별 병합 전, 판정에 올리는 최대 간선 수 — LLM#2 입력 보호


def build_edge_candidates(rows_by_root: list[tuple[int, str, list[dict]]]) -> list[SupplyEdgeCandidate]:
    """fetch_supply_neighbors_by_name으로 조회된 row들을 SupplyEdgeCandidate 모델로 변환 — (공급사, 루트) 중복 제거."""

    seen: set[tuple[str, str]] = set()
    edges: list[SupplyEdgeCandidate] = []
    for root_index, root_name, rows in rows_by_root:
        for row in rows:
            key = (row["name"], root_name)
            if key in seen:
                continue
            seen.add(key)
            edges.append(SupplyEdgeCandidate(
                gid=None,
                root_name=root_name,
                supplier_name=row["name"],
                supplier_ticker=row["ticker"],
                supplier_id=row["company_id"],
                supplier_market=row["market"],
                disclosure_items=list(row["disclosure_items"] or []),
                news_items=list(row["news_items"] or []),
                disclosure_count=row["disclosure_count"],
                news_mention_count=row["news_mention_count"],
                last_mentioned_at=(str(row["last_mentioned_at"])
                                   if row["last_mentioned_at"] is not None else None),
                root_index=root_index,
            ))
    return edges


def truncate_and_assign_gids(
    edges: list[SupplyEdgeCandidate],
) -> list[SupplyEdgeCandidate]:
    """총량 절단(상한 100) 후 최종 정렬·gid 부여 — 전부 결정적.

    절단: (disclosure+news) 내림차순, 동점 ticker 오름차순.
    최종 정렬: 루트 기업 순 → disclosure_count 내림차순 → ticker 오름차순.
    """

    if len(edges) > EDGE_POOL_CAP:
        logger.info("공급 간선 절단: %d → %d", len(edges), EDGE_POOL_CAP)
        edges = sorted(
            edges,
            key=lambda e: (-(e.disclosure_count + e.news_mention_count), e.supplier_ticker),
        )[:EDGE_POOL_CAP]

    edges = sorted(edges, key=lambda e: (e.root_index, -e.disclosure_count, e.supplier_ticker))
    for index, edge in enumerate(edges, start=1):
        edge.gid = f"g{index:02d}"
    return edges


async def expand_supply(state: SupplyTrackState) -> dict:
    """
    Root Company와 1 Hop 관계에 있는 기업들과 Relationship 정보를 반환
    """
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

    edges: list[SupplyEdgeCandidate] = build_edge_candidates(rows_by_root)
    if not edges:
        return {
            "edges": []
        }

    return {
        "edges": truncate_and_assign_gids(edges)
    }


def merge_edges_by_company(edges: list[SupplyEdgeCandidate]) -> list[SupplyCandidate]:
    """판정이 끝난 간선을 티커 단위로 병합한다 — 시장·정규명은 첫 간선에서 승계.

    strong 간선이 하나라도 있으면 그 기업은 strong 이고 구성 간선도 strong 만
    남긴다 — weak 간선이 근거에 섞여 등급을 흐리지 않게 한다. irrelevant 만
    남은 기업은 여기서 사라진다.

    gid 오름차순으로 순회한다 — 구성 간선 순서가 그대로 finance_collector 의
    근거 적재 순서가 되므로 결정적이어야 한다.
    """

    merged: dict[str, dict] = {}
    # gid 는 g01…g200 — 문자열 정렬은 "g100" < "g99" 라 수치로 정렬한다.
    for edge in sorted(edges, key=lambda e: int(e.gid[1:])):
        if edge.relevance not in ("strong", "weak"):
            continue
        entry = merged.setdefault(edge.supplier_ticker, {
            "name": edge.supplier_name, "company_id": edge.supplier_id,
            "market": edge.supplier_market,
            "strong": [], "weak": [],
        })
        entry[edge.relevance].append(edge)

    return [
        SupplyCandidate(
            ticker=ticker, name=entry["name"], company_id=entry["company_id"],
            market=entry["market"],
            relevance="strong" if entry["strong"] else "weak",
            edges=entry["strong"] or entry["weak"],
        )
        for ticker, entry in merged.items()
    ]


async def filter_supply(state: SupplyTrackState) -> dict:
    """LLM#2(공급망 트랙) — 간선의 납품 품목을 사건의 핵심 품목과 대조해 선별한다.

    판정은 간선 단위, 반환은 기업 단위다(모듈 docstring 참조).
    """

    edges = state["edges"]
    plan = state["plan"]

    # 핵심 품목이 없으면 연관성을 판정할 기준 자체가 없다 — 카운트로 때우지 않는다.
    if not plan.core_items:
        return {
            "status": "no_candidates",
            "reason": "사건의 핵심 품목을 특정하지 못해 공급사를 선별할 수 없습니다."
        }

    output = await llm.filter_supply(pack_supply_filter_context(plan, edges))

    cap_weak_ids = {edge.gid for edge in edges
                    if not edge.disclosure_items and not edge.news_items}

    strong_ids, weak_ids = apply_filter_output(
        output, {edge.gid: edge for edge in edges}, cap_weak_ids
    )

    candidates = merge_edges_by_company(edges)
    logger.info("공급 후보 병합: 간선 %d개(strong %d·weak %d) → 기업 %d개",
                len(edges), len(strong_ids), len(weak_ids), len(candidates))

    return {
        "edges": edges,
        "candidates": candidates,
        "strong_ids": strong_ids,
        "weak_ids": weak_ids
    }
