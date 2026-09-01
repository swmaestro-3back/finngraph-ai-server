"""beneficiary 데이터 계층 통합 테스트 — 로컬 ETL DB(0001 적용) + Neo4j 필요.

시드 시나리오(uid 유일화, 픽스처가 정리):
  PG  — 뉴스: 대표뉴스(link 보유) + 클러스터 중복기사 + 근거뉴스(클러스터 외).
        관계 원장: ① 대표뉴스에 루트기업(subject) SUPPLIES_TO 상대기업(object)
        affirmed, item 'HBM', subject_impact negative ② 중복기사에 같은 삼중항
        denied 1행 — 전 극성 반환 확인용. uq_relsrc_news(news_id+삼중항) 제약상
        같은 뉴스에 두 극성을 달 수 없어 클러스터의 다른 뉴스에 단다.
        ③ 근거뉴스에 공급사기업→루트기업 affirmed — 호재 e2e 에서
        finance_collector 의 affirmed 근거 조회가 0건이 되지 않게 하는 원장 행.
  Neo4j — Company: 루트기업(A), 상대기업(B), 공급사기업(C, KOSDAQ), 경쟁사기업(D),
        자회사기업(E), 비상장공급(ticker·market 없음), 상폐공급(is_active false).
        market·is_active 는 노드 필드로 적재된다(ETL 이 ticker 와 같은 시점에
        적재) — 시장·상장 필터는 Cypher 가 수행한다.
        SUPPLIES_TO: 공급사기업→루트기업(아이템·카운트 보유), 비상장공급→루트기업,
        상폐공급→루트기업(is_active 게이트 확인용),
        상대기업→루트기업(뉴스 당사자 제외 확인용), 경쟁사기업→상대기업(경쟁사의
        유출 아이템 원천). INVESTS_IN: 루트기업→자회사기업(이웃 제외 확인용).
        Theme: 테마1(멤버 3: 루트 기업·경쟁사·자회사), 테마2(멤버 2: 루트 기업·경쟁사) —
        멤버 수 오름차순 정렬 확인용. BELONGS_TO 에 reason.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from beneficiary import repository
from core import neo4j_client
from core.config import settings

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def conn():
    connection = await AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def seed(conn):
    uid = uuid.uuid4().hex[:8]
    names = {
        "root": f"루트기업-{uid}",
        "partner": f"상대기업-{uid}",
        "supplier": f"공급사기업-{uid}",
        "rival": f"경쟁사기업-{uid}",
        "subsid": f"자회사기업-{uid}",
    }
    ids: dict = {"uid": uid, **{f"{k}_name": v for k, v in names.items()}}

    async with conn.cursor() as cur:
        for i, (key, market) in enumerate(
            [("root", "KOSPI"), ("partner", "KOSPI"), ("supplier", "KOSDAQ"),
             ("rival", "KOSPI"), ("subsid", "KOSDAQ")]
        ):
            await cur.execute(
                "INSERT INTO companies (name, is_listed, country) VALUES (%s, true, 'KR') RETURNING id",
                (names[key],),
            )
            ids[f"{key}_company_id"] = (await cur.fetchone())["id"]
            ticker = f"{chr(65 + i)}{uid[:5].upper()}"
            await cur.execute(
                "INSERT INTO stocks (name, ticker, market, standard_code, company_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (names[key], ticker, market, f"KR{uid}{i:02d}", ids[f"{key}_company_id"]),
            )
            ids[f"{key}_stock_id"] = (await cur.fetchone())["id"]
            ids[f"{key}_ticker"] = ticker

        await cur.execute(
            "INSERT INTO news (title, summary, published_at, link) "
            "VALUES (%s, '요약', now(), %s) RETURNING id",
            (f"대표뉴스-{uid}", f"https://news.example/{uid}"),
        )
        ids["rep_news_id"] = (await cur.fetchone())["id"]
        await cur.execute(
            "INSERT INTO news (title, cluster_rep_news_id) VALUES (%s, %s) RETURNING id",
            (f"중복기사-{uid}", ids["rep_news_id"]),
        )
        ids["dup_news_id"] = (await cur.fetchone())["id"]

        # uq_relsrc_news(news_id+삼중항) 제약 때문에 denied 행은 클러스터의 다른
        # 뉴스(중복기사)에 단다 — fetch_relation_lines 는 클러스터 기준 조회라
        # 두 극성 행을 모두 반환한다.
        for news_id, polarity, impact in [
            (ids["rep_news_id"], "affirmed", "negative"),
            (ids["dup_news_id"], "denied", "neutral"),
        ]:
            await cur.execute(
                """
                INSERT INTO relation_sources
                    (source_type, news_id, subject_name, subject_code, relation,
                     object_name, object_code, item, evidence, mentioned_at,
                     polarity, subject_impact, object_impact)
                VALUES ('news', %s, %s, %s, 'SUPPLIES_TO', %s, %s, 'HBM',
                        '근거 문장', now(), %s, %s, 'neutral')
                """,
                (news_id, names["root"], ids["root_ticker"],
                 names["partner"], ids["partner_ticker"], polarity, impact),
            )

        # 공급 후보 간선(공급사기업→루트기업)의 근거 원장 — finance_collector 의 affirmed
        # 근거 0건 제거 규칙(§4.7)이 호재 e2e 에서 '통과' 방향으로도 검증되게
        # 하는 행. 클러스터 밖의 별도 근거뉴스에 달아 대표뉴스의 당사자 집합
        # (fetch_root_companies·fetch_relation_lines)을 오염시키지 않는다.
        await cur.execute(
            "INSERT INTO news (title) VALUES (%s) RETURNING id", (f"근거뉴스-{uid}",)
        )
        ids["evidence_news_id"] = (await cur.fetchone())["id"]
        await cur.execute(
            """
            INSERT INTO relation_sources
                (source_type, news_id, subject_name, subject_code, relation,
                 object_name, object_code, item, evidence, mentioned_at,
                 polarity, subject_impact, object_impact)
            VALUES ('news', %s, %s, %s, 'SUPPLIES_TO', %s, %s, 'HBM',
                    '공급 계약 근거 문장', now(), 'affirmed', 'positive', 'neutral')
            """,
            (ids["evidence_news_id"], names["supplier"], ids["supplier_ticker"],
             names["root"], ids["root_ticker"]),
        )
    await conn.commit()

    theme1, theme2 = f"테마1-{uid}", f"테마2-{uid}"
    ids["theme1"], ids["theme2"] = theme1, theme2
    await neo4j_client.connect()
    await neo4j_client.execute(
        """
UNWIND $rows AS row
MERGE (c:Company {name: row.name})
SET c.ticker = row.ticker, c.company_id = row.cid,
    c.market = row.market, c.is_active = row.active
""",
        {"rows": [
            {"name": names["root"], "ticker": ids["root_ticker"], "cid": ids["root_company_id"],
             "market": "KOSPI", "active": True},
            {"name": names["partner"], "ticker": ids["partner_ticker"], "cid": ids["partner_company_id"],
             "market": "KOSPI", "active": True},
            {"name": names["supplier"], "ticker": ids["supplier_ticker"], "cid": ids["supplier_company_id"],
             "market": "KOSDAQ", "active": True},
            {"name": names["rival"], "ticker": ids["rival_ticker"], "cid": ids["rival_company_id"],
             "market": "KOSPI", "active": True},
            {"name": names["subsid"], "ticker": ids["subsid_ticker"], "cid": ids["subsid_company_id"],
             "market": "KOSDAQ", "active": True},
            {"name": f"비상장공급-{uid}", "ticker": None, "cid": None,
             "market": None, "active": None},
            {"name": f"상폐공급-{uid}", "ticker": f"Z{uid[:5].upper()}", "cid": None,
             "market": "KOSDAQ", "active": False},
        ]},
    )
    await neo4j_client.execute(
        """
UNWIND $rows AS row
MATCH (s:Company {name: row.s}), (o:Company {name: row.o})
MERGE (s)-[r:SUPPLIES_TO]->(o)
SET r.disclosure_count = row.dc, r.news_mention_count = row.nc,
    r.disclosure_items = row.di, r.news_items = row.ni
""",
        {"rows": [
            {"s": names["supplier"], "o": names["root"], "dc": 2, "nc": 1,
             "di": ["HBM"], "ni": ["TC본더"]},
            {"s": f"비상장공급-{uid}", "o": names["root"], "dc": 1, "nc": 0, "di": [], "ni": []},
            {"s": f"상폐공급-{uid}", "o": names["root"], "dc": 3, "nc": 3, "di": ["HBM"], "ni": []},
            {"s": names["partner"], "o": names["root"], "dc": 9, "nc": 9, "di": ["HBM"], "ni": []},
            {"s": names["rival"], "o": names["partner"], "dc": 1, "nc": 2,
             "di": ["HBM2"], "ni": ["DDR5"]},
        ]},
    )
    await neo4j_client.execute(
        """
MATCH (a:Company {name: $a}), (b:Company {name: $b}) MERGE (a)-[:INVESTS_IN]->(b)
""",
        {"a": names["root"], "b": names["subsid"]},
    )
    await neo4j_client.execute(
        """
UNWIND $rows AS row
MERGE (t:Theme {name: row.theme}) SET t.description = row.desc
WITH t, row
UNWIND row.members AS member
MATCH (c:Company {name: member.name})
MERGE (c)-[b:BELONGS_TO]->(t) SET b.reason = member.reason
""",
        {"rows": [
            {"theme": theme1, "desc": "테마1 설명", "members": [
                {"name": names["root"], "reason": "주력 생산"},
                {"name": names["rival"], "reason": "대체 생산 경쟁"},
                {"name": names["subsid"], "reason": "자회사 편입"},
            ]},
            {"theme": theme2, "desc": "테마2 설명", "members": [
                {"name": names["root"], "reason": "주력"},
                {"name": names["rival"], "reason": "경쟁"},
            ]},
        ]},
    )

    yield ids

    await neo4j_client.execute(
        "MATCH (c:Company) WHERE c.name IN $names DETACH DELETE c",
        {"names": [*names.values(), f"비상장공급-{uid}", f"상폐공급-{uid}"]},
    )
    await neo4j_client.execute(
        "MATCH (t:Theme) WHERE t.name IN $names DETACH DELETE t",
        {"names": [theme1, theme2]},
    )
    await neo4j_client.close()
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM relation_sources WHERE subject_name = ANY(%s)",
                          ([names["root"], names["supplier"]],))
        await cur.execute("DELETE FROM news WHERE id = ANY(%s)",
                          ([ids["rep_news_id"], ids["dup_news_id"], ids["evidence_news_id"]],))
        for key in ["root", "partner", "supplier", "rival", "subsid"]:
            await cur.execute("DELETE FROM stocks WHERE id = %s", (ids[f"{key}_stock_id"],))
            await cur.execute("DELETE FROM companies WHERE id = %s", (ids[f"{key}_company_id"],))
    await conn.commit()


async def test_resolve_news_with_link(conn, seed):
    resolved = await repository.resolve_news_with_link(conn, seed["dup_news_id"])
    assert resolved["rep_news_id"] == seed["rep_news_id"]
    assert resolved["link"] == f"https://news.example/{seed['uid']}"
    assert await repository.resolve_news_with_link(conn, -1) is None


async def test_fetch_relation_lines_returns_all_polarities(conn, seed):
    lines = await repository.fetch_relation_lines(conn, seed["rep_news_id"])
    assert {(l.polarity, l.subject_impact) for l in lines} == {
        ("affirmed", "negative"), ("denied", "neutral"),
    }
    line = lines[0]
    assert line.subject_name == seed["root_name"] and line.item == "HBM"
    assert line.subject_code == seed["root_ticker"] and line.object_code == seed["partner_ticker"]


async def test_fetch_supply_neighbors_by_name(seed):
    rows = await repository.fetch_supply_neighbors_by_name(
        seed["root_name"],
        exclude_names=[seed["root_name"], seed["partner_name"]],
        exclude_tickers=[seed["root_ticker"], seed["partner_ticker"]],
    )
    # 비상장(ticker·market 없음)·상폐(is_active false)·뉴스 당사자(상대기업)
    # 제외 → 공급사기업만. 시장·상장 판정은 Cypher 의 노드 필드 필터 소관.
    assert [(r["name"], r["disclosure_count"], r["news_mention_count"]) for r in rows] == [
        (seed["supplier_name"], 2, 1)
    ]
    assert rows[0]["market"] == "KOSDAQ"  # 노드 필드에서 온 시장 구분
    assert rows[0]["disclosure_items"] == ["HBM"] and rows[0]["news_items"] == ["TC본더"]
    assert rows[0]["object_name"] == seed["root_name"]


async def test_pg_party_evidence_and_valuation_queries(conn, seed):
    root_companies = await repository.fetch_root_companies(conn, seed["rep_news_id"])
    names = {a["name"] for a in root_companies}
    assert seed["root_name"] in names          # subject 당사자
    assert seed["supplier_name"] not in names    # 근거뉴스는 클러스터 밖 — 루트 기업 아님
    evidence = await repository.fetch_edge_evidence(
        conn, seed["supplier_name"], "SUPPLIES_TO", seed["root_name"]
    )
    assert [row["evidence"] for row in evidence] == ["공급 계약 근거 문장"]  # affirmed 1건
    assert await repository.fetch_latest_valuation(conn, "NOPE") is None


@pytest_asyncio.fixture
async def neo4j_conn():
    """search_theme_reasons 테스트 전용 접속 — seed 픽스처와 달리 데이터를 심지
    않고 실제 그래프(시드된 로컬 인덱스)를 그대로 조회하므로 연결만 잡는다."""

    await neo4j_client.connect()
    yield
    await neo4j_client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_theme_reasons_returns_listed_domestic_only(neo4j_conn):
    from beneficiary.agent.utils import embed

    vector = (await embed.embed_queries(["변압기 초고압 전력기기"]))[0]
    rows = await repository.search_theme_reasons(
        query_vector=vector, exclude_names=[], exclude_tickers=[],
        min_score=0.0, limit=10, over_fetch=50,
    )

    assert all(row["ticker"] for row in rows)
    assert all(row["market"] in ("KOSPI", "KOSDAQ") for row in rows)
    assert all(row["reason"] for row in rows)
    # ORDER BY score DESC 가 보존되는지
    assert rows == sorted(rows, key=lambda r: -r["score"])


@pytest_asyncio.fixture
async def scenario_reason_vector(seed):
    """search_theme_reasons exclusion 테스트 전용 픽스처.

    실 벌크 데이터는 Company.is_active 가 전혀 채워져 있지 않아(Task 6 보고서
    참고 — finngraph-etl 쪽 데이터 갭, 이 계층의 문제가 아니다)
    search_theme_reasons 의 상장 필터를 하나도 통과하지 못한다. is_active 를
    실제로 세팅하는 seed 픽스처의 root 기업 테마1 편입 사유에 실 Titan
    임베딩을 심어, 필터를 전부 만족하는 매치로 exclusion 로직을 검증한다.
    """

    from beneficiary.agent.utils import embed

    reason_text = f"초고압 변압기 및 전력기기 전문 제조 {seed['uid']}"
    vector = (await embed.embed_queries([reason_text]))[0]
    await neo4j_client.execute(
        """
MATCH (c:Company {name: $name})-[b:BELONGS_TO]->(t:Theme {name: $theme})
SET b.reason = $reason, b.reason_embedding = $embedding
""",
        {"name": seed["root_name"], "theme": seed["theme1"],
         "reason": reason_text, "embedding": vector},
    )
    return vector


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_theme_reasons_honors_exclusions(seed, scenario_reason_vector):
    # min_score=0.9: 질의 임베딩이 시드된 reason_embedding 과 동일 텍스트에서 나와
    # 코사인이 1.0 에 근접(관측 0.9998) — 0.0 으로 낮추지 않고도 점수 게이트를
    # 함께 검증하면서, 실 벌크 데이터의 최대 관측 점수(~0.77, is_active 갭으로
    # 어차피 필터 탈락)보다 한참 위라 오탐 없이 seed 매치만 걸린다.
    baseline = await repository.search_theme_reasons(
        query_vector=scenario_reason_vector, exclude_names=[], exclude_tickers=[],
        min_score=0.9, limit=5, over_fetch=50,
    )
    assert baseline, "기준 결과가 없으면 이 테스트는 아무것도 검증하지 못한다"
    assert seed["root_ticker"] in {row["ticker"] for row in baseline}

    excluded = await repository.search_theme_reasons(
        query_vector=scenario_reason_vector, exclude_names=[seed["root_name"]],
        exclude_tickers=[seed["root_ticker"]],
        min_score=0.9, limit=5, over_fetch=50,
    )
    assert seed["root_ticker"] not in {row["ticker"] for row in excluded}
