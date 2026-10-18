"""종목·테마 시세 — 그래프 응답 노드와 이벤트 상세의 관련 기업에 붙는다."""

from __future__ import annotations

from psycopg import AsyncConnection

from .base import fetch_all

# 종목마다 최신 일봉 1행과 최신 밸류에이션 1행. 두 테이블 PK 가 (종목, trade_date) 라 인덱스로 바로 찾는다.
# 시세가 없는 활성 종목(해외 등)도 행은 나오고 값만 NULL 이다 — fetch_stock_quotes 가 걸러 낸다.
_STOCK_QUOTES_SQL = """
SELECT s.ticker,
       c.close        AS price,
       c.change_rate  AS change,
       c.trade_date   AS price_date,
       v.market_cap, v.r_1w, v.r_1m, v.r_3m
FROM stocks s
LEFT JOIN LATERAL (
  SELECT close, change_rate, trade_date FROM stock_candles_daily
  WHERE stock_id = s.id ORDER BY trade_date DESC LIMIT 1
) c ON true
LEFT JOIN LATERAL (
  SELECT market_cap, r_1w, r_1m, r_3m FROM stock_valuations_daily
  WHERE listing_id = s.id ORDER BY trade_date DESC LIMIT 1
) v ON true
WHERE s.is_active AND s.ticker = ANY(%(tickers)s)
"""

# 테마 지수 최신 행 + 기준일 - 7일/1개월/3개월 이전의 가장 가까운 거래일 종가로 기간 수익률.
# ETL 종목 수익률(stock_valuations.UPDATE_RETURNS_SQL)·Spring ThemeIndexStats 와 같은 규칙이다.
# 시가총액은 테마 테이블에 없어 소속 활성 종목의 최신 시가총액을 합한다.
_THEME_QUOTES_SQL = """
SELECT t.id AS theme_id,
       last.change_rate AS change,
       last.trade_date  AS price_date,
       round((last.close / NULLIF(w.close, 0) - 1) * 100, 2) AS r_1w,
       round((last.close / NULLIF(m.close, 0) - 1) * 100, 2) AS r_1m,
       round((last.close / NULLIF(q.close, 0) - 1) * 100, 2) AS r_3m,
       cap.market_cap
FROM themes t
JOIN LATERAL (
  SELECT close, change_rate, trade_date FROM theme_candles_daily
  WHERE theme_id = t.id ORDER BY trade_date DESC LIMIT 1
) last ON true
LEFT JOIN LATERAL (
  SELECT close FROM theme_candles_daily WHERE theme_id = t.id
    AND trade_date <= last.trade_date - INTERVAL '7 days' ORDER BY trade_date DESC LIMIT 1
) w ON true
LEFT JOIN LATERAL (
  SELECT close FROM theme_candles_daily WHERE theme_id = t.id
    AND trade_date <= last.trade_date - INTERVAL '1 month' ORDER BY trade_date DESC LIMIT 1
) m ON true
LEFT JOIN LATERAL (
  SELECT close FROM theme_candles_daily WHERE theme_id = t.id
    AND trade_date <= last.trade_date - INTERVAL '3 months' ORDER BY trade_date DESC LIMIT 1
) q ON true
LEFT JOIN LATERAL (
  SELECT sum(v.market_cap)::bigint AS market_cap
  FROM theme_stocks ts
  JOIN stocks s ON s.id = ts.stock_id AND s.is_active
  JOIN LATERAL (
    SELECT market_cap FROM stock_valuations_daily
    WHERE listing_id = s.id ORDER BY trade_date DESC LIMIT 1
  ) v ON true
  WHERE ts.theme_id = t.id
) cap ON true
WHERE t.id = ANY(%(theme_ids)s)
"""


async def fetch_stock_quotes(conn: AsyncConnection, tickers: list[str]) -> dict[str, dict]:
    if not tickers:
        return {}
    rows = await fetch_all(conn, _STOCK_QUOTES_SQL, {"tickers": tickers})
    quotes = {row.pop("ticker"): row for row in rows}
    # 일봉·밸류에이션이 하나도 없는 종목(해외 등)은 값이 전부 NULL 이다 — 시세가 없는 것으로 친다
    return {ticker: q for ticker, q in quotes.items() if any(v is not None for v in q.values())}


async def fetch_theme_quotes(conn: AsyncConnection, theme_ids: list[int]) -> dict[int, dict]:
    if not theme_ids:
        return {}
    rows = await fetch_all(conn, _THEME_QUOTES_SQL, {"theme_ids": theme_ids})
    return {row.pop("theme_id"): row for row in rows}
