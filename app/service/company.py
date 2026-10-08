from __future__ import annotations

from enums import Market, MarketIndex
from repository import neo4j
from schemas import CompanyResponse, SupplyChainResponse

from .enrich import enrich_graph


async def get_company(ticker: str) -> CompanyResponse | None:
    response = await neo4j.fetch_company(ticker)
    if response is not None:
        await enrich_graph(response)
    return response


async def get_company_supplychain(
    ticker: str,
    hop: int = 1,
    market: Market | None = None,
    index: MarketIndex | None = None,
) -> SupplyChainResponse | None:
    response = await neo4j.fetch_company_supplychain(ticker, hop, market, index)
    if response is not None:
        await enrich_graph(response)
    return response
