"""뉴스 그래프 — 뉴스 한 건을 근거로 가진 기업 간 관계(시드)와 그 확장·보강.

세 쿼리는 레코드를 그대로 돌려주고, service 의 NewsGraphAccumulator 가 순서대로 쌓는다.
"""

from __future__ import annotations

from typing import Any, LiteralString

from core import neo4j_database

# 이 뉴스를 근거(news_ids)로 가진 기업 간 관계 — 뉴스 그래프의 시드.
# 이벤트·테마는 "뉴스 한 건에서 나온 관계"가 아니라 제외한다.
# news_ids 는 적재 경로에 따라 문자열/정수가 섞일 수 있어 둘 다 본다.
# TODO: 리스트 속성 news_ids 의 IN 은 인덱스를 못 타서 관계 전체를 훑는다 — 데이터가 커지면 (:News) 노드나 조회 테이블로 옮긴다.
_NEWS_SEED_QUERY: LiteralString = """
MATCH (a:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(b:Company)
WHERE $news_id IN r.news_ids OR toInteger($news_id) IN r.news_ids
RETURN a, r, b
"""

# 프론티어 기업마다 근거(뉴스+공시)가 많은 이웃 순으로 per_node 개만 — 허브 기업 하나가 그래프를 터뜨리지 않게 한다.
# 방향 없이 따라가므로 공급자·수요자·인수·투자 어느 쪽이든 이웃이다.
_NEWS_EXPAND_QUERY: LiteralString = """
UNWIND $frontier AS fid
MATCH (n:Company) WHERE elementId(n) = fid
CALL (n) {
  MATCH (n)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]-(m:Company)
  RETURN r, m
  ORDER BY coalesce(r.news_mention_count, 0) + coalesce(r.disclosure_count, 0) DESC
  LIMIT $per_node
}
RETURN r, m
"""

# 이미 담긴 기업들 사이의 관계 전부 — 상위 N에 밀려 빠진 기업 간 간선을 채운다. 노드는 늘지 않는다.
_NEWS_CLOSURE_QUERY: LiteralString = """
MATCH (a:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(b:Company)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN r
"""


async def fetch_news_seeds(news_id: str) -> list[Any]:
    """`RETURN a, r, b` 레코드 — 없으면 빈 목록."""
    return await neo4j_database.execute(_NEWS_SEED_QUERY, {"news_id": news_id})


async def fetch_news_expansion(frontier: list[str], per_node: int) -> list[Any]:
    """`RETURN r, m` 레코드 — 프론티어 기업마다 상위 per_node 이웃."""
    return await neo4j_database.execute(_NEWS_EXPAND_QUERY, {"frontier": frontier, "per_node": per_node})


async def fetch_news_closure(ids: list[str]) -> list[Any]:
    """`RETURN r` 레코드 — ids 사이의 관계 전부."""
    return await neo4j_database.execute(_NEWS_CLOSURE_QUERY, {"ids": ids})
