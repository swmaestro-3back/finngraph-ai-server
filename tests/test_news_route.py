"""뉴스 그래프 라우트 — repository를 monkeypatch 해 DB 없이 상태 코드와 파라미터 검증만 본다."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import repository
from api.routes import news
from schemas import NewsGraphResponse


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(news.router)
    return TestClient(app)


def test_returns_graph_and_passes_hop(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake(news_id: str, hop: int = 1) -> NewsGraphResponse | None:
        calls.append((news_id, hop))
        return NewsGraphResponse(seed_relationship_ids=["r1"], truncated=True)

    monkeypatch.setattr(repository, "get_news_graph", fake)

    res = make_client().get("/api/v1/news/123/graph?hop=2")

    assert res.status_code == 200
    assert calls == [("123", 2)]
    body = res.json()
    assert body["seed_relationship_ids"] == ["r1"]
    assert body["truncated"] is True
    assert body["companies"] == [] and body["relationships"] == []


def test_404_when_news_has_no_relationships(monkeypatch):
    async def fake(news_id: str, hop: int = 1):
        return None

    monkeypatch.setattr(repository, "get_news_graph", fake)

    res = make_client().get("/api/v1/news/999/graph")
    assert res.status_code == 404


def test_hop_out_of_range_is_422(monkeypatch):
    async def fake(news_id: str, hop: int = 1):
        raise AssertionError("검증에서 걸러져야 한다")

    monkeypatch.setattr(repository, "get_news_graph", fake)

    assert make_client().get("/api/v1/news/1/graph?hop=0").status_code == 422
    assert make_client().get("/api/v1/news/1/graph?hop=4").status_code == 422
