"""
Neo4j READ 쿼리 + Record -> GraphResponse 직렬화.

각 함수는 db.execute로 얻은 Record를 받아 노드/관계를 element_id로 dedup한 뒤
GraphResponse로 만든다. 쿼리는 `center` 노드와 `paths`(가변 길이 경로 목록)를
RETURN하는 공통 모양을 쓴다.
"""

from __future__ import annotations

from typing import Any, LiteralString

from neo4j import Record
from neo4j.graph import Node, Path, Relationship

from core import neo4j_database
from schemas import GraphNode, GraphRelationship, GraphResponse, RelationshipDetail

# --- Cypher ------------------------------------------------------------------

# item 노드 경유도 1홉으로 세므로 가변 길이 [*1..N]이 그대로 홉 정의를 만족한다.
STOCK_QUERY: LiteralString = """
MATCH (s:Stock {ticker: $key})
OPTIONAL MATCH path = (s)-[*1..3]-(m)
RETURN s AS center, collect(path) AS paths
"""

PRODUCT_QUERY: LiteralString = """
MATCH (n:Product {name: $key})
OPTIONAL MATCH path = (n)-[*1..1]-(m)
RETURN n AS center, collect(path) AS paths
"""

COMMODITY_QUERY: LiteralString = """
MATCH (n:Commodity {name: $key})
OPTIONAL MATCH path = (n)-[*1..1]-(m)
RETURN n AS center, collect(path) AS paths
"""

THEME_QUERY: LiteralString = """
MATCH (t:Theme {name: $key})
OPTIONAL MATCH path = (s:Stock)-[:BELONGS_TO]->(t)
RETURN t AS center, collect(path) AS paths
"""

# 간선 클릭 시 element_id로 단일 관계의 full provenance만 조회.
RELATIONSHIP_QUERY: LiteralString = """
MATCH ()-[r]->()
WHERE elementId(r) = $id
RETURN r
"""


# --- 직렬화 헬퍼 --------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    """neo4j 임시(date/datetime 등) 타입을 ISO 문자열로, 나머지는 그대로."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    # neo4j.time.Date / DateTime / Time 등은 iso_format()을 가진다.
    iso = getattr(value, "iso_format", None)
    if callable(iso):
        return iso()
    return str(value)


def _node(node: Node) -> GraphNode:
    return GraphNode(
        id=node.element_id,
        labels=list(node.labels),
        properties={k: _to_jsonable(v) for k, v in dict(node).items()},
    )


def _relationship(rel: Relationship) -> GraphRelationship:
    """가벼운 간선: 무거운 provenance 배열은 빼고 렌더/필터용 스칼라만 싣는다."""
    return GraphRelationship(
        id=rel.element_id,
        type=rel.type,
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
        mention_count=rel.get("mention_count"),
    )


def _relationship_detail(rel: Relationship) -> RelationshipDetail:
    """full provenance. 간선 상세 조회 전용."""
    return RelationshipDetail(
        id=rel.element_id,
        type=rel.type,
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
        news_ids=list(rel.get("news_ids") or []),
        source_sentences=list(rel.get("source_sentences") or []),
        mentioned_ats=_to_jsonable(rel.get("mentioned_ats") or []),
        mention_count=rel.get("mention_count"),
        first_mentioned_at=_to_jsonable(rel.get("first_mentioned_at")),
        last_mentioned_at=_to_jsonable(rel.get("last_mentioned_at")),
    )


def _build_response(record: Record) -> GraphResponse:
    """center 노드 + collect(path) 결과를 GraphResponse로 dedup 병합."""
    center: Node = record["center"]
    paths: list[Path] = record["paths"]

    nodes: dict[str, GraphNode] = {center.element_id: _node(center)}
    rels: dict[str, GraphRelationship] = {}

    for path in paths:
        if path is None:  # 이웃이 없으면 OPTIONAL MATCH가 null path를 담는다.
            continue
        for n in path.nodes:
            nodes.setdefault(n.element_id, _node(n))
        for r in path.relationships:
            rels.setdefault(r.element_id, _relationship(r))

    return GraphResponse(
        center=center.element_id,
        nodes=list(nodes.values()),
        relationships=list(rels.values()),
    )


# --- 조회 함수 ----------------------------------------------------------------


async def _fetch_graph(query: LiteralString, key: str) -> GraphResponse | None:
    records = await neo4j_database.execute(query, {"key": key})
    if not records:  # 기준 노드 자체가 없음
        return None
    return _build_response(records[0])


async def get_stock_graph(ticker: str) -> GraphResponse | None:
    return await _fetch_graph(STOCK_QUERY, ticker)


async def get_product_graph(name: str) -> GraphResponse | None:
    return await _fetch_graph(PRODUCT_QUERY, name)


async def get_commodity_graph(name: str) -> GraphResponse | None:
    return await _fetch_graph(COMMODITY_QUERY, name)


async def get_theme_graph(name: str) -> GraphResponse | None:
    return await _fetch_graph(THEME_QUERY, name)


async def get_relationship_detail(element_id: str) -> RelationshipDetail | None:
    records = await neo4j_database.execute(RELATIONSHIP_QUERY, {"id": element_id})
    if not records:
        return None
    return _relationship_detail(records[0]["r"])
