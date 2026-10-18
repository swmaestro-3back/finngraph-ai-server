from __future__ import annotations

from repository import neo4j
from schemas import CompanyThemesResponse, ThemeResponse

from .enrich import enrich_graph


async def get_theme(name: str) -> ThemeResponse | None:
    response = await neo4j.fetch_theme(name)
    if response is not None:
        await enrich_graph(response)
    return response


async def get_company_themes(ticker: str) -> CompanyThemesResponse | None:
    response = await neo4j.fetch_company_themes(ticker)
    if response is not None:
        await enrich_graph(response)
    return response
