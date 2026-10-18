from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):  # datetime 도 date 의 하위 클래스다
        return value.isoformat()
    return value


async def fetch_all(conn: AsyncConnection, query: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [{k: plain(v) for k, v in row.items()} for row in await cur.fetchall()]


async def fetch_one(conn: AsyncConnection, query: str, params: Any = None) -> dict | None:
    rows = await fetch_all(conn, query, params)
    return rows[0] if rows else None
