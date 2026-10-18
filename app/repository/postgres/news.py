"""근거 기사 — 간선의 news_ids 로 제목·링크·발행일과 월별 건수를 꺼낸다."""

from __future__ import annotations

from psycopg import AsyncConnection

from .base import fetch_all

# 전체 건수는 윈도우 count 로 같은 쿼리에 싣는다 — LIMIT 전에 세므로 한 번 더 묻지 않는다.
_NEWS_BRIEFS_SQL = """
SELECT id::text AS news_id, title, link AS url, originallink AS original_url, published_at,
       count(*) OVER () AS total
FROM news
WHERE id = ANY(%(ids)s)
ORDER BY published_at DESC NULLS LAST, id DESC
LIMIT %(limit)s
"""

_NEWS_MONTHLY_SQL = """
SELECT to_char(date_trunc('month', published_at), 'YYYY-MM') AS month, count(*) AS count
FROM news
WHERE id = ANY(%(ids)s) AND published_at IS NOT NULL
GROUP BY 1
ORDER BY 1
"""


async def fetch_news_briefs(
    conn: AsyncConnection, news_ids: list[int], limit: int
) -> tuple[list[dict], int, list[dict]]:
    """(최신 limit 건, 전체 건수, 월별 건수). 전체 건수는 발행일 없는 기사도 센다."""
    if not news_ids:
        return [], 0, []
    rows = await fetch_all(conn, _NEWS_BRIEFS_SQL, {"ids": news_ids, "limit": limit})
    total = rows[0]["total"] if rows else 0
    for row in rows:
        row.pop("total", None)
    monthly = await fetch_all(conn, _NEWS_MONTHLY_SQL, {"ids": news_ids})
    return rows, total, monthly
