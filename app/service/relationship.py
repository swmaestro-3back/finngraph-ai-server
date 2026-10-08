from __future__ import annotations

from typing import Any

from core import postgres_client
from repository import neo4j, postgres
from schemas import EvidenceDisclosure, EvidenceNews, MonthlyCount, RelationshipEvidenceResponse

from .common import PG_CONNECT_TIMEOUT


async def get_relationship_evidence(element_id: str, limit: int) -> RelationshipEvidenceResponse | None:
    """간선의 근거 기사(최신 limit 건·전체 건수·월별 건수)와 공시. 간선이 없으면 None(404)."""
    refs = await neo4j.fetch_relationship_evidence(element_id)
    if refs is None:
        return None

    async with postgres_client.connection(timeout=PG_CONNECT_TIMEOUT) as conn:
        news_rows, news_total, monthly = await postgres.fetch_news_briefs(conn, refs.news_ids, limit)
        disclosure_rows = await postgres.fetch_disclosure_briefs(conn, list(refs.disclosure_items))

    return to_relationship_evidence(
        refs.items, news_rows, news_total, monthly, disclosure_rows, refs.disclosure_items
    )


def to_relationship_evidence(
    items: dict[str, list[str]],
    news_rows: list[dict[str, Any]],
    news_total: int,
    monthly: list[dict[str, Any]],
    disclosure_rows: list[dict[str, Any]],
    disclosure_items: dict[str, str | None],
) -> RelationshipEvidenceResponse:
    return RelationshipEvidenceResponse(
        news=[EvidenceNews(**row, items=items.get(row["news_id"], [])) for row in news_rows],
        news_total=news_total,
        monthly=[MonthlyCount(**row) for row in monthly],
        disclosures=[
            EvidenceDisclosure(**row, item=disclosure_items.get(row["rcept_no"]))
            for row in disclosure_rows
        ],
    )
