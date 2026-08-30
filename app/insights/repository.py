"""인사이트 데이터 계층 — 읽기 전용.

공급망 1-hop 탐색은 Neo4j 다 — subject company(앵커)를 ticker 로 특정하고
그 기업에 공급하는(SUPPLIES_TO 유입) 1-hop 이웃을 가져온다. 후보 선별은
공시 수가 아니라 시장(KOSPI/KOSDAQ)·시가총액 기준이라 stocks + stock_valuations_daily
를 조회하는 fetch_market_info 가 있다. 뉴스·근거 원장(relation_sources)·
재무(company_financials)·밸류에이션(stock_valuations_daily)은 ETL Postgres 를 직접
읽는다. 결과 저장·캐시는 없다 — 실행 관측은 LangSmith 트레이싱으로 한다.

극성 규칙(근거 조회): denied/terminated 근거는 제외한다 — 끊긴 공급 관계를
살아있다고 말하는 사고 방지.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from core import neo4j_database
from graph.models import Anchor

_AFFIRMED = "(polarity IS NULL OR polarity = 'affirmed')"


async def _fetch_all(conn: AsyncConnection, query: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def _fetch_one(conn: AsyncConnection, query: str, params: Any = None) -> dict | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


# ── 앵커 해석 ────────────────────────────────────────────────────────────────


async def resolve_news(conn: AsyncConnection, news_id: int) -> dict | None:
    """클러스터 대표로 정규화한 뉴스 컨텍스트를 반환한다 (없으면 None)."""

    return await _fetch_one(
        conn,
        """
        SELECT rep.id AS rep_news_id, rep.title, rep.summary, rep.published_at
        FROM news n
        JOIN news rep ON rep.id = COALESCE(n.cluster_rep_news_id, n.id)
        WHERE n.id = %(news_id)s
        """,
        {"news_id": news_id},
    )


async def fetch_anchors(conn: AsyncConnection, rep_news_id: int) -> list[Anchor]:
    """앵커 = 이 뉴스(클러스터)가 서술한 관계의 subject 당사자.

    object 는 앵커가 아니다 — 사건을 일으킨 주체(subject)가 앵커고, 후보 탐색
    (유입 SUPPLIES_TO)은 별도로 object ticker 에서 시작한다(fetch_news_parties).
    극성은 거르지 않는다 — 해지·부인 뉴스라도 당사자는 그 기업들이다. 비상장
    subject 도 앵커다: 추천은 못 받지만 사건 맥락으로 심사 프롬프트에 들어간다.
    티커는 원장 코드 → 활성 보통주(stocks) → companies.ticker 순으로 해석한다.
    """

    rows = await _fetch_all(
        conn,
        """
        WITH mention AS (
            SELECT rs.subject_name AS name, rs.subject_code AS code
            FROM relation_sources rs
            JOIN news n ON n.id = rs.news_id
            WHERE COALESCE(n.cluster_rep_news_id, n.id) = %(rep_news_id)s
        ),
        parties AS (
            SELECT name, max(code) AS code FROM mention GROUP BY name
        )
        SELECT c.id AS company_id, p.name,
               COALESCE(p.code, s.ticker, c.ticker) AS ticker, c.description
        FROM parties p
        LEFT JOIN companies c ON c.name = p.name
        LEFT JOIN LATERAL (SELECT ticker FROM stocks
                           WHERE company_id = c.id AND is_active AND NOT preferred_stock
                           ORDER BY id LIMIT 1) s ON true
        ORDER BY p.name
        """,
        {"rep_news_id": rep_news_id},
    )
    return [Anchor(**row) for row in rows]


# ── 공급망 1-hop (SUPPLIES_TO, Neo4j) ────────────────────────────────────────


async def fetch_news_parties(conn: AsyncConnection, rep_news_id: int) -> list[dict]:
    """이 뉴스(클러스터)가 서술한 관계들을 subject/object 역할 그대로 반환한다.

    subject_code 가 Neo4j 1-hop 탐색의 시작점(ticker)이고, 뉴스 당사자
    (subject·object)의 티커는 모두 후보에서 제외한다.
    """

    return await _fetch_all(
        conn,
        """
        SELECT DISTINCT rs.subject_name, rs.subject_code, rs.object_name, rs.object_code
        FROM relation_sources rs
        JOIN news n ON n.id = rs.news_id
        WHERE COALESCE(n.cluster_rep_news_id, n.id) = %(rep_news_id)s
        """,
        {"rep_news_id": rep_news_id},
    )


async def fetch_supply_neighbors(ticker: str, exclude_tickers: list[str]) -> list[dict]:
    """앵커(subject) 기업 노드를 ticker 로 특정하고 그 기업에 공급하는 이웃을 반환한다.

    유입 방향만 본다 — (n)-[:SUPPLIES_TO]->(anchor) 인 공급사 n 들이 초기
    후보군이다. 비상장(ticker 없는) 노드와 제외 티커(뉴스 당사자)는 거른다.
    선별은 이후 시장·시가총액(fetch_market_info) 기준으로 한다.
    """

    records = await neo4j_database.execute(
        """
MATCH (n:Company)-[r:SUPPLIES_TO]->(o:Company {ticker: $ticker})
WHERE n.ticker IS NOT NULL AND NOT n.ticker IN $exclude
RETURN n.ticker AS ticker, n.name AS name, n.company_id AS company_id,
       n.name AS subject_name, o.name AS object_name,
       coalesce(r.disclosure_count, 0) AS disclosure_count
ORDER BY disclosure_count DESC
""",
        {"ticker": ticker, "exclude": exclude_tickers},
    )
    return [dict(record) for record in records]


async def fetch_market_info(conn: AsyncConnection, tickers: list[str]) -> list[dict]:
    """활성 종목의 시장 구분(KOSPI/KOSDAQ 등)과 최신 시가총액을 반환한다.

    시가총액은 stock_valuations_daily 최신 거래일 행에서 가져오며, 밸류에이션이 없는
    종목은 market_cap 이 NULL 이다. stocks 에 없는 티커는 결과에서 빠진다.
    """

    return await _fetch_all(
        conn,
        """
        SELECT s.ticker, s.market, v.market_cap
        FROM stocks s
        LEFT JOIN LATERAL (SELECT market_cap FROM stock_valuations_daily
                           WHERE listing_id = s.id
                           ORDER BY trade_date DESC LIMIT 1) v ON true
        WHERE s.ticker = ANY(%(tickers)s) AND s.is_active
        """,
        {"tickers": tickers},
    )


async def fetch_edge_evidence(
    conn: AsyncConnection,
    subject_name: str,
    relation: str,
    object_name: str,
    limit: int = 3,
) -> list[dict]:
    # 원장은 출처 키만 든다 — 링크는 공시면 rcept_no 로 DART 뷰어 URL 을 만들고,
    # 뉴스면 news 테이블에서 참조한다.
    return await _fetch_all(
        conn,
        f"""
        SELECT rs.id, rs.source_type, rs.evidence, rs.item, rs.mentioned_at, rs.rcept_no,
               CASE rs.source_type
                   WHEN 'disclosure'
                       THEN 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' || rs.rcept_no
                   ELSE n.link
               END AS link
        FROM relation_sources rs
        LEFT JOIN news n ON n.id = rs.news_id
        WHERE rs.subject_name = %(s)s AND rs.relation = %(r)s AND rs.object_name = %(o)s
          AND {_AFFIRMED}
        ORDER BY rs.mentioned_at DESC
        LIMIT %(limit)s
        """,
        {"s": subject_name, "r": relation, "o": object_name, "limit": limit},
    )


# ── 재무 테이블 (table RAG) ──────────────────────────────────────────────────


async def fetch_financial_history(
    conn: AsyncConnection, company_id: int, limit: int = 4
) -> list[dict]:
    """연결(CFS) 연간 재무 이력을 최신 회계연도부터 반환한다.

    부채비율은 저장돼 있지 않아 total_liabilities/total_equity 로 계산한다.
    """

    return await _fetch_all(
        conn,
        """
        SELECT fiscal_yymm, revenue, operating_income, net_income, roe, eps,
               total_assets, total_liabilities, total_equity,
               CASE WHEN total_equity > 0
                    THEN round(total_liabilities::numeric / total_equity * 100, 1)
               END AS debt_ratio
        FROM company_financials
        WHERE company_id = %(company_id)s AND period_type = 'A' AND fs_div = 'CFS'
        ORDER BY fiscal_yymm DESC
        LIMIT %(limit)s
        """,
        {"company_id": company_id, "limit": limit},
    )


async def fetch_latest_valuation(conn: AsyncConnection, ticker: str) -> dict | None:
    """활성 종목의 최신 밸류에이션(PER 등)을 반환한다."""

    return await _fetch_one(
        conn,
        """
        SELECT v.trade_date, v.market_cap, v.per, v.pbr, v.eps, v.bps
        FROM stocks s
        JOIN stock_valuations_daily v ON v.listing_id = s.id
        WHERE s.ticker = %(ticker)s AND s.is_active
        ORDER BY v.trade_date DESC
        LIMIT 1
        """,
        {"ticker": ticker},
    )
