"""filter 후처리·폴백 규칙 (DB·LLM 없음) + 노드의 LLM 폴백 경로 (모듈 시임)."""

from __future__ import annotations

import pytest

from beneficiary.models import SupplyChainCandidate, FilterOutput, NewsPlan, RivalCandidate
from beneficiary.nodes.rivals import fallback_filter_rivals
from beneficiary.nodes.supply import fallback_filter_supply
from beneficiary.nodes import supply as supply_module
from beneficiary.utils import llm
from beneficiary.utils.postprocess import apply_filter_output


def _edge(gid, ticker="000002", market="KOSPI", dc=1, nc=0, items=("HBM",)):
    return SupplyChainCandidate(gid=gid, root_name="루트 기업", subject_name=f"공급{gid}", object_name="루트 기업",
                         ticker=ticker, name=f"공급{gid}", company_id=1, market=market,
                         disclosure_items=list(items), news_items=[],
                         disclosure_count=dc, news_mention_count=nc)


def test_apply_filter_output_reenforces_rules():
    edges = {e.gid: e for e in [_edge("g01"), _edge("g02"), _edge("g03", items=()), _edge("g04")]}
    output = FilterOutput(strong=["g01", "g02", "g03", "gXX"], weak=["g02"])
    strong_ids, weak_ids = apply_filter_output(output, edges, cap_weak_ids={"g03"})
    assert strong_ids == ["g01", "g02"]      # gXX 폐기, g02 는 strong 우선
    assert weak_ids == ["g03"]               # 아이템 없는 간선은 최대 weak
    assert edges["g04"].relevance == "irrelevant"  # 응답에서 빠진 id
    assert edges["g01"].relevance == "strong" and edges["g03"].relevance == "weak"


def test_fallback_filter_supply_top3_per_market_by_count():
    edges = [
        _edge("g01", ticker="000001", market="KOSPI", dc=5),
        _edge("g02", ticker="000002", market="KOSPI", dc=3),
        _edge("g03", ticker="000003", market="KOSPI", dc=3),
        _edge("g04", ticker="000004", market="KOSPI", dc=1),
        _edge("g05", ticker="000005", market="KOSDAQ", dc=2),
    ]
    strong_ids, weak_ids = fallback_filter_supply(edges)
    assert strong_ids == ["g01", "g02", "g03", "g05"] and weak_ids == []
    assert edges[3].relevance == "irrelevant"


def test_fallback_filter_rivals_top3_per_market_by_shared():
    def rival(kid, ticker, market, shared):
        return RivalCandidate(kid=kid, subject_name="루트 기업", ticker=ticker, name=kid,
                              company_id=1, market=market, shared_themes=shared)
    rivals = [rival("k01", "000001", "KOSPI", 3), rival("k02", "000002", "KOSPI", 1),
              rival("k03", "000003", "KOSPI", 1), rival("k04", "000004", "KOSPI", 1),
              rival("k05", "000005", "KOSDAQ", 2)]
    strong_ids, _ = fallback_filter_rivals(rivals)
    # KOSPI 동점(1) 은 ticker asc → k02, k03 이 남고 k04 탈락
    assert strong_ids == ["k01", "k02", "k03", "k05"]
    assert rivals[3].relevance == "irrelevant"


async def test_filter_supply_node_falls_back_on_llm_error(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(llm, "filter_supply", boom)
    edges = [_edge("g01"), _edge("g02", ticker="000003", dc=9)]
    plan = NewsPlan(event_summary="s", polarity="positive", core_items=["HBM"])
    result = await supply_module.filter_supply({"edges": edges, "plan": plan})
    assert result["filter_fallback"] is True
    assert set(result["strong_ids"]) == {"g01", "g02"}


async def test_filter_supply_node_skips_llm_when_no_core_items(monkeypatch):
    called = {"n": 0}

    async def counter(prompt):
        called["n"] += 1
        return FilterOutput()

    monkeypatch.setattr(llm, "filter_supply", counter)
    plan = NewsPlan(event_summary="s", polarity="positive", core_items=[])
    result = await supply_module.filter_supply({"edges": [_edge("g01")], "plan": plan})
    assert called["n"] == 0 and result["filter_fallback"] is True
