from __future__ import annotations

from typing import Any

from neo4j import Record
from neo4j.graph import Node, Path, Relationship

from graph import NodeLabel, RelationshipType
from schemas import (
    BelongsToRelationship,
    CompanyEventsResponse,
    CompanyNode,
    CompanyResponse,
    DisclosureMention,
    EventNode,
    HasEventRelationship,
    NewsMention,
    SupplyChainResponse,
    SupplyRelationship,
    ThemeNode,
    ThemeResponse,
)


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


def _properties(entity: Node | Relationship) -> dict[str, Any]:
    return {k: _to_jsonable(v) for k, v in dict(entity).items()}


# ---------------------------------------------------------------- 노드

# 최상위 필드로 승격할 때 도메인 프로퍼티가 덮어쓰면 안 되는 이름.
_RESERVED_NODE_KEYS = {"id"}


def build_company(node: Node) -> CompanyNode:
    fields = {k: v for k, v in _properties(node).items() if k not in _RESERVED_NODE_KEYS}
    return CompanyNode(id=node.element_id, **fields)


def build_theme(projected: dict[str, Any]) -> ThemeNode:
    """Theme 은 노드 객체가 아니라 Cypher 에서 `t{.*, id: elementId(t), embedding: null}` 로 투영한 맵으로 받는다.

    embedding 은 ai-server 내부에서만 쓰는 값이라 Neo4j 밖으로 꺼내지 않는다.
    """
    return ThemeNode(**_to_jsonable(projected))


def build_event(node: Node) -> EventNode:
    fields = {k: v for k, v in _properties(node).items() if k not in _RESERVED_NODE_KEYS}
    return EventNode(id=node.element_id, **fields)


# ---------------------------------------------------------------- 간선


def _zip_mentions(keys: list[Any], items: list[Any]) -> list[tuple[str, str | None]]:
    """키 리스트를 기준으로 항목을 인덱스 대응시킨다.

    ETL 오류로 길이가 어긋나면 남는 항목은 None이 된다. 키 없는 항목은 식별자가 없어 버린다.
    """
    return [
        (str(key), items[i] if i < len(items) else None) for i, key in enumerate(keys)
    ]


def build_supply(rel: Relationship) -> SupplyRelationship:
    """SUPPLIES_TO 뿐 아니라 같은 근거 속성을 갖는 ACQUIRES / INVESTS_IN 에도 쓴다."""
    properties = _properties(rel)

    news = [
        NewsMention(news_id=news_id, item=item)
        for news_id, item in _zip_mentions(
            properties.get("news_ids") or [], properties.get("news_items") or []
        )
    ]
    disclosures = [
        DisclosureMention(rcept_no=rcept_no, item=item)
        for rcept_no, item in _zip_mentions(
            properties.get("disclosure_rcept_nos") or [],
            properties.get("disclosure_items") or [],
        )
    ]
    return SupplyRelationship(
        id=rel.element_id,
        type=rel.type,
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
        news_mention_count=properties.get("news_mention_count") or 0,
        news=news,
        disclosure_count=properties.get("disclosure_count") or 0,
        disclosures=disclosures,
        first_mentioned_at=properties.get("first_mentioned_at"),
        last_mentioned_at=properties.get("last_mentioned_at"),
    )


def build_has_event(rel: Relationship) -> HasEventRelationship:
    return HasEventRelationship(
        id=rel.element_id,
        type=rel.type,
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
    )


# ---------------------------------------------------------------- 응답


def to_supplychain_response(record: Record) -> SupplyChainResponse:
    """RETURN c AS center, collect(path) AS paths 형태의 레코드를 응답으로 조립한다."""
    center: Node = record["center"]
    paths: list[Path] = record["paths"]

    companies: dict[str, CompanyNode] = {center.element_id: build_company(center)}
    rels: dict[str, SupplyRelationship] = {}

    for path in paths:
        if path is None:  # 이웃이 없으면 OPTIONAL MATCH가 null path를 담는다.
            continue
        for node in path.nodes:
            if node.element_id not in companies:
                companies[node.element_id] = build_company(node)
        for rel in path.relationships:
            if rel.element_id not in rels:
                rels[rel.element_id] = build_supply(rel)

    return SupplyChainResponse(
        companies=list(companies.values()), relationships=list(rels.values())
    )


def to_theme_response(record: Record) -> ThemeResponse:
    """RETURN t{...} AS theme, companies, relationships 레코드를 응답으로 조립한다.

    theme 은 임베딩을 뺀 맵, relationships 는 응답 필드만 담은 맵 목록이다. 테마주가 없으면 두 목록 모두 비어 있다.
    """
    return ThemeResponse(
        theme=build_theme(record["theme"]),
        companies=[build_company(node) for node in record["companies"]],
        relationships=[BelongsToRelationship(**rel) for rel in record["relationships"]],
    )


def to_company_events_response(record: Record) -> CompanyEventsResponse:
    """RETURN c AS center, collect(path) AS paths 형태의 레코드를 응답으로 조립한다.

    경로는 HAS_EVENT 를 방향 없이 따라가므로 노드가 Company / Event 로 번갈아 나온다.
    라벨로 분기해 각각의 목록에 나눠 담는다.
    """
    center: Node = record["center"]
    paths: list[Path] = record["paths"]

    companies: dict[str, CompanyNode] = {center.element_id: build_company(center)}
    events: dict[str, EventNode] = {}
    rels: dict[str, HasEventRelationship] = {}

    for path in paths:
        if path is None:  # 이벤트가 없으면 OPTIONAL MATCH가 null path를 담는다.
            continue
        for node in path.nodes:
            if NodeLabel.EVENT in node.labels:
                if node.element_id not in events:
                    events[node.element_id] = build_event(node)
            else:
                if node.element_id not in companies:
                    companies[node.element_id] = build_company(node)
        for rel in path.relationships:
            if rel.element_id not in rels:
                rels[rel.element_id] = build_has_event(rel)

    return CompanyEventsResponse(
        companies=list(companies.values()),
        events=list(events.values()),
        relationships=list(rels.values()),
    )


def to_company_response(record: Record) -> CompanyResponse:
    """RETURN c AS center, neighbors, themes, relationships, belongs_to 레코드를 응답으로 조립한다.

    neighbors 는 Theme 을 제외한 이웃 노드로, 라벨로 분기해 companies / events 에 나눠 담는다.
    themes 와 belongs_to 는 임베딩을 뺀 맵 목록, relationships 는 BELONGS_TO 를 제외한 간선 객체 목록이다.
    """
    center: Node = record["center"]

    companies: list[CompanyNode] = [build_company(center)]
    events: list[EventNode] = []
    for node in record["neighbors"]:
        if NodeLabel.EVENT in node.labels:
            events.append(build_event(node))
        else:
            companies.append(build_company(node))
    themes = [build_theme(theme) for theme in record["themes"]]

    relationships: list[SupplyRelationship | BelongsToRelationship | HasEventRelationship] = []
    for rel in record["relationships"]:
        if rel.type == RelationshipType.HAS_EVENT:
            relationships.append(build_has_event(rel))
        else:
            relationships.append(build_supply(rel))
    relationships.extend(BelongsToRelationship(**rel) for rel in record["belongs_to"])

    return CompanyResponse(
        companies=companies, themes=themes, events=events, relationships=relationships
    )
