"""이벤트(뉴스 클러스터) — 그래프 노드에 붙는 메타와 이벤트 상세."""

from __future__ import annotations

from psycopg import AsyncConnection

from .base import fetch_all, fetch_one

# 건수는 member_count(클러스터 전체 기사 수)다 — V14 부터 승격 상한에 묶이지 않고 멤버 전체를 센다.
_EVENT_META_SQL = """
SELECT id AS cluster_id, keywords, member_count AS news_count, representative_news_id
FROM news_clusters
WHERE id = ANY(%(cluster_ids)s)
"""

# 전체 기사 수(분석 여부 무관)는 클러스터 행에 서브쿼리로 싣는다 — 기사 목록은 분석된 것만 자르므로 따로 센다.
_EVENT_CLUSTER_SQL = """
SELECT nc.id AS cluster_id, nc.title, nc.keywords, nc.representative_news_id,
       nc.first_published_at, nc.last_published_at,
       (SELECT count(*) FROM news n WHERE n.cluster_id = nc.id) AS news_total
FROM news_clusters nc
WHERE nc.id = %(id)s
"""

# 뉴스 모달(Spring /news/{id})이 미분석 기사에 404 를 주므로 열 수 있는 기사만 싣는다.
_EVENT_NEWS_SQL = """
SELECT id::text AS news_id, title, link AS url, originallink AS original_url, published_at
FROM news
WHERE cluster_id = %(id)s AND triple_extracted IS NOT NULL
ORDER BY published_at DESC NULLS LAST, id DESC
LIMIT %(limit)s
"""

_EVENT_COMPANIES_SQL = """
SELECT DISTINCT c.name, c.ticker
FROM news n
JOIN news_companies nc ON nc.news_id = n.id
JOIN companies c ON c.id = nc.company_id
WHERE n.cluster_id = %(id)s
ORDER BY c.name
"""


async def fetch_event_meta(conn: AsyncConnection, cluster_ids: list[int]) -> dict[int, dict]:
    if not cluster_ids:
        return {}
    rows = await fetch_all(conn, _EVENT_META_SQL, {"cluster_ids": cluster_ids})
    return {row.pop("cluster_id"): row for row in rows}


async def fetch_event_detail(conn: AsyncConnection, cluster_id: int, limit: int) -> dict | None:
    cluster = await fetch_one(conn, _EVENT_CLUSTER_SQL, {"id": cluster_id})
    if cluster is None:
        return None
    news = await fetch_all(conn, _EVENT_NEWS_SQL, {"id": cluster_id, "limit": limit})
    companies = await fetch_all(conn, _EVENT_COMPANIES_SQL, {"id": cluster_id})
    return {**cluster, "news": news, "companies": companies}
