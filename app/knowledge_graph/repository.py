"""
Neo4j READ 쿼리 계층.

쿼리는 `center` 노드와 `paths`(가변 길이 경로 목록)를 RETURN하는 공통 모양을 쓰고,
Record -> 스키마 변환(직렬화/dedup)은 knowledge_graph/schemas.py 의 from_record/from_neo4j 가 담당한다.

라벨·관계 타입은 문자열로 박지 않고 core.graph_schema 의 NodeLabel/RelationshipType 에서
가져온다 — beneficiary 와 공유하는 어휘라 한 곳만 고치면 되게. 보간된 쿼리는 드라이버가
요구하는 LiteralString 으로 cast 한다(라벨은 사용자 입력이 아니라 enum 상수이므로 주입
위험 없음 — 사용자 입력은 전부 $key 파라미터로 나간다).
"""

from __future__ import annotations

from typing import LiteralString, cast

from core import NodeLabel, RelationshipType, neo4j_client
from knowledge_graph.schemas import GraphResponse, RelationshipDetail


# DAO
def _company_query(hop: int) -> LiteralString:
    return cast(
        LiteralString,
        f"""
MATCH (c:{NodeLabel.COMPANY} {{ticker: $key}})
OPTIONAL MATCH path = (c)-[*1..{hop}]->(m)
RETURN c AS center, collect(path) AS paths
""",
    )


THEME_QUERY: LiteralString = cast(
    LiteralString,
    f"""
MATCH (t:{NodeLabel.THEME} {{name: $key}})
OPTIONAL MATCH path = (c:{NodeLabel.COMPANY})-[:{RelationshipType.BELONGS_TO}]->(t)
RETURN t AS center, collect(path) AS paths
""",
)

def _theme_query(hop: int) -> LiteralString:
    if hop <= 1:
        return THEME_QUERY
    return cast(
        LiteralString,
        f"""
MATCH (t:{NodeLabel.THEME} {{name: $key}})
OPTIONAL MATCH mpath = (c:{NodeLabel.COMPANY})-[:{RelationshipType.BELONGS_TO}]->(t)
OPTIONAL MATCH epath = (c)-[*1..{hop - 1}]->(m)
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
    records = await neo4j_client.execute(query, {"key": key})
    if not records:  # 기준 노드 자체가 없음
        return None
    return GraphResponse.from_record(records[0])


async def get_company_graph(ticker: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_company_query(hop), ticker)


async def get_theme_graph(name: str, hop: int = 1) -> GraphResponse | None:
    return await _fetch_graph(_theme_query(hop), name)


async def get_relationship_detail(element_id: str) -> RelationshipDetail | None:
    records = await neo4j_client.execute(RELATIONSHIP_QUERY, {"id": element_id})
    if not records:
        return None
    return RelationshipDetail.from_neo4j(records[0]["r"])
