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

    무거운 provenance(news_ids, source_sentences, mentioned_ats)는 싣지 않는다.
    간선 클릭 시 GET /relationship/{id}로 RelationshipDetail을 지연 조회한다.
    """

    id: str = Field(description="Neo4j element_id. 상세 조회 키.")
    type: str = Field(description="관계 타입")
    start: str = Field(description="시작 노드 id")
    end: str = Field(description="끝 노드 id")
    mention_count: int | None = Field(default=None, description="언급된 뉴스 개수")

    @classmethod
    def from_neo4j(cls, rel: Relationship) -> GraphRelationship:
        return cls(
            id=rel.element_id,
            type=rel.type,
            start=rel.start_node.element_id,
            end=rel.end_node.element_id,
            mention_count=rel.get("mention_count"),
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


class NewsGraphResponse(GraphResponse):

    seed_relationship_ids: list[str] = Field(
        default_factory=list,
    )

    @classmethod
    def from_seed_and_paths(
        cls, seed_records: list[Record], expand_paths: list[Path]
    ) -> NewsGraphResponse:
 
        nodes: dict[str, GraphNode] = {}
        rels: dict[str, GraphRelationship] = {}
        seed_ids: list[str] = []
        center_id = ""
        center_mentions = -1

        for record in seed_records:
            a: Node = record["a"]
            r: Relationship = record["r"]
            b: Node = record["b"]
            nodes.setdefault(a.element_id, GraphNode.from_neo4j(a))
            nodes.setdefault(b.element_id, GraphNode.from_neo4j(b))
            if r.element_id not in rels:
                rels[r.element_id] = GraphRelationship.from_neo4j(r)
                seed_ids.append(r.element_id)
            mentions = r.get("mention_count") or 0
            if mentions > center_mentions:
                center_mentions = mentions
                center_id = a.element_id

        for path in expand_paths:
            if path is None:
                continue
            for n in path.nodes:
                nodes.setdefault(n.element_id, GraphNode.from_neo4j(n))
            for r in path.relationships:
                rels.setdefault(r.element_id, GraphRelationship.from_neo4j(r))

        return cls(
            center=center_id,
            nodes=list(nodes.values()),
            relationships=list(rels.values()),
            seed_relationship_ids=seed_ids,
        )


class RelationshipDetail(BaseModel):
    """간선 클릭 시 지연 조회하는 full provenance."""

    id: str = Field(description="Neo4j element_id")
    type: str = Field(description="관계 타입")
    start: str
    end: str
    news_ids: list[str] = Field(default_factory=list)
    source_sentences: list[str] = Field(default_factory=list)
    mentioned_ats: list[str] = Field(default_factory=list, description="각 근거 저장 날짜 (ISO)")
    mention_count: int | None = None
    first_mentioned_at: str | None = None
    last_mentioned_at: str | None = None

    @classmethod
    def from_neo4j(cls, rel: Relationship) -> RelationshipDetail:
        return cls(
            id=rel.element_id,
            type=rel.type,
            start=rel.start_node.element_id,
            end=rel.end_node.element_id,
            news_ids=[str(v) for v in (rel.get("news_ids") or [])],
            source_sentences=list(rel.get("source_sentences") or []),
            mentioned_ats=_to_jsonable(rel.get("mentioned_ats") or []),
            mention_count=rel.get("mention_count"),
            first_mentioned_at=_to_jsonable(rel.get("first_mentioned_at")),
            last_mentioned_at=_to_jsonable(rel.get("last_mentioned_at")),
        )
