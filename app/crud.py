"""
Neo4j READ 쿼리 계층.

쿼리는 `center` 노드와 `paths`(가변 길이 경로 목록)를 RETURN하는 공통 모양을 쓰고,
Record -> 스키마 변환(직렬화/dedup)은 schemas.py의 from_record/from_neo4j가 담당한다.
"""

from __future__ import annotations

from typing import LiteralString, cast

from core import neo4j_database
from schemas import GraphResponse, RelationshipDetail


# DAO
def _stock_query(hop: int) -> LiteralString:
    return cast(
        LiteralString,
        f"""
MATCH (s:Stock {{ticker: $key}})
OPTIONAL MATCH path = (s)-[*1..{hop}]->(m)
RETURN s AS center, collect(path) AS paths
""",
    )


def _product_query(hop: int) -> LiteralString:
    return cast(
        LiteralString,
        f"""
MATCH (n:Product {{name: $key}})
OPTIONAL MATCH path = (n)-[*1..{hop}]->(m)
RETURN n AS center, collect(path) AS paths
""",
    )


def _commodity_query(hop: int) -> LiteralString:
    return cast(
        LiteralString,
        f"""
MATCH (n:Commodity {{name: $key}})
OPTIONAL MATCH path = (n)-[*1..{hop}]->(m)
RETURN n AS center, collect(path) AS paths
""",
    )


THEME_QUERY: LiteralString = """
MATCH (t:Theme {name: $key})
OPTIONAL MATCH path = (s:Stock)-[:BELONGS_TO]->(t)
RETURN t AS center, collect(path) AS paths
"""

def _theme_query(hop: int) -> LiteralString:
    if hop <= 1:
        return THEME_QUERY
    return cast(
        LiteralString,
        f"""
MATCH (t:Theme {{name: $key}})
OPTIONAL MATCH mpath = (s:Stock)-[:BELONGS_TO]->(t)
OPTIONAL MATCH epath = (s)-[*1..{hop - 1}]->(m)
RETURN t AS center, collect(mpath) + collect(epath) AS paths
""",
    )


# 간선 클릭 시 element_id로 단일 관계의 full provenance만 조회.
RELATIONSHIP_QUERY: LiteralString = """
MATCH ()-[r]->()
WHERE elementId(r) = $id
RETURN r
"""

# SERVICE
async def _fetch_graph(query: LiteralString, key: str) -> GraphResponse | None:
    records = await neo4j_database.execute(query, {"key": key})
    if not records:  # 기준 노드 자체가 없음
        return None
    return GraphResponse.from_record(records[0])


async def get_stock_graph(ticker: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_stock_query(hop), ticker)


async def get_product_graph(name: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_product_query(hop), name)


async def get_commodity_graph(name: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_commodity_query(hop), name)


async def get_theme_graph(name: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_theme_query(hop), name)


async def get_relationship_detail(element_id: str) -> RelationshipDetail | None:
    records = await neo4j_database.execute(RELATIONSHIP_QUERY, {"id": element_id})
    if not records:
        return None
    return RelationshipDetail.from_neo4j(records[0]["r"])
