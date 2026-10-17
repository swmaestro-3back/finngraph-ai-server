"""psycopg AsyncConnection 흉내 — cursor(row_factory=...) 컨텍스트, execute, fetchall/fetchone 만.

results 는 execute 순서대로 소비할 행 목록들이다. fetchone 은 그 목록의 첫 행(없으면 None).
"""
from __future__ import annotations

from typing import Any


class FakeCursor:
    def __init__(self, conn: "FakeConn"):
        self._conn = conn
        self._rows: list[dict[str, Any]] = []

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def execute(self, query: str, params: Any = None) -> None:
        self._conn.calls.append((query, params))
        self._rows = [dict(r) for r in self._conn.results.pop(0)]

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, *results: list[dict[str, Any]]):
        self.results = list(results)
        self.calls: list[tuple[str, Any]] = []

    def cursor(self, row_factory: Any = None) -> FakeCursor:
        return FakeCursor(self)
