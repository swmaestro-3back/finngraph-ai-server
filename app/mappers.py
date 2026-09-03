from __future__ import annotations

from typing import Any

from neo4j import Record
from neo4j.graph import Node, Path, Relationship

from schemas import (
    BelongsToRelationship,
    CompanyNode,
    DisclosureMention,
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


def build_theme(node: Node) -> ThemeNode:
    fields = {k: v for k, v in _properties(node).items() if k not in _RESERVED_NODE_KEYS}
    return ThemeNode(id=node.element_id, **fields)


# ---------------------------------------------------------------- 간선


def _zip_mentions(keys: list[Any], items: list[Any]) -> list[tuple[str, str | None]]:
    """키 리스트를 기준으로 항목을 인덱스 대응시킨다.

    ETL 오류로 길이가 어긋나면 남는 항목은 None이 된다. 키 없는 항목은 식별자가 없어 버린다.
    """
    return [
        (str(key), items[i] if i < len(items) else None) for i, key in enumerate(keys)
    ]


def build_supply(rel: Relationship) -> SupplyRelationship:
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
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
        news_mention_count=properties.get("news_mention_count") or 0,
        news=news,
        disclosure_count=properties.get("disclosure_count") or 0,
        disclosures=disclosures,
        first_mentioned_at=properties.get("first_mentioned_at"),
        last_mentioned_at=properties.get("last_mentioned_at"),
    )


def build_belongs_to(rel: Relationship) -> BelongsToRelationship:
    return BelongsToRelationship(
        id=rel.element_id,
        start=rel.start_node.element_id,
        end=rel.end_node.element_id,
        reason=_properties(rel).get("reason"),
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
            companies.setdefault(node.element_id, build_company(node))
        for rel in path.relationships:
            rels.setdefault(rel.element_id, build_supply(rel))

    return SupplyChainResponse(
        companies=list(companies.values()), relationships=list(rels.values())
    )


def to_theme_response(record: Record) -> ThemeResponse:
    """RETURN t AS theme, collect(c) AS companies, collect(r) AS relationships 레코드를 응답으로 조립한다."""
    theme: Node = record["theme"]
    # 테마주가 없으면 OPTIONAL MATCH가 null을 담는다.
    company_nodes: list[Node] = [n for n in record["companies"] if n is not None]
    rels: list[Relationship] = [r for r in record["relationships"] if r is not None]

    return ThemeResponse(
        theme=build_theme(theme),
        companies=[build_company(node) for node in company_nodes],
        relationships=[build_belongs_to(rel) for rel in rels],
    )
