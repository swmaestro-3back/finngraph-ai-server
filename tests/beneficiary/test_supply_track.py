"""supply 트랙 서브그래프 — 부모 없이 단독으로 돈다."""

from __future__ import annotations

import pytest

from beneficiary.models import NewsContext, NewsPlan, RootCompany
from beneficiary.agent.tracks.supply import build_supply_subgraph
from beneficiary.agent.tracks.supply import nodes as supply_nodes


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
async def test_node_exception_is_demoted_to_outcome_error(monkeypatch):
    async def _boom(state):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(supply_nodes, "expand_supply", _boom)

    result = await build_supply_subgraph().ainvoke(_inputs())

    # 예외는 서브그래프 밖으로 나가지 않는다 — 값으로 받는다
    assert result["outcome"].error is not None
    assert result["edges"] == []
