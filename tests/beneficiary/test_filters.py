"""filter 후처리 규칙 (DB·LLM 없음) + 노드의 정지 경로 (모듈 시임)."""

from __future__ import annotations

import pytest

from beneficiary.models import FilterOutput, NewsPlan, ScenarioProbe, SupplyChainCandidate, ThemeCandidate
from beneficiary.agent.tracks.supply import nodes as supply_module
from beneficiary.agent.tracks.theme import nodes as theme_nodes
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.postprocess import apply_filter_output


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


async def test_filter_supply_node_propagates_llm_error(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(llm, "filter_supply", boom)
    plan = NewsPlan(event_summary="s", polarity="positive", core_items=["HBM"])
    # 폴백 없음 — 노드는 삼키지 않고 올린다. error 강등은 workflow 의
    # error_handler 소관이다(test_workflow 참조).
    with pytest.raises(RuntimeError):
        await supply_module.filter_supply({"edges": [_edge("g01")], "plan": plan})


async def test_filter_supply_node_stops_when_no_core_items(monkeypatch):
    called = {"n": 0}

    async def counter(prompt):
        called["n"] += 1
        return FilterOutput()

    monkeypatch.setattr(llm, "filter_supply", counter)
    plan = NewsPlan(event_summary="s", polarity="positive", core_items=[])
    result = await supply_module.filter_supply({"edges": [_edge("g01")], "plan": plan})
    assert called["n"] == 0  # 판정 기준이 없으면 LLM 도 부르지 않는다
    assert result["status"] == "no_candidates" and result["reason"]


def _hit(tid, score, ticker="005930"):
    return ThemeCandidate(tid=tid, stage=1, hypothesis="h", ticker=ticker,
                          name="회사", company_id=1, market="KOSPI", score=score,
                          matched_themes=["테마A"], matched_reasons=["[테마A] 사유"])


async def test_borderline_score_cannot_be_strong(monkeypatch):
    """임계값 언저리 후보는 LLM 이 strong 을 줘도 코드가 weak 로 강등한다."""
    hits = [_hit("t01", theme_nodes.MIN_SCORE + 0.001, "000001"),   # 언저리
            _hit("t02", theme_nodes.MIN_SCORE + 0.10, "000002")]    # 충분(0.72 — 실측 true positive 대역)

    async def _fake_filter(prompt):
        return FilterOutput(strong=["t01", "t02"], weak=[])

    monkeypatch.setattr(theme_nodes.llm, "filter_theme", _fake_filter)

    state = {"hits": hits,
             "plan": NewsPlan(event_summary="s", polarity="positive",
                              scenario_probes=[ScenarioProbe(stage=1, hypothesis="h",
                                                             query="q")])}
    result = await theme_nodes.filter_theme(state)

    assert result["strong_ids"] == ["t02"]
    assert result["weak_ids"] == ["t01"]
    assert hits[0].relevance == "weak" and hits[1].relevance == "strong"
