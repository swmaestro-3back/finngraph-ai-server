"""악재 트랙 — expand_rivals(Cypher, LLM 없음) / filter_rivals(LLM#2)는 Task 10.

probe(앵커 × 핵심 테마)마다 테마 겹침 경쟁사를 모아 티커 기준으로 병합하고,
앵커 밸류체인·지분 관계 1-hop 이웃을 구조적으로 배제한다(스펙 §4.4).
"""

from __future__ import annotations

import logging

from beneficiary import repository
from beneficiary.models import RivalCandidate
from beneficiary.nodes.common import apply_market_filter, derive_exclusions, MARKETS
from beneficiary.state import GraphState
from beneficiary.utils import llm
from beneficiary.utils.packer import pack_rival_filter_context
from beneficiary.utils.postprocess import apply_filter_output
from core import postgres_database

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
    앵커가 subject_name 이 된다. kid 는 병합·절단 후에 부여한다.
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
    try:
        return await _expand_rivals(state)
    except Exception as error:
        logger.exception("경쟁사 확장 실패")
        return {"rivals": [], "error": str(error)}


async def _expand_rivals(state: GraphState) -> dict:
    anchors = state["anchors"]
    plan = state["plan"]
    exclude_names, exclude_tickers = derive_exclusions(anchors, state["relation_lines"])

    # 전 subject 의 3개 관계 타입 양방향 1-hop 이웃 — 자회사·밸류체인 배제.
    # 전역 합집합인 이유: 같은 악재 뉴스의 다른 당사자 밸류체인도 동반 피해
    # 가능성이 있어 보수적으로 제외한다(스펙 §4.4 명시적 결정).
    neighbor_names = await repository.fetch_neighbor_names(
        sorted({anchor.name for anchor in anchors})
    )
    exclude_names |= neighbor_names

    rows_by_probe = []
    for probe in plan.rival_probes:
        rows = await repository.fetch_theme_rivals(
            probe.subject_name, probe.themes, sorted(exclude_names), sorted(exclude_tickers)
        )
        rows_by_probe.append((probe.subject_name, rows))

    rivals = merge_rival_rows(rows_by_probe)
    if not rivals:
        return {"rivals": []}

    async with postgres_database.connection() as conn:
        market_rows = await repository.fetch_market_info(
            conn, sorted({rival.ticker for rival in rivals})
        )
    rivals = apply_market_filter(rivals, market_rows)
    return {"rivals": truncate_and_assign_kids(rivals)}


FALLBACK_TOP_PER_MARKET = 3


def fallback_filter_rivals(rivals: list[RivalCandidate]) -> tuple[list[str], list[str]]:
    """LLM 실패·core_items 없음 시의 겹침 폴백 — 시장별 상위 3개 strong."""

    strong_ids: list[str] = []
    for market in MARKETS:
        pool = sorted(
            [rival for rival in rivals if rival.market == market],
            key=lambda r: (-r.shared_themes, r.ticker),
        )[:FALLBACK_TOP_PER_MARKET]
        strong_ids.extend(rival.kid for rival in pool)
    for rival in rivals:
        rival.relevance = "strong" if rival.kid in strong_ids else "irrelevant"
    return strong_ids, []


async def filter_rivals(state: GraphState) -> dict:
    """LLM#2(악재 트랙) — 대체 생산자 선별. 실패는 폴백으로 계속 진행."""

    rivals = state["rivals"]
    plan = state["plan"]

    output = None
    if plan.core_items:
        try:
            output = await llm.filter_rivals(pack_rival_filter_context(plan, rivals))
        except Exception:
            logger.exception("경쟁사 선별 LLM 실패 — 겹침 폴백으로 진행")

    if output is None:
        strong_ids, weak_ids = fallback_filter_rivals(rivals)
        return {"rivals": rivals, "strong_ids": strong_ids, "weak_ids": weak_ids,
                "filter_fallback": True}

    cap_weak_ids = {rival.kid for rival in rivals if not rival.supplied_items}
    strong_ids, weak_ids = apply_filter_output(
        output, {rival.kid: rival for rival in rivals}, cap_weak_ids
    )
    return {"rivals": rivals, "strong_ids": strong_ids, "weak_ids": weak_ids,
            "filter_fallback": False}
