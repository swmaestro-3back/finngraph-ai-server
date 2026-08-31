"""
Pydantic 기반 Type-Safe API Response Schema
모든 조회 엔드포인트는 GraphResponse 하나로 통일한다.
"""

from __future__ import annotations

from typing import Any

from neo4j import Record
from neo4j.graph import Node, Path, Relationship
from pydantic import BaseModel, Field


def _to_jsonable(value: Any) -> Any:
    """
    neo4j 임시(date/datetime 등) 타입을 ISO 문자열로 변환.
    나머지는 그대로.
    """
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


class GraphNode(BaseModel):
    """
    그래프 노드 속성은 Label/Type마다 다르기 때문에 properties는 유연한 dict로 설정
    """
    id: str = Field(description="Neo4j Element ID")
    labels: list[str] = Field(description="해당 노드에 붙은 모든 라벨")
    properties: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_neo4j(cls, node: Node) -> GraphNode:
        return cls(
            id=node.element_id,
            labels=list(node.labels),
            properties={k: _to_jsonable(v) for k, v in dict(node).items()},
        )


class GraphRelationship(BaseModel):
    """서브그래프에 실리는 '가벼운' 간선. 위상 + 렌더/필터용 스칼라만.

    근거 배열(disclosure_items, disclosure_rcept_nos, news_items, news_ids)은
    싣지 않는다 — 간선 클릭 시 GET /relationships/{id}로 RelationshipDetail을
    지연 조회한다. 카운트는 간선 굵기·필터에 바로 쓸 수 있게 스칼라로 남긴다.
    """

    id: str = Field(description="Neo4j element_id. 상세 조회 키.")
    type: str = Field(description="관계 타입")
    start: str = Field(description="시작 노드 id")
    end: str = Field(description="끝 노드 id")
    disclosure_count: int = Field(default=0, description="이 관계를 뒷받침하는 공시 건수")
    news_mention_count: int = Field(default=0, description="이 관계를 언급한 뉴스 건수")
    last_mentioned_at: str | None = Field(default=None, description="마지막 언급일 (ISO)")

    @classmethod
    def from_neo4j(cls, rel: Relationship) -> GraphRelationship:
        # 관계 타입마다 속성이 다르다(BELONGS_TO 에는 카운트가 없다) — 없으면 0.
        return cls(
            id=rel.element_id,
            type=rel.type,
            start=rel.start_node.element_id,
            end=rel.end_node.element_id,
            disclosure_count=rel.get("disclosure_count") or 0,
            news_mention_count=rel.get("news_mention_count") or 0,
            last_mentioned_at=_to_jsonable(rel.get("last_mentioned_at")),
        )


class GraphResponse(BaseModel):
    center: str = Field(description="조회 기준 노드의 element_id")
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: Record) -> GraphResponse:
        """center 노드 + collect(path) 결과를 element_id로 dedup 병합한다."""
        center: Node = record["center"]
        paths: list[Path] = record["paths"]

        nodes: dict[str, GraphNode] = {center.element_id: GraphNode.from_neo4j(center)}
        rels: dict[str, GraphRelationship] = {}

        for path in paths:
            if path is None:  # 이웃이 없으면 OPTIONAL MATCH가 null path를 담는다.
                continue
            for n in path.nodes:
                nodes.setdefault(n.element_id, GraphNode.from_neo4j(n))
            for r in path.relationships:
                rels.setdefault(r.element_id, GraphRelationship.from_neo4j(r))

        return cls(
            center=center.element_id,
            nodes=list(nodes.values()),
            relationships=list(rels.values()),
        )


class RelationshipDetail(BaseModel):
    """간선 클릭 시 지연 조회하는 full provenance.

    간선 속성은 관계 타입마다 다르다 — SUPPLIES_TO 는 공시·뉴스 근거 배열
    (disclosure_items, disclosure_rcept_nos, news_items, news_ids)과 카운트·
    최초/최종 언급일을, BELONGS_TO 는 편입 사유(reason)를 갖는다. 그래서
    GraphNode 와 같이 properties 를 유연한 dict 로 두고 있는 그대로 싣는다.
    """

    id: str = Field(description="Neo4j element_id")
    type: str = Field(description="관계 타입")
    start: str
    end: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_neo4j(cls, rel: Relationship) -> RelationshipDetail:
        return cls(
            id=rel.element_id,
            type=rel.type,
            start=rel.start_node.element_id,
            end=rel.end_node.element_id,
            properties={k: _to_jsonable(v) for k, v in dict(rel).items()},
        )
