"""candidate_selector — 기업 접기·쿼터·weak 승격·정렬·matched_items·트랙 병합 (DB·LLM 없음)."""

from __future__ import annotations

import pytest

from beneficiary.models import SupplyChainCandidate, ThemeCandidate, TrackOutcome
from beneficiary.agent.nodes.candidate_selector import (
    select_candidates,
    select_supply_candidates,
    POOL_PER_MARKET,
    POOL_PER_TRACK_PER_MARKET,
)


def _edge(gid, ticker, market="KOSPI", relevance="strong", dc=1, nc=0, items=("HBM",), name=None):
    return SupplyChainCandidate(gid=gid, root_name="루트 기업", supplier_name=name or f"공급{ticker}",
                         supplier_ticker=ticker, supplier_id=1, supplier_market=market,
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
async def test_both_tracks_failed_is_error_even_with_raw_rows_left_in_state():
    """장애 판정은 리스트 상태에 걸리지 않는다.

    filter 단계에서 실패하면 원시 리스트가 state 에 남을 수 있었다. 그때
    `not edges and not hits` 가드가 통째로 죽어 두 축 동시 장애가 200 +
    "심사할 후보가 없습니다"로 나갔다 — 전면 Bedrock 장애가 모니터링에서
    보이지 않게 되는 경로다.
    """
    edges = [_edge("g01", "000001")]          # relevance 는 붙지 못한 채 남은 원시 행
    hits = [_hit("t01", "000002")]

    result = await select_candidates({
        "edges": edges, "theme_hits": hits,
        "supply_outcome": TrackOutcome(error="bedrock timeout"),
        "theme_outcome": TrackOutcome(error="bedrock timeout"),
    })

    assert result.get("error")
    assert "bedrock timeout" in result["error"]
    assert result.get("status") is None
    assert result["candidates"] == []


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


@pytest.mark.asyncio
async def test_merge_happens_even_when_taken_ticker_sorts_after_cap():
    """cap 도달로 인한 break 가 뒤에 오는 병합 대상까지 삼키면 안 된다 (fix round 1, finding 1)."""
    # supply 가 기본 슬롯을 꽉 채워야 theme cap 이 POOL_PER_TRACK_PER_MARKET 로
    # 좁아지고 break 가 실제로 걸린다.
    edges = [_edge("g01", "000001", market="KOSPI", relevance="strong"),
             _edge("g02", "000009", market="KOSPI", relevance="strong")]
    # cap 개의 non-taken 히트로 pool 을 채우고, 그다음 non-taken 히트에서 break 가
    # 걸린 뒤에야 taken 히트(000001)가 오도록 정렬 점수를 낮춰 맨 뒤에 둔다.
    fillers = [_hit(f"t{i:02d}", f"00000{i + 2}", score=0.99 - i * 0.01)
               for i in range(POOL_PER_TRACK_PER_MARKET + 1)]
    taken_hit = _hit("t99", "000001", score=0.01)  # 가장 낮은 점수 → 정렬상 맨 뒤
    hits = [*fillers, taken_hit]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})
    by_ticker = {c.ticker: c for c in result["candidates"]}
    assert by_ticker["000001"].track == "both"  # cap 도달 뒤에도 병합은 일어난다
    filler_tickers = {h.ticker for h in fillers}
    assert len(filler_tickers & set(by_ticker)) == POOL_PER_TRACK_PER_MARKET  # cap 만큼만 채움


@pytest.mark.asyncio
async def test_weak_hit_on_taken_ticker_still_merges():
    """taken 티커의 히트가 weak 여도 병합은 일어난다 (fix round 1, finding 2)."""
    edges = [_edge("g01", "000001", market="KOSPI", relevance="strong")]
    hits = [_hit("t01", "000001", relevance="weak", score=0.5)]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})
    merged = {c.ticker: c for c in result["candidates"]}["000001"]
    assert merged.track == "both"
    assert merged.matched_reasons == ["[테마A] 사유"]


@pytest.mark.asyncio
async def test_supply_track_absorbs_up_to_pool_per_market_when_theme_empty():
    """흡수 공식의 supply 쪽 방향도 select_candidates 로 직접 검증한다 (fix round 1, finding 3)."""
    edges = [
        _edge("g01", "000001", market="KOSPI", relevance="strong"),  # strong 1개 → 쿼터(2) 미달
        _edge("g02", "000002", market="KOSPI", relevance="weak", dc=5),
        _edge("g03", "000003", market="KOSPI", relevance="weak", dc=4),
        _edge("g04", "000004", market="KOSPI", relevance="weak", dc=3),
        _edge("g05", "000005", market="KOSPI", relevance="weak", dc=2),
    ]
    result = await select_candidates({"edges": edges, "theme_hits": [],
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome(status="no_pool")})
    kospi = [c for c in result["candidates"] if c.market == "KOSPI"]
    assert len(kospi) == POOL_PER_MARKET  # theme 이 비어 supply 가 시장 총 상한까지 흡수


@pytest.mark.asyncio
async def test_absorption_follows_actual_shortfall_not_raw_row_presence():
    """원시 행을 냈지만 후보를 0개 낸 트랙은 슬롯을 붙들지 못한다.

    이전 규칙은 bool(hits)/bool(edges) 를 대리 지표로 썼다 — theme 이 원시
    히트를 냈는데 filter 가 전부 irrelevant 로 판정하면, supply 가 채울 수
    있는데도 시장 풀이 절반에서 멈췄다.
    """
    edges = [_edge(f"g0{i}", f"00000{i}", market="KOSPI", relevance="strong", dc=10 - i)
             for i in range(1, 6)]                       # KOSPI strong 공급사 5개
    hits = [_hit("t01", "000009", relevance="irrelevant")]  # 원시 행은 있으나 선발 0

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})

    kospi = [c for c in result["candidates"] if c.market == "KOSPI"]
    assert len(kospi) == POOL_PER_MARKET  # 2가 아니라 4
    assert all(c.track == "supply" for c in kospi)


@pytest.mark.asyncio
async def test_supply_absorption_does_not_displace_theme_candidates():
    """흡수는 잔여 슬롯에만 미친다 — supply 가 theme 의 기본 슬롯을 먹지 않는다."""
    edges = [_edge(f"g0{i}", f"00000{i}", market="KOSPI", relevance="strong", dc=10 - i)
             for i in range(1, 6)]                       # 흡수 가능한 supply 5개
    hits = [_hit("t01", "000011", score=0.9), _hit("t02", "000012", score=0.8)]

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})

    kospi = [c for c in result["candidates"] if c.market == "KOSPI"]
    assert len(kospi) == POOL_PER_MARKET
    tracks = [c.track for c in kospi]
    assert tracks.count("supply") == POOL_PER_TRACK_PER_MARKET
    assert tracks.count("theme") == POOL_PER_TRACK_PER_MARKET


@pytest.mark.asyncio
async def test_theme_hit_on_an_absorbed_supply_candidate_merges_instead_of_replacing():
    """흡수분(기본 슬롯 밖의 supply)을 지목한 히트도 both 로 접힌다.

    병합을 슬롯 배분 뒤로 미루면, 3순위 공급사를 지목한 히트가 그 기업을
    supply 근거 없는 순수 theme 후보로 바꿔치기한다 — §7.2 가 금지하는 방향
    (그래프 간선 근거가 벡터 유사도보다 단단하다)이다.
    """
    edges = [_edge(f"g0{i}", f"00000{i}", market="KOSPI", relevance="strong", dc=10 - i)
             for i in range(1, 5)]                       # 000001·2 가 기본 슬롯, 3·4 는 흡수분
    hits = [_hit("t01", "000003")]                       # 흡수분을 지목한 히트

    result = await select_candidates({"edges": edges, "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(),
                                      "theme_outcome": TrackOutcome()})

    by_ticker = {c.ticker: c for c in result["candidates"]}
    assert by_ticker["000003"].track == "both"
    assert by_ticker["000003"].source_edges                   # supply 근거가 살아 있다
    assert by_ticker["000003"].matched_reasons == ["[테마A] 사유"]
    assert len([c for c in result["candidates"] if c.market == "KOSPI"]) == POOL_PER_MARKET


@pytest.mark.asyncio
async def test_failed_supply_filter_lets_theme_take_the_whole_market():
    """filter 실패로 간선이 비워진 트랙은 슬롯을 남기지 않는다(그래프가 edges 를 비운다)."""
    hits = [_hit(f"t{i:02d}", f"00000{i}", score=0.9 - i * 0.01) for i in range(1, 6)]

    result = await select_candidates({"edges": [], "theme_hits": hits,
                                      "supply_outcome": TrackOutcome(error="bedrock timeout"),
                                      "theme_outcome": TrackOutcome()})

    kospi = [c for c in result["candidates"] if c.market == "KOSPI"]
    assert len(kospi) == POOL_PER_MARKET


@pytest.mark.asyncio
async def test_no_pool_reason_excludes_error_text_but_logs_warning(caplog):
    """장애 원문은 사용자용 reason 이 아니라 로그로만 남는다 (fix round 1, finding 4)."""
    import logging

    with caplog.at_level(logging.WARNING, logger="beneficiary.agent.nodes.candidate_selector"):
        result = await select_candidates({
            "edges": [], "theme_hits": [],
            "supply_outcome": TrackOutcome(status="no_pool", reason="공급망 사유"),
            "theme_outcome": TrackOutcome(error="vector index missing"),
        })
    assert result["status"] == "no_pool"
    assert "vector index missing" not in result["reason"]
    assert "vector index missing" in caplog.text
