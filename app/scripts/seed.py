from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, LiteralString, cast

from core import neo4j_database

logger = logging.getLogger(__name__)

_SEED_FILE = Path(__file__).with_name("seed.json")

_CONSTRAINTS: list[tuple[str, str, str]] = [
    # (제약명, 라벨, 유니크 속성)
    ("stock_ticker_unique", "Stock", "ticker"),
    ("country_iso_alp2_unique", "Country", "iso_alp2"),
    ("commodity_name_unique", "Commodity", "name"),
    ("product_name_unique", "Product", "name"),
    ("theme_name_unique", "Theme", "name"),
]

_DATE_SCALAR_FIELDS = frozenset({"first_mentioned_at", "last_mentioned_at", "created_at"})
_DATE_LIST_FIELDS = frozenset({"mentioned_ats"})


async def create_constraints() -> None:
    """
    CONSTRAINTS 생성
    """
    for name, label, prop in _CONSTRAINTS:
        query = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        await neo4j_database.execute(cast(LiteralString, query))
    logger.info("Constraints ensured (%d)", len(_CONSTRAINTS))


def _convert_dates(props: dict[str, Any]) -> dict[str, Any]:
    """스키마상 date 타입인 속성만 ISO 문자열에서 datetime.date 로 변환한다."""
    converted: dict[str, Any] = {}
    for key, value in props.items():
        if key in _DATE_SCALAR_FIELDS and isinstance(value, str):
            converted[key] = datetime.date.fromisoformat(value)
        elif key in _DATE_LIST_FIELDS and isinstance(value, list):
            converted[key] = [
                datetime.date.fromisoformat(v) if isinstance(v, str) else v for v in value
            ]
        else:
            converted[key] = value
    return converted


async def _upsert_node(node: dict[str, Any]) -> None:
    labels = ":".join(node["labels"])  # 예: "Stock:KOSPI"
    key_prop = node["key_prop"]
    props = _convert_dates(node["properties"])
    query = f"MERGE (n:{labels} {{{key_prop}: $key}}) SET n += $props"
    await neo4j_database.execute(
        cast(LiteralString, query),
        {"key": props[key_prop], "props": props},
    )


async def _upsert_relationship(rel: dict[str, Any]) -> None:
    start, end = rel["start"], rel["end"]
    props = _convert_dates(rel.get("properties") or {})
    query = (
        f"MATCH (a:{start['label']} {{{start['key_prop']}: $start_key}}) "
        f"MATCH (b:{end['label']} {{{end['key_prop']}: $end_key}}) "
        f"MERGE (a)-[r:{rel['type']}]->(b) "
        f"SET r += $props"
    )
    await neo4j_database.execute(
        cast(LiteralString, query),
        {"start_key": start["key_val"], "end_key": end["key_val"], "props": props},
    )


async def _has_existing_data() -> bool:
    """DB 에 노드가 하나라도 있으면 True. 이미 시드된 DB 로 판단해 재적재를 건너뛴다."""
    records = await neo4j_database.execute("MATCH (n) RETURN count(n) AS c")
    node_count = records[0]["c"]
    if node_count > 0:
        logger.info("Skip seeding: %d node(s) already exist", node_count)
        return True
    return False


async def seed() -> None:
    """CREAT CONSTRAINTS -> NODE UPSERT -> RELATIONSHIP UPSERT 순으로 시드를 적재
    """

    # 이미 데이터가 하나라도 존재한다면 seed 과정 스킵
    if await _has_existing_data():
        return

    await create_constraints()

    data = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
    nodes: list[dict[str, Any]] = data.get("nodes", [])
    relationships: list[dict[str, Any]] = data.get("relationships", [])

    for node in nodes:
        await _upsert_node(node)
    logger.info("Seeded %d node(s)", len(nodes))

    # 관계는 양 끝 노드가 먼저 존재해야 하므로 노드 적재 이후에 건다.
    for rel in relationships:
        await _upsert_relationship(rel)
    logger.info("Seeded %d relationship(s)", len(relationships))
