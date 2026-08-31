"""악재 트랙 — expand_rivals(Cypher, LLM 없음) / filter_rivals(LLM#2).

probe(루트 기업 × 핵심 테마)마다 테마 겹침 경쟁사를 모아 티커 기준으로 병합하고,
루트 기업 밸류체인·지분 관계 1-hop 이웃을 구조적으로 배제한다(스펙 §4.4).
"""

from __future__ import annotations

import asyncio
import logging

from beneficiary import repository
from beneficiary.models import RivalCandidate
from beneficiary.agent.nodes.common import derive_exclusions
from beneficiary.agent.state import GraphState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_rival_filter_context
from beneficiary.agent.utils.postprocess import apply_filter_output

logger = logging.getLogger(__name__)

RIVAL_POOL_CAP = 60  # 병합 후 총량 상한 — LLM#2 입력 보호
ITEMS_PER_RIVAL = 10
VIA_THEMES_CAP = 5
REASONS_CAP = 3


def flatten_items(item_arrays: list, cap: int = ITEMS_PER_RIVAL) -> list[str]:
    """간선 아이템 배열들을 평탄화 — 중복 제거, 원 순서(뷰 array_agg 순) 보존."""

    seen: dict[str, None] = {}
    for array in item_arrays:
        if not array:
            continue
        for item in array:
            if item and item not in seen:
                seen[item] = None
    return list(seen)[:cap]


def _union_capped(base: list[str], extra: list[str], cap: int) -> list[str]:
    merged = dict.fromkeys([*base, *extra])
    return list(merged)[:cap]


def merge_rival_rows(rows_by_probe: list[tuple[str, list[dict]]]) -> list[RivalCandidate]:
    """probe 간 티커 병합 — shared_themes 는 최대값, 합집합은 상한 적용.

    같은 기업이 여러 probe 에서 나오면 1건으로: 최대 shared 를 준 probe 의
    루트 기업가 subject_name 이 된다. kid 는 병합·절단 후에 부여한다.
    """

    by_ticker: dict[str, RivalCandidate] = {}
    for subject_name, rows in rows_by_probe:
        for row in rows:
            supplied = flatten_items(row["item_arrays"])
            existing = by_ticker.get(row["ticker"])
            if existing is None:
                by_ticker[row["ticker"]] = RivalCandidate(
                    kid=None,
                    subject_name=subject_name,
                    ticker=row["ticker"],
                    name=row["name"],
                    company_id=row["company_id"],
                    market=row["market"],
                    shared_themes=row["shared_themes"],
                    via_themes=list(row["via_themes"])[:VIA_THEMES_CAP],
                    reasons=[r for r in row["reasons"] if r][:REASONS_CAP],
                    supplied_items=supplied,
                )
                continue
            if row["shared_themes"] > existing.shared_themes:
                existing.shared_themes = row["shared_themes"]
                existing.subject_name = subject_name
            existing.via_themes = _union_capped(existing.via_themes, list(row["via_themes"]), VIA_THEMES_CAP)
            existing.reasons = _union_capped(existing.reasons, [r for r in row["reasons"] if r], REASONS_CAP)
            existing.supplied_items = _union_capped(existing.supplied_items, supplied, ITEMS_PER_RIVAL)
    return list(by_ticker.values())


def truncate_and_assign_kids(rivals: list[RivalCandidate]) -> list[RivalCandidate]:
    """정렬(shared desc → ticker asc)·총량 절단(60)·kid 부여 — 전부 결정적."""

    rivals = sorted(rivals, key=lambda r: (-r.shared_themes, r.ticker))
    if len(rivals) > RIVAL_POOL_CAP:
        logger.info("경쟁사 후보 절단: %d → %d", len(rivals), RIVAL_POOL_CAP)
        rivals = rivals[:RIVAL_POOL_CAP]
    for index, rival in enumerate(rivals, start=1):
        rival.kid = f"k{index:02d}"
    return rivals


async def expand_rivals(state: GraphState) -> dict:
    root_companies = state["root_companies"]
    plan = state["plan"]
    exclude_names, exclude_tickers = derive_exclusions(root_companies, state["relation_lines"])

    # 전 subject 의 3개 관계 타입 양방향 1-hop 이웃 — 자회사·밸류체인 배제.
    # 전역 합집합인 이유: 같은 악재 뉴스의 다른 당사자 밸류체인도 동반 피해
    # 가능성이 있어 보수적으로 제외한다(스펙 §4.4 명시적 결정).
    neighbor_names = await repository.fetch_neighbor_names(
        sorted({root.name for root in root_companies})
    )
    exclude_names |= neighbor_names

    # probe 별 조회는 서로 독립이다 — 순차 await 하지 않는다. gather 가 입력
    # 순서를 보존하므로 probe 순 병합(최대 shared 우선)은 그대로 결정적이다.
    names, tickers = sorted(exclude_names), sorted(exclude_tickers)
    rows_per_probe = await asyncio.gather(
        *(repository.fetch_theme_rivals(probe.subject_name, probe.themes, names, tickers)
          for probe in plan.rival_probes)
    )
    rows_by_probe = [
        (probe.subject_name, rows)
        for probe, rows in zip(plan.rival_probes, rows_per_probe)
    ]

    rivals = merge_rival_rows(rows_by_probe)
    if not rivals:
        return {"rivals": [], "status": "no_pool",
                "reason": "루트 기업과 테마가 겹치는 상장 경쟁사를 그래프에서 찾지 못했습니다."}

    return {"rivals": truncate_and_assign_kids(rivals)}


async def filter_rivals(state: GraphState) -> dict:
    """LLM#2(악재 트랙) — 대체 생산자 선별. 실패는 그래프가 error 로 강등한다."""

    rivals = state["rivals"]
    plan = state["plan"]

    # 핵심 품목이 없으면 대체 생산 여부를 판정할 기준이 없다 — 겹침으로 때우지 않는다.
    if not plan.core_items:
        return {"status": "no_candidates",
                "reason": "사건의 핵심 품목을 특정하지 못해 경쟁사를 선별할 수 없습니다."}

    output = await llm.filter_rivals(pack_rival_filter_context(plan, rivals))
    cap_weak_ids = {rival.kid for rival in rivals if not rival.supplied_items}
    strong_ids, weak_ids = apply_filter_output(
        output, {rival.kid: rival for rival in rivals}, cap_weak_ids
    )
    return {"rivals": rivals, "strong_ids": strong_ids, "weak_ids": weak_ids}
