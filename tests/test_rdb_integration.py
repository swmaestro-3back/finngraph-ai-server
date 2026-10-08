"""rdb SQL 이 실제 ETL 스키마에서 실행되는지 — 로컬 스택 ETL DB(localhost:15432) 필요.

데이터는 심지 않고 DB 에 있는 행을 하나 골라 쓴다. 없으면 skip.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from psycopg import AsyncConnection

import rdb
from core.config import settings

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def conn():
    connection = await AsyncConnection.connect(settings.database_url)
    yield connection
    await connection.close()


async def pick(conn: AsyncConnection, sql: str):
    async with conn.cursor() as cur:
        await cur.execute(sql)
        row = await cur.fetchone()
    if row is None:
        pytest.skip(f"로컬 DB 에 데이터가 없다: {sql}")
    return row[0]


async def test_stock_quotes(conn):
    ticker = await pick(conn, """
        SELECT s.ticker FROM stocks s WHERE s.is_active
          AND EXISTS (SELECT 1 FROM stock_candles_daily c WHERE c.stock_id = s.id) LIMIT 1""")
    quotes = await rdb.fetch_stock_quotes(conn, [ticker, "NO-SUCH-TICKER"])
    assert set(quotes) == {ticker}
    quote = quotes[ticker]
    assert set(quote) == {"price", "change", "price_date", "market_cap", "r_1w", "r_1m", "r_3m"}
    assert isinstance(quote["price"], float) and isinstance(quote["price_date"], str)


async def test_theme_quotes(conn):
    theme_id = await pick(conn, "SELECT theme_id FROM theme_candles_daily LIMIT 1")
    quotes = await rdb.fetch_theme_quotes(conn, [theme_id])
    assert set(quotes[theme_id]) == {"change", "price_date", "r_1w", "r_1m", "r_3m", "market_cap"}
    assert quotes[theme_id]["market_cap"] is None or isinstance(quotes[theme_id]["market_cap"], int)


async def test_event_meta(conn):
    cluster_id = await pick(conn, "SELECT id FROM news_clusters LIMIT 1")
    meta = await rdb.fetch_event_meta(conn, [cluster_id])
    assert isinstance(meta[cluster_id]["keywords"], list)
    assert isinstance(meta[cluster_id]["member_count"], int)


async def test_news_briefs(conn):
    news_id = await pick(conn, "SELECT id FROM news WHERE published_at IS NOT NULL LIMIT 1")
    rows, total, monthly = await rdb.fetch_news_briefs(conn, [news_id, -1], 5)
    assert [r["news_id"] for r in rows] == [str(news_id)]
    assert total == 1 and monthly[0]["count"] == 1 and len(monthly[0]["month"]) == 7


async def test_disclosure_briefs(conn):
    rcept_no = await pick(conn, "SELECT rcept_no FROM disclosures LIMIT 1")
    rows = await rdb.fetch_disclosure_briefs(conn, [rcept_no])
    assert rows[0]["rcept_no"] == rcept_no and isinstance(rows[0]["rcept_dt"], str)


async def test_event_detail(conn):
    cluster_id = await pick(conn, "SELECT cluster_id FROM news WHERE cluster_id IS NOT NULL LIMIT 1")
    detail = await rdb.fetch_event_detail(conn, cluster_id, 5)
    assert detail["cluster_id"] == cluster_id
    assert detail["news_total"] >= len(detail["news"])
    assert all(set(c) == {"name", "ticker"} for c in detail["companies"])
    assert await rdb.fetch_event_detail(conn, -1, 5) is None
