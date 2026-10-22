from __future__ import annotations

from typing import Any

from core import postgres_client
from repository import neo4j, postgres
from schemas import CompanyEventsResponse, EventCompany, EventDetailResponse, NewsBrief, StockQuote

from .common import PG_CONNECT_TIMEOUT
from .enrich import enrich_graph


async def get_company_events(ticker: str, hop: int = 1) -> CompanyEventsResponse | None:
    response = await neo4j.fetch_company_events(ticker, hop)
    if response is not None:
        await enrich_graph(response)
    return response


async def get_event_detail(cluster_id: int, limit: int) -> EventDetailResponse | None:
    """이벤트의 키워드·기사·관련 기업(시세 포함). 클러스터가 없으면 None(404)."""
    async with postgres_client.connection(timeout=PG_CONNECT_TIMEOUT) as conn:
        detail = await postgres.fetch_event_detail(conn, cluster_id, limit)
        if detail is None:
            return None
        tickers = sorted({row["ticker"] for row in detail["companies"] if row["ticker"]})
        quotes = await postgres.fetch_stock_quotes(conn, tickers)
    return to_event_detail(detail, quotes)


def to_event_detail(detail: dict[str, Any], quotes: dict[str, dict[str, Any]]) -> EventDetailResponse:
    companies = [
        EventCompany(
            name=row["name"],
            ticker=row["ticker"],
            quote=StockQuote(**quotes[row["ticker"]]) if row["ticker"] in quotes else None,
        )
        for row in detail["companies"]
    ]
    news = [NewsBrief(**row) for row in detail["news"]]
    fields = {k: v for k, v in detail.items() if k not in ("companies", "news")}
    return EventDetailResponse(**fields, news=news, companies=companies)
