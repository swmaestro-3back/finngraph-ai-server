from __future__ import annotations

from core import postgres_client
from enrich import enrich_graph
from enums import Market, MarketIndex
from news_graph import NewsGraphAccumulator
from repository import neo4j, postgres
from repository.neo4j.mappers import to_event_detail, to_relationship_evidence
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

# 근거·이벤트 상세가 풀에서 커넥션을 기다리는 상한(초) — 게이트웨이 상한(8초) 전에 503 으로 끝낸다.
PG_CONNECT_TIMEOUT = 3.0

# 확장 상한 — 기업당 이웃 수와 전체 노드 수. 모달의 420px 캔버스에서 읽히는 크기에 맞춘다.
NEWS_EXPAND_PER_NODE = 8
NEWS_MAX_NODES = 60


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


async def get_company_events(ticker: str, hop: int = 1) -> CompanyEventsResponse | None:
    response = await neo4j.fetch_company_events(ticker, hop)
    if response is not None:
        await enrich_graph(response)
    return response


async def get_news_graph(news_id: str, hop: int = 1) -> NewsGraphResponse | None:
    """뉴스 시드 관계에서 시작해 hop-1 단계만큼 기업 간 관계를 따라 펼친다.

    시드 0건이면 None(404). hop ≥ 2 면 단계마다 프론티어 기업의 상위 이웃을 붙이고,
    마지막에 담긴 기업들 사이의 관계를 보강해 연결이 빠지지 않게 한다.
    """
    seeds = await neo4j.fetch_news_seeds(news_id)
    if not seeds:  # 이 뉴스를 근거로 가진 관계가 없음
        return None

    acc = NewsGraphAccumulator(max_nodes=NEWS_MAX_NODES)
    acc.add_seeds(seeds)

    frontier = list(acc.seed_company_ids)
    for _ in range(hop - 1):
        if not frontier or acc.truncated:
            break
        records = await neo4j.fetch_news_expansion(frontier, NEWS_EXPAND_PER_NODE)
        frontier = acc.add_expansion(records)

    if hop > 1:
        records = await neo4j.fetch_news_closure(list(acc.companies))
        acc.add_closure(records)

    return acc.to_response()


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


async def get_event_detail(cluster_id: int, limit: int) -> EventDetailResponse | None:
    """이벤트의 키워드·기사·관련 기업(시세 포함). 클러스터가 없으면 None(404)."""
    async with postgres_client.connection(timeout=PG_CONNECT_TIMEOUT) as conn:
        detail = await postgres.fetch_event_detail(conn, cluster_id, limit)
        if detail is None:
            return None
        tickers = sorted({row["ticker"] for row in detail["companies"] if row["ticker"]})
        quotes = await postgres.fetch_stock_quotes(conn, tickers)
    return to_event_detail(detail, quotes)
