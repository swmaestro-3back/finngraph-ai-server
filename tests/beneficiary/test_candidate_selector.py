"""candidate_selector — 기업 접기·쿼터·weak 승격·정렬·matched_items (DB·LLM 없음)."""

from __future__ import annotations

from beneficiary.models import SupplyChainCandidate, RivalCandidate
from beneficiary.agent.nodes.candidate_selector import select_rival_candidates, select_supply_candidates


def _edge(gid, ticker, market, relevance, dc=1, nc=0, items=("HBM",), name=None):
    return SupplyChainCandidate(gid=gid, root_name="루트 기업", subject_name=name or f"공급{ticker}",
                         object_name="루트 기업", ticker=ticker, name=name or f"공급{ticker}",
                         company_id=1, market=market,
                         disclosure_items=list(items), news_items=[],
                         disclosure_count=dc, news_mention_count=nc, relevance=relevance)


def test_folds_edges_per_company_and_merges_items():
    edges = [
        _edge("g01", "000001", "KOSPI", "strong", dc=2, items=("HBM",)),
        _edge("g02", "000001", "KOSPI", "strong", dc=1, items=("TC본더", "HBM")),
        _edge("g03", "000002", "KOSPI", "strong", dc=9),
        _edge("g04", "000001", "KOSPI", "weak", items=("무관",)),  # 비승격 → 구성 제외
    ]
    candidates = select_supply_candidates(edges)
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
    candidates = select_supply_candidates(edges)
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
    candidates = select_supply_candidates(edges)
    kospi = [c.ticker for c in candidates if c.market == "KOSPI"]
    kosdaq = [(c.ticker, c.promoted) for c in candidates if c.market == "KOSDAQ"]
    assert kospi == ["000001", "000002"]  # weak 000003 승격 안 됨
    # 미달 시장만 시장당 3개까지 승격 (dc 순): 000004(strong) + 000005, 000006
    assert kosdaq == [("000004", False), ("000005", True), ("000006", True)]
    promoted = {c.ticker: c for c in candidates}["000005"]
    assert promoted.relevance == "weak"  # 원 등급 유지


def test_market_zero_still_proceeds():
    edges = [_edge("g01", "000001", "KOSPI", "strong")]
    candidates = select_supply_candidates(edges)
    assert len(candidates) == 1  # KOSDAQ 0개여도 진행 (caveats 는 evaluator 소관)


def test_rival_selection_orders_by_shared_then_ticker():
    def rival(kid, ticker, market, relevance, shared=1):
        return RivalCandidate(kid=kid, subject_name="루트 기업", ticker=ticker, name=kid,
                              company_id=1, market=market,
                              shared_themes=shared, via_themes=["테마A"],
                              supplied_items=["HBM2"], relevance=relevance)
    rivals = [rival("k01", "000001", "KOSPI", "strong", shared=1),
              rival("k02", "000002", "KOSPI", "strong", shared=3),
              rival("k03", "000003", "KOSDAQ", "weak", shared=2),
              rival("k04", "000004", "KOSDAQ", "weak", shared=2)]
    candidates = select_rival_candidates(rivals)
    kospi = [c.ticker for c in candidates if c.market == "KOSPI"]
    kosdaq = [(c.ticker, c.promoted) for c in candidates if c.market == "KOSDAQ"]
    assert kospi == ["000002", "000001"]  # shared desc
    assert kosdaq == [("000003", True), ("000004", True)]  # shared 동점 → ticker asc
    assert candidates[0].track == "rival"
    assert candidates[0].matched_items == ["HBM2"]
    assert candidates[0].relation_lines == ["공유 테마: 테마A"]
