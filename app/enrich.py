"""그래프 응답 노드에 Postgres 데이터를 채운다 — 종목·테마 시세, 이벤트 키워드·건수·대표 기사.

시세는 부가 정보다. 조회 하나가 실패해도 그 부분만 비우고 경고를 남긴 채 그래프는 그대로 돌려준다.
세 조회는 서로 기다리지 않도록 각자 풀에서 커넥션을 받아 동시에 돈다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import rdb
from core import postgres_client
from schemas import CompanyNode, EventNode, StockQuote, ThemeNode, ThemeQuote

logger = logging.getLogger(__name__)

Fetch = Callable[[Any, list], Awaitable[dict]]


async def _query(fetch: Fetch, ids: list) -> dict:
    if not ids:
        return {}
    async with postgres_client.connection() as conn:
        return await fetch(conn, ids)


async def _safe(fetch: Fetch, ids: list) -> dict:
    try:
        return await _query(fetch, ids)
    except Exception:
        logger.warning("graph enrichment failed: %s", fetch.__name__, exc_info=True)
        return {}


def _nodes(response: Any, many: str, one: str) -> list:
    nodes = list(getattr(response, many, None) or [])
    single = getattr(response, one, None)
    if single is not None:
        nodes.append(single)
    return nodes


async def enrich_graph(response: Any) -> None:
    """companies/company, themes/theme, events 속성을 가진 그래프 응답을 제자리에서 채운다."""
    companies: list[CompanyNode] = _nodes(response, "companies", "company")
    themes: list[ThemeNode] = _nodes(response, "themes", "theme")
    events: list[EventNode] = _nodes(response, "events", "event")

    tickers = sorted({c.ticker for c in companies if c.ticker})
    theme_ids = sorted({t.theme_id for t in themes if t.theme_id is not None})
    cluster_ids = sorted({e.cluster_id for e in events if e.cluster_id is not None})

    stock_quotes, theme_quotes, event_meta = await asyncio.gather(
        _safe(rdb.fetch_stock_quotes, tickers),
        _safe(rdb.fetch_theme_quotes, theme_ids),
        _safe(rdb.fetch_event_meta, cluster_ids),
    )

    for company in companies:
        row = stock_quotes.get(company.ticker) if company.ticker else None
        if row is not None:
            company.quote = StockQuote(**row)
    for theme in themes:
        row = theme_quotes.get(theme.theme_id) if theme.theme_id is not None else None
        if row is not None:
            theme.quote = ThemeQuote(**row)
    for event in events:
        meta = event_meta.get(event.cluster_id) if event.cluster_id is not None else None
        if meta is not None:
            event.keywords = meta["keywords"] or []
            event.member_count = meta["member_count"]
            event.representative_news_id = meta["representative_news_id"]
