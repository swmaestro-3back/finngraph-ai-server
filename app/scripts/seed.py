from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, LiteralString, cast

from core import neo4j_database

logger = logging.getLogger(__name__)

# seed.json 은 이 파일과 같은 디렉토리에 둔다.
_SEED_FILE = Path(__file__).with_name("seed.json")

# docs/neo4j-schema.md 의 Key(유니크 제약) 컬럼과 1:1로 대응한다.
# 라벨/속성명을 f-string 으로 넣지만 전부 코드 내 상수(신뢰 가능한 값)이므로 안전하다.
_CONSTRAINTS: list[tuple[str, str, str]] = [
    # (제약명, 라벨, 유니크 속성)
    ("stock_ticker_unique", "Stock", "ticker"),
    ("country_iso_alp2_unique", "Country", "iso_alp2"),
    ("commodity_name_unique", "Commodity", "name"),
    ("product_name_unique", "Product", "name"),
    ("theme_name_unique", "Theme", "name"),
]

# Neo4j Date 타입으로 저장해야 하는 속성. ISO 문자열 -> datetime.date 로 변환하면
# neo4j 드라이버가 자동으로 Date 로 직렬화한다.
_DATE_SCALAR_FIELDS = frozenset({"first_mentioned_at", "last_mentioned_at", "created_at"})
_DATE_LIST_FIELDS = frozenset({"mentioned_ats"})


async def create_constraints() -> None:
    """노드 유니크 제약을 먼저 건다. 시드 이전에 반드시 호출한다.

    Neo4j 에는 PK 개념이 없어 유니크 제약으로 PK처럼 동작할 필드를 지정한다.
    제약을 걸면 B-Tree 인덱스도 자동 생성되어 MERGE 조회가 빨라진다.
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


async def seed() -> None:
    """제약 생성 -> 노드 upsert -> 관계 upsert 순으로 시드를 적재한다."""
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
