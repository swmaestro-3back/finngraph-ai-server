"""candidate_selector — 기업 접기·쿼터·weak 승격·정렬·matched_items·트랙 병합 (DB·LLM 없음)."""

from __future__ import annotations

import pytest

from beneficiary.models import SupplyChainCandidate, ThemeCandidate, TrackOutcome
from beneficiary.agent.nodes.candidate_selector import (
    select_candidates,
    select_supply_candidates,
    POOL_PER_MARKET,
)


def _edge(gid, ticker, market="KOSPI", relevance="strong", dc=1, nc=0, items=("HBM",), name=None):
    return SupplyChainCandidate(gid=gid, root_name="루트 기업", subject_name=name or f"공급{ticker}",
                         object_name="루트 기업", ticker=ticker, name=name or f"공급{ticker}",
                         company_id=1, market=market,
                         disclosure_items=list(items), news_items=[],
                         disclosure_count=dc, news_mention_count=nc, relevance=relevance)


def _hit(tid, ticker, market="KOSPI", relevance="strong", score=0.9, stage=1):
    return ThemeCandidate(tid=tid, stage=stage, hypothesis="h", ticker=ticker,
                          name=f"회사{ticker}", company_id=1, market=market,
                          score=score, matched_themes=["테마A"],
                          matched_reasons=["[테마A] 사유"], relevance=relevance)


def test_folds_edges_per_company_and_merges_items():
    edges = [
        _edge("g01", "000001", "KOSPI", "strong", dc=2, items=("HBM",)),
        _edge("g02", "000001", "KOSPI", "strong", dc=1, items=("TC본더", "HBM")),
        _edge("g03", "000002", "KOSPI", "strong", dc=9),
        _edge("g04", "000001", "KOSPI", "weak", items=("무관",)),  # 비승격 → 구성 제외
    ]
    candidates = select_supply_candidates(edges, POOL_PER_MARKET)
    by_ticker = {c.ticker: c for c in candidates}
    c = by_ticker["000001"]
    assert [e.gid for e in c.source_edges] == ["g01", "g02"]  # gid 오름차순, weak 제외
    assert c.matched_items == ["HBM", "TC본더"]
    assert c.relevance == "strong" and c.promoted is False
    assert c.relation_lines == ["공급000001 →공급→ 루트 기업"]


def test_ranking_strong_count_then_countsum_then_ticker():
    edges = [
        _edge("g01", "000001", "KOSPI", "strong", dc=1),
        _edge("g02", "000001", "KOSPI", "strong", dc=1),  # strong 2개
        _edge("g03", "000002", "KOSPI", "strong", dc=9),
        _edge("g04", "000003", "KOSPI", "strong", dc=9),  # g03 과 전부 동점 → ticker
        _edge("g05", "000004", "KOSDAQ", "strong", dc=1),
    ]
    candidates = select_supply_candidates(edges, POOL_PER_MARKET)
    kospi = [c.ticker for c in candidates if c.market == "KOSPI"]
    assert kospi == ["000001", "000002", "000003"]  # strong 수 우선, 동점 ticker asc
    assert candidates[-1].market == "KOSDAQ"  # KOSPI 블록 뒤에 KOSDAQ


def test_promotes_weak_only_when_market_below_quota():
    edges = [
        _edge("g01", "000001", "KOSPI", "strong"),
        _edge("g02", "000002", "KOSPI", "strong"),   # KOSPI 쿼터 충족(2) → 승격 없음
        _edge("g03", "000003", "KOSPI", "weak"),
        _edge("g04", "000004", "KOSDAQ", "strong"),  # KOSDAQ 1개 → 미달
        _edge("g05", "000005", "KOSDAQ", "weak", dc=5),
        _edge("g06", "000006", "KOSDAQ", "weak", dc=3),
        _edge("g07", "000007", "KOSDAQ", "weak", dc=1),
        _edge("g08", "000004", "KOSDAQ", "weak", items=("보조",)),  # 기선정 기업 weak — 승격 단위 아님
    ]
    candidates = select_supply_candidates(edges, POOL_PER_MARKET)
    kospi = [c.ticker for c in candidates if c.market == "KOSPI"]
    kosdaq = [(c.ticker, c.promoted) for c in candidates if c.market == "KOSDAQ"]
    assert kospi == ["000001", "000002"]  # weak 000003 승격 안 됨
    # 미달 시장만 시장당 POOL_PER_MARKET(4)개까지 승격 (dc 순): 000004(strong) + 000005·6·7
    assert kosdaq == [("000004", False), ("000005", True), ("000006", True), ("000007", True)]
    promoted = {c.ticker: c for c in candidates}["000005"]
    assert promoted.relevance == "weak"  # 원 등급 유지


def test_market_zero_still_proceeds():
    edges = [_edge("g01", "000001", "KOSPI", "strong")]
    candidates = select_supply_candidates(edges, POOL_PER_MARKET)
    assert len(candidates) == 1  # KOSDAQ 0개여도 진행 (caveats 는 evaluator 소관)


@pytest.mark.asyncio
async def test_overlapping_ticker_becomes_both_and_frees_a_theme_slot():
    """두 축이 같은 기업을 지목하면 병합하고, theme 은 다음 후보로 슬롯을 채운다."""
    edges = [_edge("g01", "000001", market="KOSPI", relevance="strong")]
    hits = [_hit("t01", "000001"), _hit("t02", "000002"), _hit("t03", "000003")]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})
    by_ticker = {c.ticker: c for c in result["candidates"]}

    assert by_ticker["000001"].track == "both"
    assert by_ticker["000001"].matched_reasons == ["[테마A] 사유"]
    # t01 이 병합됐으므로 theme 슬롯 2개는 t02·t03 이 채운다
    assert {"000002", "000003"} <= set(by_ticker)


@pytest.mark.asyncio
async def test_overlap_does_not_raise_grade():
    """track='both' 로 병합돼도 등급은 supply 선정 시점 등급을 유지한다 — 코드가 확신을 지어내지 않는다."""
    edges = [_edge("g01", "000001", market="KOSPI", relevance="strong")]
    hits = [_hit("t01", "000001", relevance="strong")]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})
    merged = {c.ticker: c for c in result["candidates"]}["000001"]
    assert merged.track == "both"
    assert merged.relevance == "strong"  # supply 가 이미 strong — theme 병합이 등급을 바꾸지 않음
    assert merged.promoted is False


@pytest.mark.asyncio
async def test_empty_track_lets_the_other_absorb_up_to_pool_per_market():
    hits = [_hit(f"t{i:02d}", f"00000{i}") for i in range(1, 6)]

    result = await select_candidates({"edges": [], "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(status="no_pool"),
                                      "theme_outcome": TrackOutcome()})

    kospi = [c for c in result["candidates"] if c.market == "KOSPI"]
    assert len(kospi) == 4  # POOL_PER_MARKET


@pytest.mark.asyncio
async def test_both_tracks_empty_yields_no_pool_with_merged_reason():
    result = await select_candidates({
        "edges": [], "theme_hits": [],
        "supply_outcome": TrackOutcome(status="no_pool", reason="공급망 사유"),
        "theme_outcome": TrackOutcome(status="no_pool", reason="테마 사유"),
    })
    assert result["status"] == "no_pool"
    assert "공급망 사유" in result["reason"] and "테마 사유" in result["reason"]


@pytest.mark.asyncio
async def test_both_tracks_failed_is_error_not_no_pool():
    result = await select_candidates({
        "edges": [], "theme_hits": [],
        "supply_outcome": TrackOutcome(error="neo4j down"),
        "theme_outcome": TrackOutcome(error="vector index missing"),
    })
    assert result.get("error")
    assert result.get("status") != "no_pool"


@pytest.mark.asyncio
async def test_raw_candidates_but_nothing_survives_selection_is_no_candidates():
    """edges/theme_hits 는 있었지만 relevance 가 전부 irrelevant 라 풀에 아무도 안 남는 경우."""
    edges = [_edge("g01", "000001", market="KOSPI", relevance="irrelevant")]
    hits = [_hit("t01", "000002", relevance="irrelevant")]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})
    assert result["status"] == "no_candidates"
    assert result["candidates"] == []
