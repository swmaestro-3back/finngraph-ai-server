"""insights 라우트 테스트 — 서비스는 스텁, 상태코드 매핑을 검증한다."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import news
from insights import service
from insights.models import InsightResponse


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(news.router)
    return TestClient(app)


def _response(news_id: int) -> InsightResponse:
    return InsightResponse(
        news_id=news_id,
        rep_news_id=news_id,
        status="ok",
        event_interpretation="해석",
        items=[],
        prompt_version="v1",
        disclaimer="면책",
    )


def test_returns_insights_payload(client, monkeypatch):
    async def fake(news_id: int) -> InsightResponse:
        return _response(news_id)

    monkeypatch.setattr(service, "get_news_insights", fake)

    response = client.get("/api/v1/news/42/insights")

    assert response.status_code == 200
    body = response.json()
    assert body["news_id"] == 42
    assert body["disclaimer"] == "면책"


def test_unknown_news_maps_to_404(client, monkeypatch):
    async def fake(news_id: int):
        raise service.NewsNotFoundError

    monkeypatch.setattr(service, "get_news_insights", fake)

    assert client.get("/api/v1/news/42/insights").status_code == 404


def test_generation_failure_maps_to_503(client, monkeypatch):
    async def fake(news_id: int):
        raise service.InsightGenerationError

    monkeypatch.setattr(service, "get_news_insights", fake)

    assert client.get("/api/v1/news/42/insights").status_code == 503
