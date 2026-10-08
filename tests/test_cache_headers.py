"""브라우저 캐시 헤더 — 성공 응답에만 Cache-Control 이 붙고, 오류 응답에는 붙지 않는다."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import repository
from api.cache import EVENT_MAX_AGE, EVIDENCE_MAX_AGE, GRAPH_MAX_AGE, cache_control
from api.routes import company, event, relationship, theme
from schemas import (
    CompanyNode,
    CompanyResponse,
    CompanyThemesResponse,
    EventDetailResponse,
    RelationshipEvidenceResponse,
    SupplyChainResponse,
    ThemeNode,
    ThemeResponse,
)


def test_cache_control_value_is_private_with_stale_while_revalidate():
    assert cache_control(300) == "private, max-age=300, stale-while-revalidate=300"
    assert cache_control(600, stale=3600) == "private, max-age=600, stale-while-revalidate=3600"
    assert cache_control(60, stale=0) == "private, max-age=60"


def test_budgets_follow_how_often_the_data_changes():
    # 시세는 ETL 이 장중 매시간 갱신한다 — 클라이언트 메모리 캐시(5분)와 같은 주기
    assert GRAPH_MAX_AGE == 300 and EVENT_MAX_AGE == 300
    # 근거 기사 제목·공시는 관계가 다시 적재될 때만 바뀐다
    assert EVIDENCE_MAX_AGE >= GRAPH_MAX_AGE


def make_client() -> TestClient:
    app = FastAPI()
    for router in (company.router, theme.router, relationship.router, event.router):
        app.include_router(router)
    return TestClient(app)


def test_graph_routes_set_cache_control(monkeypatch):
    async def company_ok(ticker: str):
        return CompanyResponse()

    async def supply_ok(ticker: str, hop: int = 1, market=None, index=None):
        return SupplyChainResponse()

    async def themes_ok(ticker: str):
        return CompanyThemesResponse(company=CompanyNode(id="c1", ticker=ticker))

    async def theme_ok(name: str):
        return ThemeResponse(theme=ThemeNode(id="t1", name=name))

    monkeypatch.setattr(repository, "get_company", company_ok)
    monkeypatch.setattr(repository, "get_company_supplychain", supply_ok)
    monkeypatch.setattr(repository, "get_company_themes", themes_ok)
    monkeypatch.setattr(repository, "get_theme", theme_ok)

    client = make_client()
    expected = cache_control(GRAPH_MAX_AGE)
    for path in (
        "/api/v1/companies/005930",
        "/api/v1/companies/005930/supplychain?hop=2",
        "/api/v1/companies/005930/themes",
        "/api/v1/themes/2%EC%B0%A8%EC%A0%84%EC%A7%80",
    ):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == expected, path


def test_evidence_and_event_routes_set_their_own_budget(monkeypatch):
    async def evidence_ok(element_id: str, limit: int = 20):
        return RelationshipEvidenceResponse()

    async def event_ok(cluster_id: int, limit: int = 20):
        return EventDetailResponse(cluster_id=cluster_id)

    monkeypatch.setattr(repository, "get_relationship_evidence", evidence_ok)
    monkeypatch.setattr(repository, "get_event_detail", event_ok)
    client = make_client()
    assert client.get("/api/v1/relationships/5%3Aabc%3A1/evidence").headers["cache-control"] == cache_control(
        EVIDENCE_MAX_AGE, stale=EVIDENCE_MAX_AGE
    )
    assert client.get("/api/v1/events/9").headers["cache-control"] == cache_control(EVENT_MAX_AGE)


def test_error_responses_are_not_cacheable(monkeypatch):
    async def missing(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "get_company", missing)
    monkeypatch.setattr(repository, "get_relationship_evidence", missing)
    client = make_client()
    for path in ("/api/v1/companies/000000", "/api/v1/relationships/1/evidence"):
        res = client.get(path)
        assert res.status_code == 404
        assert "cache-control" not in res.headers, path
