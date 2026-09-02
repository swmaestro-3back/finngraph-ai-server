"""supply 트랙 서브그래프 — 부모 없이 단독으로 돈다."""

from __future__ import annotations

import pytest

from beneficiary.models import NewsContext, NewsPlan, RootCompany
from beneficiary.agent.subgraphs.supply import build_supply_subgraph
from beneficiary.agent.subgraphs.supply import nodes as supply_nodes


def _inputs():
    return {
        "news": NewsContext(title="t", summary="s", published_at="2026-09-01", link=None),
        "plan": NewsPlan(event_summary="s", polarity="positive", core_items=["변압기"]),
        "root_companies": [RootCompany(company_id=1, name="루트", ticker="005930",
                                       description=None)],
        "relation_lines": [],
    }


@pytest.mark.asyncio
async def test_empty_expansion_yields_no_pool_outcome_and_skips_filter(monkeypatch):
    async def _no_edges(state):
        return {"edges": []}

    called = {"filter": False}

    async def _filter(state):
        called["filter"] = True
        return {}

    monkeypatch.setattr(supply_nodes, "expand_supply", _no_edges)
    monkeypatch.setattr(supply_nodes, "filter_supply", _filter)

    result = await build_supply_subgraph().ainvoke(_inputs())

    assert result["outcome"].status == "no_pool"
    assert called["filter"] is False


@pytest.mark.asyncio
async def test_no_core_items_yields_no_candidates_outcome_through_compiled_graph(monkeypatch):
    # filter_supply 자체의 조기 종료(status="no_candidates")도 outcome 으로
    # 승격돼야 한다 — nodes.filter_supply 를 직접 부르는 게 아니라 컴파일된
    # 서브그래프를 통해서 확인한다(리뷰에서 지적된 회귀: status/reason 키가
    # SupplyTrackState 에 없어 LangGraph 가 조용히 버렸었다).
    async def _some_edges(state):
        return {"edges": [object()]}

    monkeypatch.setattr(supply_nodes, "expand_supply", _some_edges)

    inputs = _inputs()
    inputs["plan"] = NewsPlan(event_summary="s", polarity="positive", core_items=[])

    result = await build_supply_subgraph().ainvoke(inputs)

    assert result["outcome"].status == "no_candidates"
    assert result["outcome"].reason == "사건의 핵심 품목을 특정하지 못해 공급사를 선별할 수 없습니다."


@pytest.mark.asyncio
async def test_node_exception_is_demoted_to_outcome_error(monkeypatch):
    async def _boom(state):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(supply_nodes, "expand_supply", _boom)

    result = await build_supply_subgraph().ainvoke(_inputs())

    # 예외는 서브그래프 밖으로 나가지 않는다 — 값으로 받는다
    assert result["outcome"].error is not None
    assert result["edges"] == []


@pytest.mark.asyncio
async def test_filter_failure_also_clears_edges(monkeypatch):
    """선별 단계 실패도 원시 간선을 비운다.

    expand 실패만 확인하면 구멍이 남는다: filter 가 실패하면 남은 간선은 전부
    relevance=None 이라 쓸 수 없는데, 그것을 state 에 남기면 팬인이 "원시 행은
    있으니 장애가 아니다"로 오독해 두 트랙 동시 장애의 503 이 죽는다.
    """
    async def _some_edges(state):
        return {"edges": [object()]}

    async def _boom(state):
        raise RuntimeError("bedrock timeout")

    monkeypatch.setattr(supply_nodes, "expand_supply", _some_edges)
    monkeypatch.setattr(supply_nodes, "filter_supply", _boom)

    result = await build_supply_subgraph().ainvoke(_inputs())

    assert result["outcome"].error is not None
    assert result["edges"] == []
