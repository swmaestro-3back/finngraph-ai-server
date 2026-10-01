"""beneficiary 데이터 계층 — PG·Neo4j 조회.

라벨·관계 타입은 core.graph_schema 의 enum 에서 가져온다. 상장 필터와
RootCompany 변환은 여기가 아니라 build_plan 소관이다 — 이 모듈은 행(dict)만
돌려준다.

Cypher 는 f-string 으로 조립한 뒤 LiteralString 으로 cast 한다 — 보간되는 값이
enum 상수뿐이라 실제로는 리터럴이지만 타입 검사기가 그걸 증명하지 못하기
때문이다. 사용자 입력은 예외 없이 $파라미터로만 나간다. 이 불변식이 깨지는
순간 cast 도 같이 걷어내야 한다.

극성 주의: fetch_relation_lines 는 전 극성을 반환한다(LLM 은 해지·부인 맥락도
봐야 한다). 반면 근거 조회(fetch_edge_evidence)는 affirmed 만 쓴다.
"""

from __future__ import annotations

from typing import Any, LiteralString, cast

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from beneficiary.models import RelationLine
from core import MARKETS, NodeLabel, RelationshipType, neo4j_database
from core.config import settings


async def _fetch_all(conn: AsyncConnection, query: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def _fetch_one(conn: AsyncConnection, query: str, params: Any = None) -> dict | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


# ── 뉴스 해석 ────────────────────────────────────────────────────────────────


async def resolve_news_with_link(conn: AsyncConnection, news_id: int) -> dict | None:
    """클러스터 대표로 정규화한 뉴스 컨텍스트 + 원문 링크 (없으면 None).

    link 는 트리거 뉴스 자체를 근거로 실을 때 쓴다.
    """

    return await _fetch_one(
        conn,
        """
        SELECT rep.id AS rep_news_id, rep.title, rep.summary, rep.published_at, rep.link
        FROM news n
        JOIN news rep ON rep.id = COALESCE(n.cluster_rep_news_id, n.id)
        WHERE n.id = %(news_id)s
        """,
        {"news_id": news_id},
    )


async def fetch_relation_lines(conn: AsyncConnection, rep_news_id: int) -> list[RelationLine]:
    """이 뉴스(클러스터)가 서술한 관계 라인 전체 — 전 극성."""

    rows = await _fetch_all(
        conn,
        """
        SELECT DISTINCT rs.subject_name, rs.subject_code, rs.relation,
               rs.object_name, rs.object_code, rs.item, rs.polarity,
               rs.subject_impact, rs.object_impact
        FROM relation_sources rs
        JOIN news n ON n.id = rs.news_id
        WHERE COALESCE(n.cluster_rep_news_id, n.id) = %(rep_news_id)s
        ORDER BY rs.subject_name, rs.object_name, rs.item
        """,
        {"rep_news_id": rep_news_id},
    )
    return [RelationLine(**row) for row in rows]


# ── Neo4j — 공급망·이웃 ──────────────────────────────────────────────────────


async def fetch_supply_neighbors_by_name(
    root_name: str, exclude_names: list[str], exclude_tickers: list[str]
) -> list[dict]:
    """루트 기업의 1-hop 공급관계에 있는 기업 — 활성 KOSPI/KOSDAQ 만.

    루트 기업은 name 으로 특정한다 — 그래프의 자연키가 name 이고 노드 ticker 는
    시드 지연으로 빌 수 있어 name 이 안전한 키다. 시장·상장 판정은 노드
    필드(market·is_listed)로 여기서 끝낸다 — ETL 이 ticker 와 같은 시점에
    적재하며, 상장 게이트는 is_listed 가 담당한다.
    아이템 배열·카운트는 filter LLM 의 판단 원료다.
    """

    query = cast(LiteralString, f"""
MATCH (n:{NodeLabel.COMPANY})-[r:{RelationshipType.SUPPLIES_TO}]->(o:{NodeLabel.COMPANY} {{name: $root_name}})
WHERE n.ticker IS NOT NULL
  AND n.market IN $markets
  AND n.is_listed = true
  AND NOT n.ticker IN $exclude_tickers
  AND NOT n.name   IN $exclude_names
RETURN n.ticker AS ticker, n.name AS name, n.company_id AS company_id,
       n.market AS market,
       coalesce(r.disclosure_count, 0)    AS disclosure_count,
       coalesce(r.news_mention_count, 0)  AS news_mention_count,
       coalesce(r.disclosure_items, [])   AS disclosure_items,
       coalesce(r.news_items, [])         AS news_items,
       r.last_mentioned_at                AS last_mentioned_at
""")
    records = await neo4j_database.execute(
        query,
        {
            "root_name": root_name,
            "markets": list(MARKETS),
            "exclude_tickers": exclude_tickers,
            "exclude_names": exclude_names
        },
    )
    return [dict(record) for record in records]


async def search_theme_reasons(
    query_vector: list[float],
    exclude_names: list[str],
    exclude_tickers: list[str],
    min_score: float,
    limit: int,
    over_fetch: int,
) -> list[dict]:
    """시나리오 질의와 의미가 맞는 테마 편입 사유를 가진 상장 기업 — 활성 KOSPI/KOSDAQ 만.

    벡터 인덱스는 top-k 를 먼저 뽑고 그 다음 WHERE 가 걸린다 — 시장·상장·제외
    필터가 뒤에서 깎으므로 over_fetch 로 과다 조회해야 limit 슬롯이 채워진다.
    (fetch_supply_neighbors_by_name 과 달리 필터를 앞단으로 밀 수 없다.)

    인덱스 이름은 enum 상수가 아니라 settings 값이다 — 모듈 불변식(보간은
    enum 상수만, 그 외 값은 전부 $parameter)에 따라 문자열로 보간하지 않고
    파라미터로 넘긴다.
    """

    query = cast(LiteralString, f"""
CALL db.index.vector.queryRelationships($index_name, $over_fetch, $query_vector)
YIELD relationship AS r, score
WHERE score >= $min_score
WITH r, score, startNode(r) AS c, endNode(r) AS t
WHERE c.ticker IS NOT NULL
  AND c.market IN $markets
  AND c.is_listed = true
  AND NOT c.ticker IN $exclude_tickers
  AND NOT c.name   IN $exclude_names
RETURN c.ticker AS ticker, c.name AS name, c.company_id AS company_id,
       c.market AS market, t.name AS theme_name, r.reason AS reason, score
ORDER BY score DESC
LIMIT $limit
""")
    records = await neo4j_database.execute(query, {
        "index_name": settings.neo4j_reason_vector_index,
        "over_fetch": over_fetch,
        "query_vector": query_vector,
        "min_score": min_score,
        "markets": list(MARKETS),
        "exclude_names": exclude_names,
        "exclude_tickers": exclude_tickers,
        "limit": limit,
    })
    return [dict(record) for record in records]


# ── PG — 당사자·시세·근거·재무 ──────────────────────────────────────────────

_AFFIRMED = "(polarity IS NULL OR polarity = 'affirmed')"


async def fetch_root_companies(conn: AsyncConnection, rep_news_id: int) -> list[dict]:
    """뉴스(클러스터) 관계의 subject 당사자 행 — 상장 국내 기업만.

    subject_code(티커)로 찾는다. 이름 조인은 쓰지 않는다 — companies.name 은
    유니크가 아니라 동명 비상장사가 한 이름에 열 몇 행씩 붙고, 당사자 하나가
    루트 기업 여러 개로 불어난다.

    티커가 사는 곳이 두 군데라 양쪽으로 해석한다: companies.ticker 와
    stocks.ticker(활성 보통주). 한쪽만 보면 놓치는 기업이 있다 — 원장 코드 중
    일부는 stocks 에 없고, companies.ticker 가 비어 stocks 에만 있는 적재분도
    있다. 두 경로가 같은 기업을 짚으면 UNION 이 접는다.
    """

    return await _fetch_all(
        conn,
        """
        WITH parties AS (
            SELECT DISTINCT rs.subject_code AS ticker
            FROM relation_sources rs
            JOIN news n ON n.id = rs.news_id
            WHERE COALESCE(n.cluster_rep_news_id, n.id) = %(rep_news_id)s
              AND rs.subject_code IS NOT NULL
        ),
        resolved AS (
            SELECT p.ticker, c.id AS company_id
            FROM parties p
            JOIN companies c ON c.ticker = p.ticker AND c.delisted_at IS NULL
            UNION
            SELECT p.ticker, s.company_id
            FROM parties p
            JOIN stocks s ON s.ticker = p.ticker
                         AND s.is_active AND NOT s.preferred_stock
        )
        SELECT DISTINCT c.id AS company_id, c.name, r.ticker, c.description
        FROM resolved r
        JOIN companies c ON c.id = r.company_id
        WHERE c.is_listed AND c.delisted_at IS NULL
        ORDER BY c.name
        """,
        {"rep_news_id": rep_news_id},
    )


async def fetch_edge_evidence(
    conn: AsyncConnection, subject_name: str, relation: str, object_name: str, limit: int = 3
) -> list[dict]:
    """간선 자연키의 affirmed 근거 — 최신순.

    denied/terminated 는 제외한다 — 끊긴 공급 관계를 살아있다고 말하는 사고
    방지. 링크는 공시면 rcept_no 로 DART 뷰어 URL, 뉴스면 news.link.
    """

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


async def fetch_financial_history(
    conn: AsyncConnection, company_id: int, limit: int = 5
) -> list[dict]:
    """연결(CFS) 연간 재무 이력 — 최신 회계연도부터, 부채비율 파생."""

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
    """활성 종목의 최신 밸류에이션(PER 등)."""

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
