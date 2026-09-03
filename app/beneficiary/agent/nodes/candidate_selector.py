"""candidate_selector 노드 (LLM 없음) — 쿼터 게이트·weak 승격·트랙 병합·풀 확정.

두 트랙 모두 **기업 단위** 원시 후보를 올린다 — 간선 병합은 supply 서브그래프의
merge_edges_by_company 가 끝냈다. 이 노드는 그 둘을 티커로 합치고 슬롯을 배분한다.

승격은 원 분류(relevance)를 바꾸지 않고 promoted 로만 추적한다. 재탐색은
없다 — 쿼터 미달이어도 있는 만큼으로 확정하고 evaluator 가 caveats 에 명시한다.

슬롯 배분 순서(§7.1·§7.2):
  ① supply 를 시장 총 상한까지 뽑아 기본 슬롯분(base)과 흡수분(extra)으로 가른다
  ② 교집합을 supply 전량에 대해 먼저 병합한다 — 병합은 슬롯을 쓰지 않는다
  ③ theme 은 base·병합 흡수분이 쓰고 남은 실제 잔여 슬롯만큼 채운다
  ④ 그러고도 남은 슬롯을 나머지 supply 흡수분이 가져간다
흡수 기준은 원시 리스트의 유무가 아니라 **선발 결과**다 — 원시 행만 내고
후보를 0개 낸 트랙이 슬롯을 붙들지 못하게 하는 것이 이 순서의 요점이다.
"""

from __future__ import annotations

import logging
from collections import Counter

from beneficiary.models import (
    Candidate,
    SupplyCandidate,
    SupplyEdgeCandidate,
    SupplySubgraphResult,
    ThemeCandidate,
    ThemeSubgraphResult,
)
from core import MARKETS
from beneficiary.agent.state import GraphState

logger = logging.getLogger(__name__)

QUOTA_PER_MARKET = 2  # weak 승격 트리거 — 트랙별로 판정한다
POOL_PER_TRACK_PER_MARKET = 2  # 명목 트랙 슬롯 (스펙 §7.1 의 supply 2 + theme 2)
POOL_PER_MARKET = 4  # 시장 총 상한 — 한 트랙이 못 채우면 다른 쪽이 흡수
MATCHED_ITEMS_CAP = 5


def _edge_items(supply_candidates: list[SupplyEdgeCandidate]) -> list[str]:
    merged: dict[str, None] = {}
    for edge in supply_candidates:
        for item in [*edge.disclosure_items, *edge.news_items]:
            if item:
                merged.setdefault(item, None)
    return list(merged)[:MATCHED_ITEMS_CAP]


def _supply_sort_key(source: SupplyCandidate):
    """strong 간선 수 우선 — 관련 품목으로 여러 루트에 납품할수록 노출이 넓다.

    weak 후보는 strong 간선이 0개이므로 첫 키가 항상 0이다(구성 간선 수가
    승격 후보를 strong 앞으로 밀지 않는다).
    """

    strong_count = len(source.edges) if source.relevance == "strong" else 0
    count_sum = sum(e.disclosure_count + e.news_mention_count for e in source.edges)
    return (-strong_count, -count_sum, source.ticker)


def _build_supply_candidate(source: SupplyCandidate, promoted: bool) -> Candidate:
    lines = list(dict.fromkeys(
        f"{e.supplier_name} →공급→ {e.root_name}" for e in source.edges
    ))
    return Candidate(
        ticker=source.ticker, name=source.name, company_id=source.company_id,
        track="supply", relation_lines=lines, matched_items=_edge_items(source.edges),
        relevance=source.relevance, promoted=promoted,
        source_edges=source.edges, market=source.market,
    )


def select_supply_candidates(
    supply_candidates: list[SupplyCandidate], cap_per_market: int
) -> list[Candidate]:
    selected: list[Candidate] = []
    for market in MARKETS:
        in_market = [c for c in supply_candidates if c.market == market]
        base = sorted([c for c in in_market if c.relevance == "strong"],
                      key=_supply_sort_key)
        pool = [_build_supply_candidate(c, promoted=False) for c in base]
        if len(pool) < QUOTA_PER_MARKET:
            promotables = sorted([c for c in in_market if c.relevance == "weak"],
                                 key=_supply_sort_key)
            for source in promotables:
                if len(pool) >= cap_per_market:
                    break
                pool.append(_build_supply_candidate(source, promoted=True))
        selected.extend(pool[:cap_per_market])
    return selected


def _by_market(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    """선발 순서를 보존한 시장별 묶음 — 시장은 MARKETS 로 고정한다."""

    grouped: dict[str, list[Candidate]] = {market: [] for market in MARKETS}
    for candidate in candidates:
        grouped[candidate.market].append(candidate)
    return grouped


def _theme_sort_key(source: ThemeCandidate):
    """stage 우선 — 2차 파급이 우연한 고유사도로 1차를 앞서지 않게 한다."""
    return (source.stage, -source.score, source.ticker)


def _build_theme_candidate(source: ThemeCandidate, promoted: bool) -> Candidate:
    return Candidate(
        ticker=source.ticker, name=source.name, company_id=source.company_id,
        track="theme",
        relation_lines=[f"시나리오(stage {source.stage}): {source.hypothesis}"],
        matched_items=[], relevance="weak" if promoted else "strong",
        promoted=promoted, market=source.market,
        hypothesis=source.hypothesis, stage=source.stage, theme_score=source.score,
        # 복사해서 싣는다 — 참조로 넘기면 Candidate 와 ThemeCandidate 가 같은
        # 리스트를 공유해 한쪽 수정이 다른 쪽에 새는 앨리어싱 위험이 남는다.
        matched_themes=list(source.matched_themes),
        matched_reasons=list(source.matched_reasons),
    )


def merge_into_supply(candidate: Candidate, source: ThemeCandidate) -> None:
    """두 축이 같은 기업을 지목했다 — 근거를 합치고 both 로 표시한다.

    등급은 올리지 않는다. 판단은 evaluator 가 하고 코드는 근거만 싣는다(스펙 §7.2).
    """

    candidate.track = "both"
    candidate.hypothesis = source.hypothesis
    candidate.stage = source.stage
    candidate.theme_score = source.score
    candidate.matched_themes = list(source.matched_themes)
    candidate.matched_reasons = list(source.matched_reasons)
    candidate.relation_lines.append(f"시나리오(stage {source.stage}): {source.hypothesis}")


def merge_theme_candidates_into_supply(
    theme_candidates: list[ThemeCandidate], taken: dict[str, Candidate]
) -> set[str]:
    """supply 가 이미 뽑은 티커를 지목한 테마 후보를 전부 접는다 — 병합 티커를 돌려준다.

    병합은 슬롯 배분과 완전히 독립이다(§7.2): 용량·등급·정렬 위치와 무관하게
    전부 접는다. 슬롯 루프 안에서 하면 cap 도달로 인한 break 가 뒤에 오는
    병합 대상을 통째로 삼킨다.
    """

    merged: set[str] = set()
    for theme_candidate in sorted(theme_candidates, key=_theme_sort_key):
        # irrelevant 는 병합하지 않는다
        if theme_candidate.relevance not in ("strong", "weak"):
            continue
        target = taken.get(theme_candidate.ticker)
        if target is not None:
            merge_into_supply(target, theme_candidate)
            merged.add(theme_candidate.ticker)
    return merged


def select_theme_candidates(
    theme_candidates: list[ThemeCandidate], taken: dict[str, Candidate],
    caps: dict[str, int],
) -> list[Candidate]:
    """supply 선발분에 없는 티커만 자기 슬롯에 채운다.

    caps 는 시장별 잔여 슬롯이다 — supply 가 그 시장에서 실제로 몇 개를
    확정했는지에서 계산된다(스펙 §7.1 의 "실제 부족분 흡수"). 교집합 병합은
    호출 전에 merge_theme_candidates_into_supply 가 이미 끝냈다.
    """

    selected: list[Candidate] = []
    for market in MARKETS:
        cap_per_market = caps.get(market, 0)
        strong = sorted(
            [c for c in theme_candidates if c.market == market and c.relevance == "strong"],
            key=_theme_sort_key)
        weak = sorted(
            [c for c in theme_candidates if c.market == market and c.relevance == "weak"],
            key=_theme_sort_key)

        pool: list[Candidate] = []
        for theme_candidate in strong:
            if theme_candidate.ticker in taken:
                continue
            if len(pool) >= cap_per_market:
                break
            pool.append(_build_theme_candidate(theme_candidate, promoted=False))
        if len(pool) < QUOTA_PER_MARKET:
            for theme_candidate in weak:
                if theme_candidate.ticker in taken or len(pool) >= cap_per_market:
                    continue
                pool.append(_build_theme_candidate(theme_candidate, promoted=True))
        selected.extend(pool[:cap_per_market])
    return selected


async def select_candidates(state: GraphState) -> dict:
    supply = state.get("supply_result") or SupplySubgraphResult()
    theme = state.get("theme_result") or ThemeSubgraphResult()

    # 두 축이 모두 장애면 "후보 없음"이 아니라 장애다 — 503 으로 나가야 한다(§7.0).
    # 리스트 상태보다 **먼저** 판정한다: 리스트가 비었는지에 이 보장을 걸면
    # 원시 리스트를 남긴 채 실패한 단계에서 분기가 통째로 죽는다.
    if supply.error and theme.error:
        return {"candidates": [],
                "error": f"supply: {supply.error} / theme: {theme.error}"}

    supply_candidates = supply.candidates
    theme_candidates = theme.candidates

    if not supply_candidates and not theme_candidates:
        # 한쪽만 장애면 no_pool 로 계속 진행하되(다른 쪽은 정상 조기 종료일 수
        # 있다), 장애 원문은 사용자용 reason 에 넣지 않고 로그로만 남긴다.
        for label, result in (("supply", supply), ("theme", theme)):
            if result.error:
                logger.warning("%s 트랙 장애(no_pool 로 계속): %s", label, result.error)
        reasons = [r.reason for r in (supply, theme) if r.reason]
        return {"candidates": [], "status": "no_pool",
                "reason": " ".join(reasons) or "탐색된 후보 기업이 없습니다."}

    # supply 를 먼저 뽑는다 — 그래프 간선 근거가 벡터 유사도보다 단단하다(§7.2).
    # 흡수는 **선발 결과의 실제 시장별 부족분**으로 계산한다(§7.1). 원시
    # 리스트의 유무(bool(supply_candidates)/bool(theme_candidates))를 대리 지표로 쓰면, 원시 행은
    # 냈지만 후보를 0개 낸 트랙이 슬롯을 붙들고 있게 된다 — filter 가 전부
    # irrelevant 로 판정한 경우, filter 단계가 실패한 경우, filter_supply 의
    # 핵심 품목 부재 조기 종료가 모두 그 경로다.
    supply_by_market = _by_market(
        select_supply_candidates(supply_candidates, POOL_PER_MARKET)
    )
    # 기본 슬롯분은 supply 가 확보하고, 그 너머(흡수분)는 theme 이 실제로 못
    # 채운 만큼만 가져간다 — 승격된 weak 공급사가 strong 테마 후보를 밀어내지
    # 않게 하는 경계다.
    base = {m: cs[:POOL_PER_TRACK_PER_MARKET] for m, cs in supply_by_market.items()}
    extra = {m: cs[POOL_PER_TRACK_PER_MARKET:] for m, cs in supply_by_market.items()}

    # 병합은 슬롯 배분보다 먼저, 흡수분까지 포함한 supply 전량을 대상으로 한다 —
    # 두 축이 같은 기업을 지목했는데 supply 근거를 떨어뜨리면 안 된다(§7.2).
    taken = {c.ticker: c for cs in supply_by_market.values() for c in cs}
    merged_tickers = merge_theme_candidates_into_supply(theme_candidates, taken)

    # 병합된 흡수분(both)은 두 축 근거를 다 실었으므로 슬롯을 갖고 살아남는다.
    merged_extra = {m: [c for c in extra[m] if c.ticker in merged_tickers] for m in MARKETS}
    theme_caps = {m: POOL_PER_MARKET - len(base[m]) - len(merged_extra[m]) for m in MARKETS}
    theme = select_theme_candidates(theme_candidates, taken, theme_caps)

    # theme 이 남긴 잔여 슬롯을 나머지 supply 흡수분이 채운다.
    theme_per_market = Counter(c.market for c in theme)
    supply: list[Candidate] = []
    for market in MARKETS:
        room = (POOL_PER_MARKET - len(base[market])
                - len(merged_extra[market]) - theme_per_market[market])
        plain = [c for c in extra[market] if c.ticker not in merged_tickers][:max(room, 0)]
        keep = {c.ticker for c in [*merged_extra[market], *plain]}
        # 흡수분은 원래 선발 순서를 지킨다 — 병합 여부로 순서가 바뀌지 않는다.
        supply.extend([*base[market], *(c for c in extra[market] if c.ticker in keep)])

    candidates = supply + theme
    logger.info("후보 확정: supply %d + theme %d = %d개",
                len(supply), len(theme), len(candidates))
    if not candidates:
        return {"candidates": [], "status": "no_candidates",
                "reason": "선별 결과 심사할 만한 후보 기업이 남지 않았습니다."}
    return {"candidates": candidates}
