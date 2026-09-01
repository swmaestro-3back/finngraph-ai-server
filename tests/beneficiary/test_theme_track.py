"""theme 트랙 서브그래프 — 부모 없이 단독으로 돈다."""

from __future__ import annotations

import pytest

from beneficiary.models import NewsContext, NewsPlan, RootCompany, ScenarioProbe
from beneficiary.agent.tracks.theme import build_theme_subgraph
from beneficiary.agent.tracks.theme import nodes as theme_nodes


def _inputs():
    return {
        "news": NewsContext(title="t", summary="s", published_at="2026-09-01", link=None),
        "plan": NewsPlan(event_summary="s", polarity="positive",
                         scenario_probes=[ScenarioProbe(stage=1, hypothesis="h", query="q")]),
        "root_companies": [RootCompany(company_id=1, name="루트", ticker="005930",
                                       description=None)],
        "relation_lines": [],
    }


@pytest.mark.asyncio
async def test_zero_hits_yields_no_pool_and_skips_filter(monkeypatch):
    called = {"filter": False}

    async def _no_hits(state):
        return {"hits": []}

    async def _filter(state):
        called["filter"] = True
        return {}

    monkeypatch.setattr(theme_nodes, "expand_theme", _no_hits)
    monkeypatch.setattr(theme_nodes, "filter_theme", _filter)

    result = await build_theme_subgraph().ainvoke(_inputs())

    assert result["outcome"].status == "no_pool"
    assert called["filter"] is False


@pytest.mark.asyncio
async def test_search_failure_becomes_outcome_error(monkeypatch):
    async def _boom(state):
        raise RuntimeError("vector index missing")

    monkeypatch.setattr(theme_nodes, "expand_theme", _boom)

    result = await build_theme_subgraph().ainvoke(_inputs())

    assert result["outcome"].error is not None
    assert result["hits"] == []
