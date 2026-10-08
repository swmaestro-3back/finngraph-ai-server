from __future__ import annotations

from typing import Any, LiteralString, cast

import rdb
from core import neo4j_database, postgres_client
from enrich import enrich_graph
from enums import Market, MarketIndex
from mappers import (
    group_news_items,
    to_company_events_response,
    to_company_response,
    to_company_themes_response,
    to_event_detail,
    to_relationship_evidence,
    to_supplychain_response,
    to_theme_response,
)
from news_graph import NewsGraphAccumulator
from schemas import (
    CompanyEventsResponse,
    CompanyResponse,
    CompanyThemesResponse,
    EventDetailResponse,
    NewsGraphResponse,
    RelationshipEvidenceResponse,
    SupplyChainResponse,
    ThemeResponse,
)

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

# _THEME_QUERY 와 같은 이유로 Theme / BELONGS_TO 는 객체 대신 임베딩을 뺀 맵으로 투영한다.
_COMPANY_THEMES_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
CALL (c) {
  MATCH (c)-[r:BELONGS_TO]->(t:Theme)
  RETURN collect(t{.*, id: elementId(t), embedding: null}) AS themes,
         collect({id: elementId(r), start: elementId(c), end: elementId(t), reason: r.reason}) AS relationships
}
RETURN c AS company, themes, relationships
"""

# HAS_EVENT 는 (:Company)->(:Event) 한 방향뿐이라, 방향 없이 따라가면 Company / Event 가 번갈아 나온다.
_COMPANY_EVENTS_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
OPTIONAL MATCH path = (c)-[:HAS_EVENT*1..{hop}]-()
RETURN c AS center, collect(path) AS paths
"""

# ---------------------------------------------------------------- 간선 근거

# 근거·이벤트 상세가 풀에서 커넥션을 기다리는 상한(초) — 게이트웨이 상한(8초) 전에 503 으로 끝낸다.
PG_CONNECT_TIMEOUT = 3.0

# 그래프 응답이 준 간선 elementId 로 근거 목록만 꺼낸다 — 제목·날짜는 Postgres 가 갖고 있다.
_RELATIONSHIP_EVIDENCE_QUERY: LiteralString = """
MATCH (:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(:Company)
WHERE elementId(r) = $id
RETURN r.news_ids AS news_ids, r.news_items AS news_items,
       r.disclosure_rcept_nos AS rcept_nos, r.disclosure_items AS disclosure_items
"""

# ---------------------------------------------------------------- 뉴스 그래프

# 이 뉴스를 근거(news_ids)로 가진 기업 간 관계 — 뉴스 그래프의 시드.
# 이벤트·테마는 "뉴스 한 건에서 나온 관계"가 아니라 제외한다.
# news_ids 는 적재 경로에 따라 문자열/정수가 섞일 수 있어 둘 다 본다.
# TODO: 리스트 속성 news_ids 의 IN 은 인덱스를 못 타서 관계 전체를 훑는다 — 데이터가 커지면 (:News) 노드나 조회 테이블로 옮긴다.
_NEWS_SEED_QUERY: LiteralString = """
MATCH (a:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(b:Company)
WHERE $news_id IN r.news_ids OR toInteger($news_id) IN r.news_ids
RETURN a, r, b
"""

# 프론티어 기업마다 근거(뉴스+공시)가 많은 이웃 순으로 per_node 개만 — 허브 기업 하나가 그래프를 터뜨리지 않게 한다.
# 방향 없이 따라가므로 공급자·수요자·인수·투자 어느 쪽이든 이웃이다.
_NEWS_EXPAND_QUERY: LiteralString = """
UNWIND $frontier AS fid
MATCH (n:Company) WHERE elementId(n) = fid
CALL (n) {
  MATCH (n)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]-(m:Company)
  RETURN r, m
  ORDER BY coalesce(r.news_mention_count, 0) + coalesce(r.disclosure_count, 0) DESC
  LIMIT $per_node
}
RETURN r, m
"""

# 이미 담긴 기업들 사이의 관계 전부 — 상위 N에 밀려 빠진 기업 간 간선을 채운다. 노드는 늘지 않는다.
_NEWS_CLOSURE_QUERY: LiteralString = """
MATCH (a:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(b:Company)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN r
"""

# 확장 상한 — 기업당 이웃 수와 전체 노드 수. 모달의 420px 캔버스에서 읽히는 크기에 맞춘다.
NEWS_EXPAND_PER_NODE = 8
NEWS_MAX_NODES = 60

async def get_company(ticker: str) -> CompanyResponse | None:
    records = await neo4j_database.execute(_COMPANY_QUERY, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    response = to_company_response(records[0])
    await enrich_graph(response)
    return response

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
    response = to_supplychain_response(records[0])
    await enrich_graph(response)
    return response

async def get_theme(name: str) -> ThemeResponse | None:
    records = await neo4j_database.execute(_THEME_QUERY, {"key": name})
    if not records:  # 해당 테마 자체가 없음
        return None
    response = to_theme_response(records[0])
    await enrich_graph(response)
    return response

async def get_company_themes(ticker: str) -> CompanyThemesResponse | None:
    records = await neo4j_database.execute(_COMPANY_THEMES_QUERY, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    response = to_company_themes_response(records[0])
    await enrich_graph(response)
    return response

async def get_company_events(ticker: str, hop: int = 1) -> CompanyEventsResponse | None:
    query = cast(LiteralString, _COMPANY_EVENTS_QUERY.format(hop=hop))
    records = await neo4j_database.execute(query, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    response = to_company_events_response(records[0])
    await enrich_graph(response)
    return response


async def get_news_graph(news_id: str, hop: int = 1) -> NewsGraphResponse | None:
    """뉴스 시드 관계에서 시작해 hop-1 단계만큼 기업 간 관계를 따라 펼친다.

    시드 0건이면 None(404). hop ≥ 2 면 단계마다 프론티어 기업의 상위 이웃을 붙이고,
    마지막에 담긴 기업들 사이의 관계를 보강해 연결이 빠지지 않게 한다.
    """
    seeds = await neo4j_database.execute(_NEWS_SEED_QUERY, {"news_id": news_id})
    if not seeds:  # 이 뉴스를 근거로 가진 관계가 없음
        return None

    acc = NewsGraphAccumulator(max_nodes=NEWS_MAX_NODES)
    acc.add_seeds(seeds)

    frontier = list(acc.seed_company_ids)
    for _ in range(hop - 1):
        if not frontier or acc.truncated:
            break
        records = await neo4j_database.execute(
            _NEWS_EXPAND_QUERY, {"frontier": frontier, "per_node": NEWS_EXPAND_PER_NODE}
        )
        frontier = acc.add_expansion(records)

    if hop > 1:
        records = await neo4j_database.execute(_NEWS_CLOSURE_QUERY, {"ids": list(acc.companies)})
        acc.add_closure(records)

    return acc.to_response()


async def get_relationship_evidence(element_id: str, limit: int) -> RelationshipEvidenceResponse | None:
    """간선의 근거 기사(최신 limit 건·전체 건수·월별 건수)와 공시. 간선이 없으면 None(404)."""
    records = await neo4j_database.execute(_RELATIONSHIP_EVIDENCE_QUERY, {"id": element_id})
    if not records:
        return None
    record = records[0]

    items = group_news_items(record["news_ids"] or [], record["news_items"] or [])
    # news_ids 는 적재 경로에 따라 문자열/정수가 섞인다 — 숫자가 아닌 id 는 news.id 와 맞출 수 없어 버린다.
    # isdigit() 은 '²' 같은 유니코드 숫자도 참이라 int() 가 터진다 — ASCII 십진수만 받는다
    news_ids = [int(news_id) for news_id in items if news_id.isascii() and news_id.isdecimal()]
    disclosure_items: dict[str, str | None] = {}
    for rcept_no, item in zip(record["rcept_nos"] or [], record["disclosure_items"] or []):
        disclosure_items.setdefault(str(rcept_no), item)
    for rcept_no in record["rcept_nos"] or []:
        disclosure_items.setdefault(str(rcept_no), None)

    async with postgres_client.connection(timeout=PG_CONNECT_TIMEOUT) as conn:
        news_rows, news_total, monthly = await rdb.fetch_news_briefs(conn, news_ids, limit)
        disclosure_rows = await rdb.fetch_disclosure_briefs(conn, list(disclosure_items))

    return to_relationship_evidence(items, news_rows, news_total, monthly, disclosure_rows, disclosure_items)


async def get_event_detail(cluster_id: int, limit: int) -> EventDetailResponse | None:
    """이벤트의 키워드·기사·관련 기업(시세 포함). 클러스터가 없으면 None(404)."""
    async with postgres_client.connection(timeout=PG_CONNECT_TIMEOUT) as conn:
        detail = await rdb.fetch_event_detail(conn, cluster_id, limit)
        if detail is None:
            return None
        tickers = sorted({row["ticker"] for row in detail["companies"] if row["ticker"]})
        quotes = await rdb.fetch_stock_quotes(conn, tickers)
    return to_event_detail(detail, quotes)
