"""이벤트 — 기업에서 HAS_EVENT 를 따라 펼친 이벤트 서브그래프."""

from __future__ import annotations

from typing import LiteralString, cast

from core import neo4j_database
from schemas import CompanyEventsResponse

from .mappers import to_company_events_response

# HAS_EVENT 는 (:Company)->(:Event) 한 방향뿐이라, 방향 없이 따라가면 Company / Event 가 번갈아 나온다.
_COMPANY_EVENTS_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:HAS_EVENT*1..{hop}]-()
RETURN c AS center, collect(path) AS paths
"""


async def fetch_company_events(ticker: str, hop: int = 1) -> CompanyEventsResponse | None:
    query = cast(LiteralString, _COMPANY_EVENTS_QUERY.format(hop=hop))
    records = await neo4j_database.execute(query, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_company_events_response(records[0])
