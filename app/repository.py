from __future__ import annotations

from typing import Any, LiteralString, cast

from core import neo4j_database
from enums import Market, MarketIndex
from mappers import to_supplychain_response, to_theme_response
from schemas import SupplyChainResponse, ThemeResponse

_SUPPLYCHAIN_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:SUPPLIES_TO*1..{hop}]-(m:Company)
RETURN c AS center, collect(path) AS paths
"""

_SUPPLYCHAIN_BY_MARKET_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:SUPPLIES_TO*1..{hop}]-(m:Company)
WHERE all(n IN nodes(path)[1..] WHERE n.market = $market)
RETURN c AS center, collect(path) AS paths
"""

_SUPPLYCHAIN_BY_INDEX_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:SUPPLIES_TO*1..{hop}]-(m:Company)
WHERE all(n IN nodes(path)[1..] WHERE n[$index] = true)
RETURN c AS center, collect(path) AS paths
"""

_THEME_QUERY: LiteralString = """
MATCH (t:Theme {name: $key})
OPTIONAL MATCH (c:Company)-[r:BELONGS_TO]->(t)
RETURN t AS theme, collect(c) AS companies, collect(r) AS relationships
"""

async def get_company_supplychain(
    ticker: str,
    hop: int = 1,
    market: Market | None = None,
    index: MarketIndex | None = None,
) -> SupplyChainResponse | None:
    params: dict[str, Any] = {"key": ticker}
    if market is not None:
        query = _SUPPLYCHAIN_BY_MARKET_QUERY
        params["market"] = market.value
    elif index is not None:
        query = _SUPPLYCHAIN_BY_INDEX_QUERY
        params["index"] = index.value
    else:
        query = _SUPPLYCHAIN_QUERY

    records = await neo4j_database.execute(cast(LiteralString, query.format(hop=hop)), params)
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_supplychain_response(records[0])

async def get_theme(name: str) -> ThemeResponse | None:
    records = await neo4j_database.execute(_THEME_QUERY, {"key": name})
    if not records:  # 해당 테마 자체가 없음
        return None
    return to_theme_response(records[0])
