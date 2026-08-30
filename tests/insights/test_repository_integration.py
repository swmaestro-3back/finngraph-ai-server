"""인사이트 리포지토리(데이터 계층) 통합 테스트.

로컬 ETL DB(Postgres) + Neo4j 필요: finngraph-etl 에서 docker compose up -d db
+ 마이그레이션 적용 상태. 공급망 1-hop 은 Neo4j 소관이라 graph_seed 픽스처가
Company 노드·SUPPLIES_TO 간선(disclosure_count 속성)을 시드한다.
시드는 uuid 로 유일화하고 픽스처가 정리한다.

시나리오: 뉴스가 "상대기업 SUPPLIES_TO 앵커기업"(①)과 "앵커기업 SUPPLIES_TO
고객기업"(②)을 서술한다 → 앵커는 subject 당사자들(상대기업·앵커기업)이고,
각 subject ticker 로 유입 SUPPLIES_TO 탐색 → 뉴스 당사자는 후보에서 제외 →
남는 후보는 앵커기업에 공급하는 동료기업뿐 — 앵커기업이 공급하는 제3기업
(유출 방향)과 비상장 이웃은 탈락.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from core import neo4j_database
from core.config import settings
from insights import repository

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def conn():
    connection = await AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def seed(conn):
    """기업·뉴스·원장 근거·재무·밸류에이션을 Postgres 에 시드한다."""

    uid = uuid.uuid4().hex[:8]
    anchor_name = f"앵커기업-{uid}"  # 관계 ①의 object 이자 ②의 subject (1-hop 탐색 시작점)
    partner_name = f"상대기업-{uid}"  # 관계 ①의 subject (뉴스 당사자 → 후보 제외 대상)
    fellow_name = f"동료기업-{uid}"  # 앵커기업의 공급사 = 유일한 후보 (공시 2건)
    third_name = f"제3기업-{uid}"  # 앵커기업이 공급하는 곳 (유출 방향 → 후보 아님)
    customer_name = f"고객기업-{uid}"  # 비상장 당사자 (companies 행 없음)

    async with conn.cursor() as cur:
        # 기업·종목
        ids: dict = {
            "uid": uid,
            "anchor_name": anchor_name,
            "partner_name": partner_name,
            "fellow_name": fellow_name,
            "third_name": third_name,
            "customer_name": customer_name,
        }
        for key, name, ticker, market in [
            ("anchor", anchor_name, f"A{uid[:5].upper()}", "KOSPI"),
            ("partner", partner_name, f"B{uid[:5].upper()}", "KOSPI"),
            ("fellow", fellow_name, f"C{uid[:5].upper()}", "KOSPI"),
            ("third", third_name, f"D{uid[:5].upper()}", "KOSDAQ"),
        ]:
            await cur.execute(
                "INSERT INTO companies (name, is_listed, country, description) "
                "VALUES (%s, true, 'KR', %s) RETURNING id",
                (name, f"{name} 사업 설명"),
            )
            ids[f"{key}_company_id"] = (await cur.fetchone())["id"]
            await cur.execute(
                "INSERT INTO stocks (name, ticker, market, standard_code, company_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (name, ticker, market, f"KR{uid}{key[:2].upper()}", ids[f"{key}_company_id"]),
            )
            ids[f"{key}_stock_id"] = (await cur.fetchone())["id"]
            ids[f"{key}_ticker"] = ticker

        # 뉴스 (대표) + 클러스터 소속 뉴스 + 트리플 없는 뉴스(앵커 없음 시나리오)
        await cur.execute(
            "INSERT INTO news (title, summary, published_at) "
            "VALUES (%s, '요약', now()) RETURNING id",
            (f"대표뉴스-{uid}",),
        )
        ids["rep_news_id"] = (await cur.fetchone())["id"]
        await cur.execute(
            "INSERT INTO news (title, cluster_rep_news_id) VALUES (%s, %s) RETURNING id",
            (f"중복기사-{uid}", ids["rep_news_id"]),
        )
        ids["dup_news_id"] = (await cur.fetchone())["id"]
        await cur.execute(
            "INSERT INTO news (title) VALUES (%s) RETURNING id",
            (f"무관뉴스-{uid}",),
        )
        ids["bare_news_id"] = (await cur.fetchone())["id"]

        ids["evidence_news_ids"] = []

        async def insert_news_edge(polarity, subject, subject_code, obj, obj_code, news_id=None):
            if news_id is None:
                await cur.execute(
                    "INSERT INTO news (title) VALUES (%s) RETURNING id",
                    (f"근거뉴스-{polarity}-{uid}",),
                )
                news_id = (await cur.fetchone())["id"]
                ids["evidence_news_ids"].append(news_id)
            await cur.execute(
                """
                INSERT INTO relation_sources
                    (source_type, news_id, subject_name, subject_code, relation,
                     object_name, object_code, evidence, mentioned_at, polarity)
                VALUES ('news', %s, %s, %s, 'SUPPLIES_TO', %s, %s, %s, now(), %s)
                """,
                (news_id, subject, subject_code, obj, obj_code,
                 f"{polarity} 근거 문장", polarity),
            )

        # 대표뉴스가 서술한 관계 = 앵커 해석·object ticker 의 원천:
        # ① 상대기업(subject) SUPPLIES_TO 앵커기업(object, 상장)
        # ② 앵커기업(subject) SUPPLIES_TO 고객기업(object, 비상장 → 탐색 불가)
        await insert_news_edge("affirmed", partner_name, ids["partner_ticker"],
                               anchor_name, ids["anchor_ticker"], news_id=ids["rep_news_id"])
        await insert_news_edge("affirmed", anchor_name, ids["anchor_ticker"],
                               customer_name, None, news_id=ids["rep_news_id"])

        # 후보 간선의 근거 원장: 동료기업→앵커 뉴스 affirmed 2 + denied 1
        await insert_news_edge("affirmed", fellow_name, ids["fellow_ticker"],
                               anchor_name, ids["anchor_ticker"])
        await insert_news_edge("affirmed", fellow_name, ids["fellow_ticker"],
                               anchor_name, ids["anchor_ticker"])
        await insert_news_edge("denied", fellow_name, ids["fellow_ticker"],
                               anchor_name, ids["anchor_ticker"])

        # 공시 근거 — rcept_no 는 disclosures FK 라 원본 공시 행을 먼저 시드한다.
        ids["rcept_nos"] = []
        for i, (subject, subject_code, obj, obj_code) in enumerate([
            (fellow_name, ids["fellow_ticker"], anchor_name, ids["anchor_ticker"]),
            (fellow_name, ids["fellow_ticker"], anchor_name, ids["anchor_ticker"]),
            (anchor_name, ids["anchor_ticker"], third_name, ids["third_ticker"]),
        ]):
            rcept_no = f"2026{uid[:6]}{i:02d}"
            ids["rcept_nos"].append(rcept_no)
            await cur.execute(
                """
                INSERT INTO disclosures
                    (rcept_no, corp_code, report_nm, is_correction, rcept_dt, link,
                     fields, meta)
                VALUES (%s, %s, '단일판매ㆍ공급계약체결', false, now(),
                        'https://dart.fss.or.kr', '{}', '{}')
                """,
                (rcept_no, f"corp-{uid}"),
            )
            await cur.execute(
                """
                INSERT INTO relation_sources
                    (source_type, subject_name, subject_code, relation,
                     object_name, object_code, evidence, item, mentioned_at, rcept_no, polarity)
                VALUES ('disclosure', %s, %s, 'SUPPLIES_TO', %s, %s,
                        '단일판매공급계약 체결', 'HBM', now(), %s, 'affirmed')
                """,
                (subject, subject_code, obj, obj_code, rcept_no),
            )

        # 재무 (후보 1순위인 동료기업 — 연간 CFS 2개년 + 분기 1건은 걸러져야 한다)
        for fiscal_yymm, period_type, revenue, op, ni, roe, eps, assets, liab, equity in [
            ("202512", "A", 2000, 300, 250, 12.5, 500, 5000, 2000, 3000),
            ("202412", "A", 1500, 200, 150, 10.0, 300, 4000, 2000, 2000),
            ("202603", "Q", 600, 90, 70, None, 150, 5100, 2050, 3050),
        ]:
            await cur.execute(
                """
                INSERT INTO company_financials
                    (company_id, fiscal_yymm, period_type, fs_div, revenue,
                     operating_income, net_income, roe, eps, total_assets,
                     total_liabilities, total_equity)
                VALUES (%s, %s, %s, 'CFS', %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (ids["fellow_company_id"], fiscal_yymm, period_type,
                 revenue, op, ni, roe, eps, assets, liab, equity),
            )

        # 밸류에이션 (이틀치 — 최신 행이 이겨야 한다)
        for trade_date, market_cap, per in [
            ("2026-08-25", 900000, 9.0),
            ("2026-08-26", 1000000, 8.4),
        ]:
            await cur.execute(
                """
                INSERT INTO stock_valuations_daily (listing_id, trade_date, market_cap, per, pbr)
                VALUES (%s, %s, %s, %s, 1.2)
                """,
                (ids["fellow_stock_id"], trade_date, market_cap, per),
            )

    await conn.commit()
    yield ids

    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM relation_sources WHERE subject_name = ANY(%s)",
            ([anchor_name, partner_name, fellow_name],),
        )
        await cur.execute(
            "DELETE FROM news WHERE id = ANY(%s)",
            (
                [
                    ids["dup_news_id"],
                    ids["rep_news_id"],
                    ids["bare_news_id"],
                    *ids["evidence_news_ids"],
                ],
            ),
        )
        await cur.execute(
            "DELETE FROM disclosures WHERE rcept_no = ANY(%s)", (ids["rcept_nos"],)
        )
        await cur.execute(
            "DELETE FROM company_financials WHERE company_id = %s",
            (ids["fellow_company_id"],),
        )
        await cur.execute(
            "DELETE FROM stock_valuations_daily WHERE listing_id = %s",
            (ids["fellow_stock_id"],),
        )
        for key in ["anchor", "partner", "fellow", "third"]:
            await cur.execute("DELETE FROM stocks WHERE id = %s", (ids[f"{key}_stock_id"],))
            await cur.execute("DELETE FROM companies WHERE id = %s", (ids[f"{key}_company_id"],))
    await conn.commit()


@pytest_asyncio.fixture
async def graph_seed(seed):
    """Neo4j 에 Company 노드·SUPPLIES_TO 간선(disclosure_count)을 시드한다.

    - 상대기업 → 앵커 (공시 9): 뉴스 당사자라 후보에서 제외돼야 한다
    - 동료기업 → 앵커 (공시 2): 유일한 유입 공급사 = 후보
    - 앵커 → 제3기업 (공시 1): 유출 방향 → 후보 아님 (방향성 확인)
    - 앵커 → 비상장기업 (공시 7): ticker 없음·유출 방향 → 탈락
    """

    unlisted_name = f"비상장기업-{seed['uid']}"
    names = [
        seed["anchor_name"], seed["partner_name"], seed["fellow_name"],
        seed["third_name"], unlisted_name,
    ]

    neo4j_database.init_driver()
    await neo4j_database.execute(
        """
UNWIND $companies AS row
MERGE (c:Company {name: row.name})
SET c.ticker = row.ticker, c.company_id = row.company_id
""",
        {
            "companies": [
                {"name": seed["anchor_name"], "ticker": seed["anchor_ticker"],
                 "company_id": seed["anchor_company_id"]},
                {"name": seed["partner_name"], "ticker": seed["partner_ticker"],
                 "company_id": seed["partner_company_id"]},
                {"name": seed["fellow_name"], "ticker": seed["fellow_ticker"],
                 "company_id": seed["fellow_company_id"]},
                {"name": seed["third_name"], "ticker": seed["third_ticker"],
                 "company_id": seed["third_company_id"]},
                {"name": unlisted_name, "ticker": None, "company_id": None},
            ]
        },
    )
    await neo4j_database.execute(
        """
UNWIND $edges AS row
MATCH (s:Company {name: row.subject}), (o:Company {name: row.object})
MERGE (s)-[r:SUPPLIES_TO]->(o)
SET r.disclosure_count = row.disclosure_count
""",
        {
            "edges": [
                {"subject": seed["partner_name"], "object": seed["anchor_name"],
                 "disclosure_count": 9},
                {"subject": seed["fellow_name"], "object": seed["anchor_name"],
                 "disclosure_count": 2},
                {"subject": seed["anchor_name"], "object": seed["third_name"],
                 "disclosure_count": 1},
                {"subject": seed["anchor_name"], "object": unlisted_name,
                 "disclosure_count": 7},
            ]
        },
    )

    yield {**seed, "unlisted_name": unlisted_name}

    await neo4j_database.execute(
        "MATCH (c:Company) WHERE c.name IN $names DETACH DELETE c",
        {"names": names},
    )
    await neo4j_database.close()


async def test_resolve_news_normalizes_to_cluster_rep(conn, seed):
    resolved = await repository.resolve_news(conn, seed["dup_news_id"])

    assert resolved["rep_news_id"] == seed["rep_news_id"]
    assert resolved["title"] == f"대표뉴스-{seed['uid']}"

    assert await repository.resolve_news(conn, -1) is None


async def test_fetch_anchors_returns_subject_parties_only(conn, seed):
    """앵커 = 이 뉴스(클러스터)가 서술한 관계의 subject 당사자들 — object 는 제외."""
    anchors = await repository.fetch_anchors(conn, seed["rep_news_id"])

    by_name = {anchor.name: anchor for anchor in anchors}
    # 관계 ①의 subject 상대기업 + 관계 ②의 subject 앵커기업
    assert set(by_name) == {seed["partner_name"], seed["anchor_name"]}
    assert seed["customer_name"] not in by_name  # object 전용 당사자는 앵커가 아니다
    assert by_name[seed["anchor_name"]].ticker == seed["anchor_ticker"]
    assert by_name[seed["partner_name"]].ticker == seed["partner_ticker"]

    # 트리플이 없는 뉴스는 앵커가 없다.
    assert await repository.fetch_anchors(conn, seed["bare_news_id"]) == []


async def test_fetch_news_parties_keeps_subject_object_roles(conn, seed):
    parties = await repository.fetch_news_parties(conn, seed["rep_news_id"])

    by_pair = {(p["subject_name"], p["object_name"]): p for p in parties}
    assert set(by_pair) == {
        (seed["partner_name"], seed["anchor_name"]),
        (seed["anchor_name"], seed["customer_name"]),
    }
    assert by_pair[(seed["partner_name"], seed["anchor_name"])]["object_code"] == seed["anchor_ticker"]
    assert by_pair[(seed["anchor_name"], seed["customer_name"])]["object_code"] is None


async def test_fetch_supply_neighbors_returns_inbound_suppliers_only(graph_seed):
    neighbors = await repository.fetch_supply_neighbors(
        graph_seed["anchor_ticker"],
        exclude_tickers=[graph_seed["partner_ticker"], graph_seed["anchor_ticker"]],
    )

    # 유입 방향만: 앵커에 공급하는 동료기업만 남는다. subject(상대기업)·비상장
    # 이웃은 빠지고, 앵커가 공급하는 제3기업(유출 방향)도 후보가 아니다.
    assert [(n["name"], n["disclosure_count"]) for n in neighbors] == [
        (graph_seed["fellow_name"], 2),
    ]
    fellow = neighbors[0]
    assert (fellow["subject_name"], fellow["object_name"]) == (
        graph_seed["fellow_name"], graph_seed["anchor_name"]
    )
    assert fellow["company_id"] == graph_seed["fellow_company_id"]


async def test_fetch_market_info_returns_market_and_latest_cap(conn, seed):
    rows = await repository.fetch_market_info(
        conn, [seed["fellow_ticker"], seed["third_ticker"], "NOPE"]
    )

    by_ticker = {row["ticker"]: row for row in rows}
    assert set(by_ticker) == {seed["fellow_ticker"], seed["third_ticker"]}  # 미상장 티커 제외
    assert by_ticker[seed["fellow_ticker"]]["market"] == "KOSPI"
    assert int(by_ticker[seed["fellow_ticker"]]["market_cap"]) == 1000000  # 최신 거래일 행
    assert by_ticker[seed["third_ticker"]]["market"] == "KOSDAQ"
    assert by_ticker[seed["third_ticker"]]["market_cap"] is None  # 밸류에이션 없음


async def test_fetch_edge_evidence_returns_affirmed_only(conn, seed):
    rows = await repository.fetch_edge_evidence(
        conn, seed["fellow_name"], "SUPPLIES_TO", seed["anchor_name"], limit=10
    )

    # 뉴스 affirmed 2 + 공시 affirmed 2 — denied 는 제외
    assert len(rows) == 4
    disclosure_rows = [row for row in rows if row["source_type"] == "disclosure"]
    assert all("dart.fss.or.kr" in row["link"] for row in disclosure_rows)


async def test_fetch_financial_history_returns_annual_cfs_desc(conn, seed):
    rows = await repository.fetch_financial_history(conn, seed["fellow_company_id"])

    assert [row["fiscal_yymm"] for row in rows] == ["202512", "202412"]  # 분기 행 제외
    latest = rows[0]
    assert latest["revenue"] == 2000
    assert float(latest["debt_ratio"]) == pytest.approx(66.7, abs=0.1)  # 2000/3000*100


async def test_fetch_latest_valuation_returns_most_recent(conn, seed):
    valuation = await repository.fetch_latest_valuation(conn, seed["fellow_ticker"])

    assert str(valuation["trade_date"]) == "2026-08-26"
    assert float(valuation["per"]) == pytest.approx(8.4)

    assert await repository.fetch_latest_valuation(conn, "NOPE") is None
