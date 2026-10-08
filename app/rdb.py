"""그래프 응답에 붙이는 ETL Postgres 조회 — 커넥션을 받아 행(dict)만 돌려준다.

커넥션 수명·실패 처리·응답 모델 조립은 호출하는 쪽(enrich, repository) 소관이다.
값은 응답 모델이 그대로 받도록 Decimal → float, date/datetime → ISO 문자열로 바꿔 돌려준다.
입력은 전부 %(name)s 파라미터로만 나간다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):  # datetime 도 date 의 하위 클래스다
        return value.isoformat()
    return value


async def _fetch_all(conn: AsyncConnection, query: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [{k: plain(v) for k, v in row.items()} for row in await cur.fetchall()]


async def _fetch_one(conn: AsyncConnection, query: str, params: Any = None) -> dict | None:
    rows = await _fetch_all(conn, query, params)
    return rows[0] if rows else None


# ── 시세 ────────────────────────────────────────────────────────────────────

# 종목마다 최신 일봉 1행과 최신 밸류에이션 1행. 두 테이블 PK 가 (종목, trade_date) 라 인덱스로 바로 찾는다.
# 시세가 없는 활성 종목(해외 등)도 행은 나오고 값만 NULL 이다.
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

_EVENT_META_SQL = """
SELECT id AS cluster_id, keywords, member_count, representative_news_id
FROM news_clusters
WHERE id = ANY(%(cluster_ids)s)
"""


async def fetch_stock_quotes(conn: AsyncConnection, tickers: list[str]) -> dict[str, dict]:
    if not tickers:
        return {}
    rows = await _fetch_all(conn, _STOCK_QUOTES_SQL, {"tickers": tickers})
    return {row.pop("ticker"): row for row in rows}


async def fetch_theme_quotes(conn: AsyncConnection, theme_ids: list[int]) -> dict[int, dict]:
    if not theme_ids:
        return {}
    rows = await _fetch_all(conn, _THEME_QUOTES_SQL, {"theme_ids": theme_ids})
    return {row.pop("theme_id"): row for row in rows}


async def fetch_event_meta(conn: AsyncConnection, cluster_ids: list[int]) -> dict[int, dict]:
    if not cluster_ids:
        return {}
    rows = await _fetch_all(conn, _EVENT_META_SQL, {"cluster_ids": cluster_ids})
    return {row.pop("cluster_id"): row for row in rows}


# ── 근거 기사·공시 ────────────────────────────────────────────────────────────

_NEWS_BRIEFS_SQL = """
SELECT id::text AS news_id, title, link AS url, originallink AS original_url, published_at
FROM news
WHERE id = ANY(%(ids)s)
ORDER BY published_at DESC NULLS LAST, id DESC
LIMIT %(limit)s
"""

_NEWS_TOTAL_SQL = "SELECT count(*) AS total FROM news WHERE id = ANY(%(ids)s)"

_NEWS_MONTHLY_SQL = """
SELECT to_char(date_trunc('month', published_at), 'YYYY-MM') AS month, count(*) AS count
FROM news
WHERE id = ANY(%(ids)s) AND published_at IS NOT NULL
GROUP BY 1
ORDER BY 1
"""

_DISCLOSURE_BRIEFS_SQL = """
SELECT rcept_no, report_nm, rcept_dt
FROM disclosures
WHERE rcept_no = ANY(%(rcept_nos)s)
ORDER BY rcept_dt DESC, rcept_no DESC
"""


async def fetch_news_briefs(
    conn: AsyncConnection, news_ids: list[int], limit: int
) -> tuple[list[dict], int, list[dict]]:
    """(최신 limit 건, 전체 건수, 월별 건수). 전체 건수는 발행일 없는 기사도 센다."""
    if not news_ids:
        return [], 0, []
    rows = await _fetch_all(conn, _NEWS_BRIEFS_SQL, {"ids": news_ids, "limit": limit})
    total = await _fetch_one(conn, _NEWS_TOTAL_SQL, {"ids": news_ids})
    monthly = await _fetch_all(conn, _NEWS_MONTHLY_SQL, {"ids": news_ids})
    return rows, (total or {}).get("total", 0), monthly


async def fetch_disclosure_briefs(conn: AsyncConnection, rcept_nos: list[str]) -> list[dict]:
    if not rcept_nos:
        return []
    return await _fetch_all(conn, _DISCLOSURE_BRIEFS_SQL, {"rcept_nos": rcept_nos})


# ── 이벤트 상세 ──────────────────────────────────────────────────────────────

_EVENT_CLUSTER_SQL = """
SELECT id AS cluster_id, title, keywords, member_count, representative_news_id,
       first_published_at, last_published_at
FROM news_clusters
WHERE id = %(id)s
"""

# 뉴스 모달(Spring /news/{id})이 미분석 기사에 404 를 주므로 열 수 있는 기사만 싣는다.
_EVENT_NEWS_SQL = """
SELECT id::text AS news_id, title, link AS url, originallink AS original_url, published_at
FROM news
WHERE cluster_id = %(id)s AND triple_extracted IS NOT NULL
ORDER BY published_at DESC NULLS LAST, id DESC
LIMIT %(limit)s
"""

_EVENT_NEWS_TOTAL_SQL = "SELECT count(*) AS total FROM news WHERE cluster_id = %(id)s"

_EVENT_COMPANIES_SQL = """
SELECT DISTINCT c.name, c.ticker
FROM news n
JOIN news_companies nc ON nc.news_id = n.id
JOIN companies c ON c.id = nc.company_id
WHERE n.cluster_id = %(id)s
ORDER BY c.name
"""


async def fetch_event_detail(conn: AsyncConnection, cluster_id: int, limit: int) -> dict | None:
    cluster = await _fetch_one(conn, _EVENT_CLUSTER_SQL, {"id": cluster_id})
    if cluster is None:
        return None
    news = await _fetch_all(conn, _EVENT_NEWS_SQL, {"id": cluster_id, "limit": limit})
    total = await _fetch_one(conn, _EVENT_NEWS_TOTAL_SQL, {"id": cluster_id})
    companies = await _fetch_all(conn, _EVENT_COMPANIES_SQL, {"id": cluster_id})
    return {**cluster, "news": news, "news_total": (total or {}).get("total", 0), "companies": companies}
