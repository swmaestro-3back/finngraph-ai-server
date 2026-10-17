"""이벤트 상세 — Postgres 만 본다. 조회 순서·응답 조립·라우트 상태 코드."""
from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rdb
import repository
from api.routes import event
from fake_pg import FakeConn
from mappers import to_event_detail
from schemas import EventDetailResponse

CLUSTER = {
    "cluster_id": 9, "title": "HBM 증설", "keywords": ["hbm"],
    "representative_news_id": 11, "first_published_at": "2026-10-01T09:00:00+09:00",
    "last_published_at": "2026-10-02T09:00:00+09:00",
}


async def test_fetch_event_detail_none_when_cluster_missing():
    conn = FakeConn([])
    assert await rdb.fetch_event_detail(conn, 404, 20) is None
    assert len(conn.calls) == 1


async def test_fetch_event_detail_collects_news_total_companies():
    conn = FakeConn(
        [CLUSTER],
        [{"news_id": "11", "title": "t", "url": "u", "original_url": None, "published_at": None}],
        [{"total": 3}],
        [{"name": "SK하이닉스", "ticker": "000660"}, {"name": "솔리다임", "ticker": None}],
    )
    detail = await rdb.fetch_event_detail(conn, 9, 20)
    assert detail["news_total"] == 3 and len(detail["news"]) == 1
    assert detail["companies"][1] == {"name": "솔리다임", "ticker": None}
    assert conn.calls[1][1] == {"id": 9, "limit": 20}


def test_to_event_detail_attaches_quotes_by_ticker():
    detail = {**CLUSTER, "news": [], "news_total": 0,
              "companies": [{"name": "SK하이닉스", "ticker": "000660"}, {"name": "솔리다임", "ticker": None}]}
    res = to_event_detail(detail, {"000660": {"price": 1.0, "change": -1.92, "price_date": None,
                                              "market_cap": None, "r_1w": None, "r_1m": None, "r_3m": None}})
    assert res.companies[0].quote.change == -1.92
    assert res.companies[1].quote is None


@asynccontextmanager
async def fake_connection(timeout=None):
    yield object()


async def test_repository_get_event_detail(monkeypatch):
    async def fetch_detail(conn, cluster_id, limit):
        return {**CLUSTER, "news": [], "news_total": 0, "companies": [{"name": "SK하이닉스", "ticker": "000660"}]}

    async def quotes(conn, tickers):
        assert tickers == ["000660"]
        return {}

    monkeypatch.setattr(repository.postgres_client, "connection", fake_connection)
    monkeypatch.setattr(rdb, "fetch_event_detail", fetch_detail)
    monkeypatch.setattr(rdb, "fetch_stock_quotes", quotes)
    res = await repository.get_event_detail(9, 20)
    assert res.cluster_id == 9 and res.companies[0].quote is None


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(event.router)
    return TestClient(app)


def test_routes(monkeypatch):
    async def ok(cluster_id: int, limit: int = 20):
        return EventDetailResponse(**{**CLUSTER, "news": [], "news_total": 0, "companies": []})

    async def missing(cluster_id: int, limit: int = 20):
        return None

    async def down(cluster_id: int, limit: int = 20):
        raise psycopg.OperationalError("pg down")

    monkeypatch.setattr(repository, "get_event_detail", ok)
    assert make_client().get("/api/v1/events/9").json()["keywords"] == ["hbm"]
    assert make_client().get("/api/v1/events/abc").status_code == 422
    monkeypatch.setattr(repository, "get_event_detail", missing)
    assert make_client().get("/api/v1/events/404").status_code == 404
    monkeypatch.setattr(repository, "get_event_detail", down)
    assert make_client().get("/api/v1/events/9").status_code == 503
