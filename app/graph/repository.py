"""beneficiary 데이터 계층 — 신규 쿼리(PG·Neo4j)·v1 이관 쿼리·응답 캐시.

v1(삭제됨)의 읽기 쿼리 5개(fetch_root_companies, fetch_market_info,
fetch_edge_evidence, fetch_financial_history, fetch_latest_valuation)는 이
모듈로 이관했다 — fetch_root_companies 만 반환형이 dict 행으로 바뀌었고(상장 필터·
RootCompany 변환은 analyze_news 소관), 나머지는 v1 코드 그대로다.
resolve_news_with_link 는 v1 resolve_news 의 SELECT 에 link 를 더한 판이다.

극성 주의: fetch_relation_lines 는 전 극성을 반환한다(LLM 은 해지·부인 맥락도
봐야 한다). 반면 폴백 극성 투표·근거 조회(fetch_edge_evidence)는 affirmed 만
쓴다.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from graph.models import RelationLine
from core import neo4j_database

THEMES_PER_ROOT = 30  # 루트 기업당 테마 상한 — 멤버 수 오름차순(구체 테마 우선) 절단
RIVALS_PER_PROBE = 30  # probe당 경쟁사 후보 상한


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

    v1 resolve_news 의 beneficiary 판 — 악재 트랙의 트리거 뉴스 근거로 link 가
    필요해 SELECT 를 확장했다 (v1 은 수정하지 않는다).
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


# ── Neo4j — 테마·공급망·이웃 ─────────────────────────────────────────────────


async def fetch_root_company_themes(name: str) -> list[dict]:
    """상장 루트 기업의 소속 테마 — 멤버 수 오름차순 → 테마명 오름차순, 상한 30."""

    records = await neo4j_database.execute(
        f"""
MATCH (c:Company {{name: $name}})-[:BELONGS_TO]->(t:Theme)
OPTIONAL MATCH (t)<-[:BELONGS_TO]-(m:Company)
WITH t, count(m) AS member_count
ORDER BY member_count ASC, t.name ASC
LIMIT {THEMES_PER_ROOT}
RETURN t.name AS name, t.description AS description, member_count
""",
        {"name": name},
    )
    return [dict(record) for record in records]


async def fetch_supply_neighbors_by_name(
    root_name: str, exclude_names: list[str], exclude_tickers: list[str]
) -> list[dict]:
    """루트 기업(name 매칭)에 공급하는 유입 SUPPLIES_TO 1-hop 이웃 — 상장사만.

    v1 fetch_supply_neighbors 와 달리 name 으로 루트 기업를 특정한다 — 그래프의
    자연키가 name 이고 노드 ticker 는 시드 지연으로 빌 수 있어 name 이 안전한
    키다. 아이템 배열·카운트는 filter LLM 의 판단 원료다.
    """

    records = await neo4j_database.execute(
        """
MATCH (n:Company)-[r:SUPPLIES_TO]->(o:Company {name: $root_name})
WHERE n.ticker IS NOT NULL
  AND NOT n.ticker IN $exclude_tickers
  AND NOT n.name   IN $exclude_names
RETURN n.ticker AS ticker, n.name AS name, n.company_id AS company_id,
       n.name AS subject_name, o.name AS object_name,
       coalesce(r.disclosure_count, 0)    AS disclosure_count,
       coalesce(r.news_mention_count, 0)  AS news_mention_count,
       coalesce(r.disclosure_items, [])   AS disclosure_items,
       coalesce(r.news_items, [])         AS news_items,
       r.last_mentioned_at                AS last_mentioned_at
""",
        {"root_name": root_name, "exclude_tickers": exclude_tickers,
         "exclude_names": exclude_names},
    )
    return [dict(record) for record in records]


async def fetch_theme_rivals(
    subject_name: str, themes: list[str], exclude_names: list[str], exclude_tickers: list[str]
) -> list[dict]:
    """루트 기업와 probe 테마를 공유하는 상장 경쟁사 후보 + 유출 공급 아이템.

    겹침(shared_themes)은 probe 의 핵심 테마 안에서만 센다 — 전체 테마로 세면
    대기업은 무관한 대형주끼리 겹침이 쏠린다(스펙 §4.4). reasons 는 쿼리에서
    "[테마명] 편입 사유" 형태로 만들어 테마 귀속을 보존한다(스펙 §4.7 근거
    형식 — reason 이 NULL 인 간선은 문자열 연결이 NULL 이 되어 collect 에서
    자연 탈락).
    """

    records = await neo4j_database.execute(
        f"""
MATCH (a:Company {{name: $subject_name}})-[:BELONGS_TO]->(t:Theme)
WHERE t.name IN $themes
MATCH (t)<-[b:BELONGS_TO]-(c:Company)
WHERE c.ticker IS NOT NULL
  AND NOT c.name IN $exclude_names AND NOT c.ticker IN $exclude_tickers
WITH c, count(DISTINCT t) AS shared_themes,
     collect(DISTINCT t.name) AS via_themes,
     collect(DISTINCT ('[' + t.name + '] ' + b.reason))[..3] AS reasons
ORDER BY shared_themes DESC, c.ticker
LIMIT {RIVALS_PER_PROBE}
OPTIONAL MATCH (c)-[s:SUPPLIES_TO]->()
WITH c, shared_themes, via_themes, reasons,
     collect(s.disclosure_items) + collect(s.news_items) AS item_arrays
RETURN c.ticker AS ticker, c.name AS name, c.company_id AS company_id,
       shared_themes, via_themes, reasons, item_arrays
""",
        {"subject_name": subject_name, "themes": themes,
         "exclude_names": exclude_names, "exclude_tickers": exclude_tickers},
    )
    return [dict(record) for record in records]


async def fetch_neighbor_names(names: list[str]) -> set[str]:
    """대상 기업들의 SUPPLIES_TO·INVESTS_IN·ACQUIRES 양방향 1-hop 이웃 name 합집합.

    악재 트랙 제외 집합 — 밸류체인(공급망)뿐 아니라 지분 관계(자회사·계열)도
    배제해 루트 기업의 자회사가 "반사이익 경쟁사"로 추천되는 것을 차단한다.
    """

    if not names:
        return set()
    records = await neo4j_database.execute(
        """
MATCH (a:Company) WHERE a.name IN $names
MATCH (a)-[:SUPPLIES_TO|INVESTS_IN|ACQUIRES]-(n:Company)
RETURN DISTINCT n.name AS name
""",
        {"names": names},
    )
    return {record["name"] for record in records}


# ── 응답 캐시 (news_beneficiaries) ───────────────────────────────────────────


async def fetch_cached_payload(
    conn: AsyncConnection, rep_news_id: int, prompt_version: str
) -> dict | None:
    row = await _fetch_one(
        conn,
        """
        SELECT payload FROM news_beneficiaries
        WHERE rep_news_id = %(rep_news_id)s AND prompt_version = %(prompt_version)s
        """,
        {"rep_news_id": rep_news_id, "prompt_version": prompt_version},
    )
    return row["payload"] if row else None


async def store_payload(
    conn: AsyncConnection, rep_news_id: int, prompt_version: str, payload: dict
) -> None:
    """캐시 저장 — 경쟁 삽입은 먼저 쓴 쪽이 이긴다 (ON CONFLICT DO NOTHING)."""

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO news_beneficiaries (rep_news_id, prompt_version, payload)
            VALUES (%(rep_news_id)s, %(prompt_version)s, %(payload)s)
            ON CONFLICT (rep_news_id, prompt_version) DO NOTHING
            """,
            {"rep_news_id": rep_news_id, "prompt_version": prompt_version,
             "payload": Jsonb(payload)},
        )
    await conn.commit()


# ── v1 이관 쿼리 (원본: 삭제된 insights/repository.py — 코드 그대로) ─────────

_AFFIRMED = "(polarity IS NULL OR polarity = 'affirmed')"


async def fetch_root_companies(conn: AsyncConnection, rep_news_id: int) -> list[dict]:
    """뉴스(클러스터) 관계의 subject 당사자 행 (v1 이관 — dict 반환으로 변경).

    상장 필터·RootCompany 변환은 analyze_news 소관(§4.1). 극성은 거르지 않는다 —
    해지·부인 뉴스라도 당사자는 그 기업들이다. 티커는 원장 code → 활성
    보통주(stocks) → companies.ticker 순으로 해석한다.
    """

    return await _fetch_all(
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


async def fetch_market_info(conn: AsyncConnection, tickers: list[str]) -> list[dict]:
    """활성 종목의 시장 구분(KOSPI/KOSDAQ 등)·최신 시가총액 (v1 이관)."""

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
    conn: AsyncConnection, subject_name: str, relation: str, object_name: str, limit: int = 3
) -> list[dict]:
    """간선 자연키의 affirmed 근거 — 최신순 (v1 이관).

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
    conn: AsyncConnection, company_id: int, limit: int = 4
) -> list[dict]:
    """연결(CFS) 연간 재무 이력 — 최신 회계연도부터, 부채비율 파생 (v1 이관)."""

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
    """활성 종목의 최신 밸류에이션(PER 등) (v1 이관)."""

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
