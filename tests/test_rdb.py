"""rdb — SQL 문자열은 integration 이 보고, 여기서는 빈 입력 단락·키잉·값 변환만 본다."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import rdb
from fake_pg import FakeConn


def test_plain_converts_decimal_and_dates():
    assert rdb.plain(Decimal("-1.86")) == -1.86
    assert rdb.plain(date(2026, 10, 8)) == "2026-10-08"
    assert rdb.plain(datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)) == "2026-10-08T09:00:00+00:00"
    assert rdb.plain(7) == 7 and rdb.plain(None) is None and rdb.plain(["a"]) == ["a"]


async def test_stock_quotes_skip_query_when_no_tickers():
    conn = FakeConn()
    assert await rdb.fetch_stock_quotes(conn, []) == {}
    assert conn.calls == []


async def test_stock_quotes_keyed_by_ticker_with_plain_values():
    conn = FakeConn([{
        "ticker": "005930", "price": Decimal("263500"), "change": Decimal("-1.86"),
        "price_date": date(2026, 10, 8), "market_cap": 1540494253000000,
        "r_1w": Decimal("-4.01"), "r_1m": None, "r_3m": Decimal("-1.31"),
    }])
    quotes = await rdb.fetch_stock_quotes(conn, ["005930"])
    assert quotes == {"005930": {
        "price": 263500.0, "change": -1.86, "price_date": "2026-10-08",
        "market_cap": 1540494253000000, "r_1w": -4.01, "r_1m": None, "r_3m": -1.31,
    }}
    assert conn.calls[0][1] == {"tickers": ["005930"]}


async def test_theme_quotes_keyed_by_theme_id():
    conn = FakeConn([{
        "theme_id": 1, "change": Decimal("1.77"), "price_date": date(2026, 10, 8),
        "r_1w": Decimal("7.73"), "r_1m": Decimal("8.51"), "r_3m": None, "market_cap": 336627654136000,
    }])
    quotes = await rdb.fetch_theme_quotes(conn, [1])
    assert quotes[1]["change"] == 1.77 and quotes[1]["market_cap"] == 336627654136000
    assert "theme_id" not in quotes[1]
    assert conn.calls[0][1] == {"theme_ids": [1]}


async def test_event_meta_keyed_by_cluster_id():
    conn = FakeConn([{"cluster_id": 9, "keywords": ["hbm"], "member_count": 3, "representative_news_id": None}])
    assert await rdb.fetch_event_meta(conn, [9]) == {
        9: {"keywords": ["hbm"], "member_count": 3, "representative_news_id": None}
    }


async def test_theme_and_event_skip_query_when_empty():
    conn = FakeConn()
    assert await rdb.fetch_theme_quotes(conn, []) == {}
    assert await rdb.fetch_event_meta(conn, []) == {}
    assert conn.calls == []
