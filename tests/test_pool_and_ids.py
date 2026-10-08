"""풀 크기와 news_id 정제 — 그래프 요청 하나가 커넥션 셋을 동시에 쓰므로 풀이 넉넉해야 한다."""
from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg_pool

import rdb
import repository
from core import postgres


async def test_pool_is_sized_for_concurrent_enrichment(monkeypatch):
    seen: dict = {}

    class FakePool:
        def __init__(self, conninfo, **kwargs):
            seen.update(kwargs)

        async def open(self, wait=True, timeout=None):
            pass

    monkeypatch.setattr(psycopg_pool, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(postgres, "AsyncConnectionPool", FakePool)
    client = postgres.PostgresClient()
    await client.connect()
    # 그래프 요청 하나가 3개를 동시에 쓴다 — 동시 요청 몇 개는 풀 대기 없이 지나가야 한다
    assert seen["max_size"] >= 3 * 4
    assert seen["min_size"] <= seen["max_size"]


async def test_non_ascii_digits_are_dropped_not_raised(monkeypatch):
    async def execute(query, params):
        return [{"news_ids": ["10", "²", "٣", "x"], "news_items": [], "rcept_nos": [], "disclosure_items": []}]

    seen_ids: list = []

    async def news_briefs(conn, ids, limit):
        seen_ids.extend(ids)
        return [], 0, []

    async def disclosure_briefs(conn, rcept_nos):
        return []

    @asynccontextmanager
    async def connection(timeout=None):
        yield object()

    monkeypatch.setattr(repository.neo4j_database, "execute", execute)
    monkeypatch.setattr(repository.postgres_client, "connection", connection)
    monkeypatch.setattr(rdb, "fetch_news_briefs", news_briefs)
    monkeypatch.setattr(rdb, "fetch_disclosure_briefs", disclosure_briefs)

    res = await repository.get_relationship_evidence("5:abc:1", 5)
    assert res is not None
    assert seen_ids == [10]
