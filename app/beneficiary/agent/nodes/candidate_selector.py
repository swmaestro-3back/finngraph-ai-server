"""candidate_selector 노드 (LLM 없음) — 기업 접기·쿼터 게이트·weak 승격·풀 확정.

승격은 원 분류(relevance)를 바꾸지 않고 promoted 로만 추적한다. 재탐색은
없다 — 쿼터 미달이어도 있는 만큼으로 확정하고 evaluator 가 caveats 에 명시한다.
"""

from __future__ import annotations

import logging

from beneficiary.models import Candidate, SupplyChainCandidate, ThemeCandidate, TrackOutcome
from core import MARKETS
from beneficiary.agent.state import GraphState

logger = logging.getLogger(__name__)

QUOTA_PER_MARKET = 2  # 쿼터 판정 기준 (strong 기업 수)
POOL_PER_TRACK_PER_MARKET = 2  # 트랙 기본 슬롯
POOL_PER_MARKET = 4  # 시장 총 상한 — 한 트랙이 못 채우면 다른 쪽이 흡수
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


def select_supply_candidates(
    edges: list[SupplyChainCandidate], cap_per_market: int
) -> list[Candidate]:
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
                if len(pool) >= cap_per_market:
                    break
                pool.append(_build_supply_candidate(ticker, entry, promoted=True))
        selected.extend(pool[:cap_per_market])
    return selected


def _theme_sort_key(hit: ThemeCandidate):
    """stage 우선 — 2차 파급이 우연한 고유사도로 1차를 앞서지 않게 한다."""
    return (hit.stage, -hit.score, hit.ticker)


def _build_theme_candidate(hit: ThemeCandidate, promoted: bool) -> Candidate:
    return Candidate(
        ticker=hit.ticker, name=hit.name, company_id=hit.company_id,
        track="theme",
        relation_lines=[f"시나리오(stage {hit.stage}): {hit.hypothesis}"],
        matched_items=[], relevance="weak" if promoted else "strong",
        promoted=promoted, market=hit.market,
        hypothesis=hit.hypothesis, stage=hit.stage, theme_score=hit.score,
        matched_themes=hit.matched_themes, matched_reasons=hit.matched_reasons,
    )


def merge_into_supply(candidate: Candidate, hit: ThemeCandidate) -> None:
    """두 축이 같은 기업을 지목했다 — 근거를 합치고 both 로 표시한다.

    등급은 올리지 않는다. 판단은 evaluator 가 하고 코드는 근거만 싣는다(스펙 §7.2).
    """

    candidate.track = "both"
    candidate.hypothesis = hit.hypothesis
    candidate.stage = hit.stage
    candidate.theme_score = hit.score
    candidate.matched_themes = hit.matched_themes
    candidate.matched_reasons = hit.matched_reasons
    candidate.relation_lines.append(f"시나리오(stage {hit.stage}): {hit.hypothesis}")


def select_theme_candidates(
    hits: list[ThemeCandidate], taken: dict[str, Candidate], cap_per_market: int
) -> list[Candidate]:
    """supply 선발분에 없는 티커만 자기 슬롯에 채운다 — 겹치면 병합한다.

    병합은 슬롯을 쓰지 않는다: taken 에 있는 히트는 strong·weak·정렬 위치와
    무관하게 전부 접는다(그렇지 않으면 cap 도달로 인한 break 가 뒤에 오는
    병합 대상을 통째로 삼킨다). 채움은 taken 이 아닌 히트만으로, 시장당
    상한까지 별도로 진행한다.
    """

    selected: list[Candidate] = []
    for market in MARKETS:
        strong = sorted([h for h in hits if h.market == market and h.relevance == "strong"],
                        key=_theme_sort_key)
        weak = sorted([h for h in hits if h.market == market and h.relevance == "weak"],
                      key=_theme_sort_key)

        # 교집합 병합 — 용량(cap)·등급(strong/weak)과 무관하게 전부 접는다.
        for hit in [*strong, *weak]:
            if hit.ticker in taken:
                merge_into_supply(taken[hit.ticker], hit)

        pool: list[Candidate] = []
        for hit in strong:
            if hit.ticker in taken:
                continue
            if len(pool) >= cap_per_market:
                break
            pool.append(_build_theme_candidate(hit, promoted=False))
        if len(pool) < QUOTA_PER_MARKET:
            for hit in weak:
                if hit.ticker in taken or len(pool) >= cap_per_market:
                    continue
                pool.append(_build_theme_candidate(hit, promoted=True))
        selected.extend(pool[:cap_per_market])
    return selected


async def select_candidates(state: GraphState) -> dict:
    supply_outcome = state.get("supply_outcome") or TrackOutcome()
    theme_outcome = state.get("theme_outcome") or TrackOutcome()
    edges = state.get("edges") or []
    hits = state.get("theme_hits") or []

    # 두 축이 모두 장애면 "후보 없음"이 아니라 장애다 — 503 으로 나가야 한다(§7.0).
    if not edges and not hits and supply_outcome.error and theme_outcome.error:
        return {"candidates": [],
                "error": f"supply: {supply_outcome.error} / theme: {theme_outcome.error}"}

    if not edges and not hits:
        # 한쪽만 장애면 no_pool 로 계속 진행하되(다른 쪽은 정상 조기 종료일 수
        # 있다), 장애 원문은 사용자용 reason 에 넣지 않고 로그로만 남긴다.
        for label, outcome in (("supply", supply_outcome), ("theme", theme_outcome)):
            if outcome.error:
                logger.warning("%s 트랙 장애(no_pool 로 계속): %s", label, outcome.error)
        reasons = [o.reason for o in (supply_outcome, theme_outcome) if o.reason]
        return {"candidates": [], "status": "no_pool",
                "reason": " ".join(reasons) or "탐색된 후보 기업이 없습니다."}

    # 한 트랙이 비면 다른 쪽이 시장 총 상한까지 흡수한다 — 부분 성공이 자동
    # 처리되어 별도 분기가 필요 없다(§7.1).
    supply_cap = POOL_PER_TRACK_PER_MARKET if hits else POOL_PER_MARKET
    theme_cap = POOL_PER_TRACK_PER_MARKET if edges else POOL_PER_MARKET

    # supply 를 먼저 뽑는다 — 그래프 간선 근거가 벡터 유사도보다 단단하다(§7.2).
    supply = select_supply_candidates(edges, supply_cap)
    taken = {c.ticker: c for c in supply}
    theme = select_theme_candidates(hits, taken, theme_cap)

    candidates = supply + theme
    logger.info("후보 확정: supply %d + theme %d = %d개",
                len(supply), len(theme), len(candidates))
    if not candidates:
        return {"candidates": [], "status": "no_candidates",
                "reason": "선별 결과 심사할 만한 후보 기업이 남지 않았습니다."}
    return {"candidates": candidates}
