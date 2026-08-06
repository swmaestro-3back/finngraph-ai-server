"""
API 응답 스키마(Pydantic). 모든 조회 엔드포인트는 GraphResponse 하나로 통일한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """
    그래프 노드 속성은 Label/Type마다 다르기 때문에 properties는 유연한 dict로 설정
    """
    id: str = Field(description="Neo4j Element ID")
    labels: list[str] = Field(description="해당 노드에 붙은 모든 라벨")
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphRelationship(BaseModel):
    """서브그래프에 실리는 '가벼운' 간선. 위상 + 렌더/필터용 스칼라만.

    무거운 provenance(news_ids, source_sentences, mentioned_ats)는 싣지 않는다.
    간선 클릭 시 GET /relationship/{id}로 RelationshipDetail을 지연 조회한다.
    """

    id: str = Field(description="Neo4j element_id. 상세 조회 키.")
    type: str = Field(description="관계 타입 (예: SUPPLIES_TO)")
    start: str = Field(description="시작 노드 id (방향: start -> end)")
    end: str = Field(description="끝 노드 id")
    mention_count: int | None = Field(default=None, description="관측 뉴스 수. 간선 굵기/신뢰도 필터용.")


class GraphResponse(BaseModel):
    center: str = Field(description="조회 기준 노드의 element_id")
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)


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
