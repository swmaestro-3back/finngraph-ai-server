"""간선 근거 — 품목 묶기, 응답 조립, 라우트 상태 코드."""
from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rdb
import repository
from api.routes import relationship
from fake_pg import FakeConn
from mappers import group_news_items
from schemas import RelationshipEvidenceResponse


def test_group_news_items_merges_duplicate_ids_and_dedupes_items():
    grouped = group_news_items([10, "10", 11], ["HBM", "HBM", "패키징"])
    assert grouped == {"10": ["HBM"], "11": ["패키징"]}


def test_group_news_items_keeps_ids_when_items_are_shorter():
    assert group_news_items([10, 11], ["HBM"]) == {"10": ["HBM"], "11": []}


async def test_news_briefs_runs_two_queries_and_skips_empty():
    empty = FakeConn()
    assert await rdb.fetch_news_briefs(empty, [], 20) == ([], 0, [])
    assert empty.calls == []

    # 전체 건수는 목록 쿼리에 윈도우 count 로 실려 온다 — 행에서 떼어 내고 목록에는 남기지 않는다
    conn = FakeConn(
        [{"news_id": "11", "title": "t", "url": "u", "original_url": None, "published_at": None, "total": 2}],
        [{"month": "2026-09", "count": 1}],
    )
    rows, total, monthly = await rdb.fetch_news_briefs(conn, [10, 11], 20)
    assert rows == [{"news_id": "11", "title": "t", "url": "u", "original_url": None, "published_at": None}]
    assert total == 2 and monthly == [{"month": "2026-09", "count": 1}]
    assert len(conn.calls) == 2
    assert conn.calls[0][1] == {"ids": [10, 11], "limit": 20}


async def test_news_briefs_total_is_zero_when_no_rows():
    conn = FakeConn([], [])
    assert await rdb.fetch_news_briefs(conn, [10], 20) == ([], 0, [])


@asynccontextmanager
async def fake_connection(timeout=None):
    yield object()


async def test_repository_builds_evidence(monkeypatch):
    async def execute(query, params):
        assert params == {"id": "5:abc:12"}
        return [{
            "news_ids": [10, 11, "x"], "news_items": ["HBM", None],
            "rcept_nos": ["2026A"], "disclosure_items": ["단일판매"],
        }]

    async def news_briefs(conn, ids, limit):
        assert ids == [10, 11] and limit == 5  # 숫자 아닌 id 는 버린다
        return ([{"news_id": "11", "title": "B", "url": "u11", "original_url": None, "published_at": "2026-09-02"},
                 {"news_id": "10", "title": "A", "url": "u10", "original_url": "o10", "published_at": "2026-09-01"}],
                2, [{"month": "2026-09", "count": 2}])

    async def disclosure_briefs(conn, rcept_nos):
        return [{"rcept_no": "2026A", "report_nm": "단일판매·공급계약체결", "rcept_dt": "2026-09-03"}]

    monkeypatch.setattr(repository.neo4j_database, "execute", execute)
    monkeypatch.setattr(repository.postgres_client, "connection", fake_connection)
    monkeypatch.setattr(rdb, "fetch_news_briefs", news_briefs)
    monkeypatch.setattr(rdb, "fetch_disclosure_briefs", disclosure_briefs)

    res = await repository.get_relationship_evidence("5:abc:12", 5)
    assert [n.news_id for n in res.news] == ["11", "10"]
    assert res.news[1].items == ["HBM"] and res.news[0].items == []
    assert res.news_total == 2 and res.monthly[0].count == 2
    assert res.disclosures[0].item == "단일판매" and res.disclosures[0].rcept_dt == "2026-09-03"


async def test_repository_returns_none_when_relationship_missing(monkeypatch):
    async def execute(query, params):
        return []
    monkeypatch.setattr(repository.neo4j_database, "execute", execute)
    assert await repository.get_relationship_evidence("5:abc:99", 20) is None


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(relationship.router)
    return TestClient(app)


def test_element_id_with_colons_matches(monkeypatch):
    calls = []

    async def fake(element_id: str, limit: int = 20):
        calls.append((element_id, limit))
        return RelationshipEvidenceResponse()

    monkeypatch.setattr(repository, "get_relationship_evidence", fake)
    res = make_client().get("/api/v1/relationships/5%3Aabc%3A12/evidence?limit=5")
    assert res.status_code == 200
    assert calls == [("5:abc:12", 5)]
    assert res.json() == {"news": [], "news_total": 0, "monthly": [], "disclosures": []}


def test_404_422_503(monkeypatch):
    async def missing(element_id: str, limit: int = 20):
        return None

    async def down(element_id: str, limit: int = 20):
        raise psycopg.OperationalError("pg down")

    monkeypatch.setattr(repository, "get_relationship_evidence", missing)
    assert make_client().get("/api/v1/relationships/1/evidence").status_code == 404
    assert make_client().get("/api/v1/relationships/1/evidence?limit=0").status_code == 422
    assert make_client().get("/api/v1/relationships/1/evidence?limit=51").status_code == 422

    monkeypatch.setattr(repository, "get_relationship_evidence", down)
    assert make_client().get("/api/v1/relationships/1/evidence").status_code == 503


async def test_evidence_waits_for_pool_at_most_a_few_seconds(monkeypatch):
    seen: list = []

    @asynccontextmanager
    async def connection(timeout=None):
        seen.append(timeout)
        yield object()

    async def execute(query, params):
        return [{"news_ids": [], "news_items": [], "rcept_nos": [], "disclosure_items": []}]

    monkeypatch.setattr(repository.neo4j_database, "execute", execute)
    monkeypatch.setattr(repository.postgres_client, "connection", connection)
    await repository.get_relationship_evidence("5:abc:1", 5)
    assert seen and seen[0] is not None and seen[0] <= 3
