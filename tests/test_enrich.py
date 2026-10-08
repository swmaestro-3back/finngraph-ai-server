"""enrich — rdb 조회를 가짜로 바꿔 id 수집·채우기·실패 격리만 본다."""
from __future__ import annotations

import logging

import enrich
import rdb
import repository
from schemas import CompanyNode, CompanyResponse, EventNode, ThemeNode, ThemeResponse

STOCK = {"price": 263500.0, "change": -1.86, "price_date": "2026-10-08",
         "market_cap": 1, "r_1w": -4.01, "r_1m": None, "r_3m": None}
THEME = {"change": 1.77, "price_date": "2026-10-08", "r_1w": 7.73, "r_1m": 8.51, "r_3m": None, "market_cap": 2}
META = {"keywords": ["hbm"], "member_count": 3, "representative_news_id": 11}


def fake_query(results: dict, calls: list | None = None, fail: set | None = None):
    async def query(fetch, ids):
        if calls is not None:
            calls.append((fetch.__name__, list(ids)))
        if fail and fetch in fail:
            raise RuntimeError("pg down")
        return results.get(fetch, {}) if ids else {}
    return query


async def test_fills_company_theme_event_from_postgres(monkeypatch):
    calls: list = []
    monkeypatch.setattr(enrich, "_query", fake_query({
        rdb.fetch_stock_quotes: {"005930": STOCK},
        rdb.fetch_theme_quotes: {1: THEME},
        rdb.fetch_event_meta: {9: META},
    }, calls))
    resp = CompanyResponse(
        companies=[CompanyNode(id="c1", ticker="005930"), CompanyNode(id="c2", ticker=None)],
        events=[EventNode(id="e1", cluster_id=9)],
    )
    theme_resp = ThemeResponse(theme=ThemeNode(id="t1", theme_id=1), companies=[])

    await enrich.enrich_graph(resp)
    await enrich.enrich_graph(theme_resp)

    assert resp.companies[0].quote.change == -1.86
    assert resp.companies[1].quote is None
    assert resp.events[0].keywords == ["hbm"] and resp.events[0].member_count == 3
    assert resp.events[0].representative_news_id == 11
    assert theme_resp.theme.quote.r_1w == 7.73
    assert ("fetch_stock_quotes", ["005930"]) in calls  # ticker 없는 기업은 묻지 않는다


async def test_missing_rows_leave_quote_none(monkeypatch):
    monkeypatch.setattr(enrich, "_query", fake_query({rdb.fetch_stock_quotes: {}}))
    resp = CompanyResponse(companies=[CompanyNode(id="c1", ticker="AAPL")])
    await enrich.enrich_graph(resp)
    assert resp.companies[0].quote is None


async def test_one_failed_lookup_does_not_block_others(monkeypatch, caplog):
    monkeypatch.setattr(enrich, "_query", fake_query(
        {rdb.fetch_event_meta: {9: META}}, fail={rdb.fetch_stock_quotes},
    ))
    resp = CompanyResponse(
        companies=[CompanyNode(id="c1", ticker="005930")], events=[EventNode(id="e1", cluster_id=9)],
    )
    with caplog.at_level(logging.WARNING):
        await enrich.enrich_graph(resp)
    assert resp.companies[0].quote is None
    assert resp.events[0].member_count == 3
    assert "fetch_stock_quotes" in caplog.text


async def test_repository_enriches_company_overview(monkeypatch):
    class Node:
        element_id = "c1"
        labels = frozenset({"Company"})

        def keys(self):
            return ["ticker"]

        def __getitem__(self, key):
            return "005930"

    async def execute(query, params):
        return [{"center": Node(), "neighbors": [], "relationships": []}]

    seen: list = []

    async def fake_enrich(resp):
        seen.append(resp)

    monkeypatch.setattr(repository.neo4j_database, "execute", execute)
    monkeypatch.setattr(repository, "enrich_graph", fake_enrich)

    resp = await repository.get_company("005930")
    assert seen == [resp]


async def test_hung_postgres_does_not_stall_graph(monkeypatch):
    import asyncio
    import time

    async def hang(fetch, ids):
        await asyncio.sleep(60)

    monkeypatch.setattr(enrich, "_query", hang)
    monkeypatch.setattr(enrich, "LOOKUP_TIMEOUT", 0.05)
    resp = CompanyResponse(companies=[CompanyNode(id="c1", ticker="005930")])
    started = time.monotonic()
    await enrich.enrich_graph(resp)
    assert time.monotonic() - started < 1
    assert resp.companies[0].quote is None
