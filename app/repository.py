from __future__ import annotations

from typing import Any, LiteralString, cast

from core import neo4j_database
from enums import Market, MarketIndex
from mappers import (
    to_company_events_response,
    to_company_response,
    to_supplychain_response,
    to_theme_response,
)
from schemas import CompanyEventsResponse, CompanyResponse, SupplyChainResponse, ThemeResponse

# 중심 기업에 붙은 모든 간선과 이웃을 1홉만 가져온다.
# Theme 노드(embedding)와 BELONGS_TO 간선(reason_embedding)은 ai-server 내부용 임베딩을 갖고 있어
# 객체 대신 응답 필드만 맵으로 투영해 임베딩이 Neo4j 밖으로 나오지 않게 한다. collect 는 null 을 건너뛴다.
_COMPANY_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
CALL (c) {
  MATCH (c)-[r]-(n)
  RETURN collect(DISTINCT CASE WHEN NOT n:Theme THEN n END) AS neighbors,
         collect(DISTINCT CASE WHEN n:Theme THEN n{.*, id: elementId(n), embedding: null} END) AS themes,
         collect(CASE WHEN type(r) <> 'BELONGS_TO' THEN r END) AS relationships,
         collect(CASE WHEN type(r) = 'BELONGS_TO' THEN
           {id: elementId(r), start: elementId(startNode(r)), end: elementId(endNode(r)), reason: r.reason}
         END) AS belongs_to
}
RETURN c AS center, neighbors, themes, relationships, belongs_to
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

# Theme 노드(embedding)와 BELONGS_TO 간선(reason_embedding)은 ai-server 내부용 임베딩을 갖고 있어
# 객체 대신 응답 필드만 맵으로 투영해 임베딩이 Neo4j 밖으로 나오지 않게 한다.
_THEME_QUERY: LiteralString = """
MATCH (t:Theme)
WHERE t.name = $key
CALL (t) {
  MATCH (c:Company)-[r:BELONGS_TO]->(t)
  RETURN collect(c) AS companies,
         collect({id: elementId(r), start: elementId(c), end: elementId(t), reason: r.reason}) AS relationships
}
RETURN t{.*, id: elementId(t), embedding: null} AS theme, companies, relationships
"""

# HAS_EVENT 는 (:Company)->(:Event) 한 방향뿐이라, 방향 없이 따라가면 Company / Event 가 번갈아 나온다.
_COMPANY_EVENTS_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:HAS_EVENT*1..{hop}]-()
RETURN c AS center, collect(path) AS paths
"""

async def get_company(ticker: str) -> CompanyResponse | None:
    records = await neo4j_database.execute(_COMPANY_QUERY, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_company_response(records[0])

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

async def get_company_events(ticker: str, hop: int = 1) -> CompanyEventsResponse | None:
    query = cast(LiteralString, _COMPANY_EVENTS_QUERY.format(hop=hop))
    records = await neo4j_database.execute(query, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_company_events_response(records[0])
