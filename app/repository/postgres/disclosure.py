"""근거 공시 — 간선의 disclosure_rcept_nos 로 보고서명·접수일을 꺼낸다."""

from __future__ import annotations

from psycopg import AsyncConnection

from .base import fetch_all

_DISCLOSURE_BRIEFS_SQL = """
SELECT rcept_no, report_nm, rcept_dt
FROM disclosures
WHERE rcept_no = ANY(%(rcept_nos)s)
ORDER BY rcept_dt DESC, rcept_no DESC
"""


async def fetch_disclosure_briefs(conn: AsyncConnection, rcept_nos: list[str]) -> list[dict]:
    if not rcept_nos:
        return []
    return await fetch_all(conn, _DISCLOSURE_BRIEFS_SQL, {"rcept_nos": rcept_nos})
