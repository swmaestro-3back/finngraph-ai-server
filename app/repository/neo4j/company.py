"""기업 — 1홉 이웃 그래프와 공급망(SUPPLIES_TO) 서브그래프."""

from __future__ import annotations

from typing import Any, LiteralString, cast

from core import neo4j_database
from enums import Market, MarketIndex
from schemas import CompanyResponse, SupplyChainResponse

from .mappers import to_company_response, to_supplychain_response

# 중심 기업에 붙은 기업/이벤트 이웃과 그 간선만 1홉 가져온다.
# Theme 이웃과 BELONGS_TO 간선은 테마 전용 API(/themes/{name})가 따로 책임지므로 여기서는 제외한다.
_COMPANY_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
CALL (c) {
  MATCH (c)-[r]-(n)
  WHERE NOT n:Theme
  RETURN collect(DISTINCT n) AS neighbors, collect(r) AS relationships
}
RETURN c AS center, neighbors, relationships
"""

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


async def fetch_company(ticker: str) -> CompanyResponse | None:
    records = await neo4j_database.execute(_COMPANY_QUERY, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_company_response(records[0])


async def fetch_company_supplychain(
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
