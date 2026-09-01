"""beneficiary 서비스 통합 테스트 — LLM 스텁, DB 실물.

검증 계약: 호재 트랙 e2e(공급사 추천·market/track/matched_items 매핑),
theme 트랙 e2e(시나리오 벡터 검색·필터까지 실 실행), 무캐시(매 호출 재계산),
LLM 장애는 503 강등, 루트 기업 없음 no_root_companies, 미존재 뉴스 404,
악재는 not_positive 로 200 정상 종료.
"""

from __future__ import annotations

import re

import pytest
import pytest_asyncio

from beneficiary import service
from beneficiary.models import (
    EvaluatorInsight,
    EvaluatorOutput,
    FilterOutput,
    NewsPlan,
    ScenarioProbe,
)
from beneficiary.agent.utils import embed, llm
from core import neo4j_client, postgres_client

# 데이터 계층 테스트의 시드 픽스처 재사용 (PG + Neo4j, uid 유일화·정리 포함)
from tests.beneficiary.test_repository_integration import conn, seed  # noqa: F401

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def pg_pool():
    await postgres_client.connect()
    yield
    await postgres_client.close()


@pytest.fixture
def llm_stub(monkeypatch):
    """3단 LLM 스텁 — plan 은 항상 positive, filter 는 전부 strong, evaluator 는 전원 추천."""

    state = {"plan_calls": 0, "filter_calls": 0, "evaluate_calls": 0}

    async def fake_plan(prompt):
        state["plan_calls"] += 1
        return NewsPlan(event_summary="호재", polarity="positive", core_items=["HBM"])

    async def fake_filter(prompt):
        state["filter_calls"] += 1
        import re
        # gNN = 공급 간선 id, tNN = 테마 히트 id. 같은 스텁이 두 트랙의
        # filter 프롬프트를 모두 받으므로 둘 다 잡는다.
        ids = re.findall(r"\[([gt]\d+)\]", prompt)
        return FilterOutput(strong=ids, weak=[])

    async def fake_evaluate(prompt):
        state["evaluate_calls"] += 1
        import re
        cids = re.findall(r"\[후보 (c\d+)\]", prompt)
        eids = re.findall(r"\[(e\d+)\]", prompt)
        return EvaluatorOutput(
            event_interpretation="사건 해석",
            insights=[EvaluatorInsight(candidate_id=cids[0], impact="benefit",
                                   confidence="medium",
                                   rationale=f"체크리스트 통과 [{eids[0]}]",
                                   evidence_ids=eids)],
            no_impact_ids=cids[1:],
        )

    monkeypatch.setattr(llm, "plan_news", fake_plan)
    monkeypatch.setattr(llm, "filter_supply", fake_filter)
    monkeypatch.setattr(llm, "evaluate_beneficiary", fake_evaluate)
    return state


async def test_unknown_news_raises_not_found(llm_stub):
    with pytest.raises(service.NewsNotFoundError):
        await service.get_news_beneficiaries(-1)


async def test_positive_track_recommends_supplier(seed, llm_stub):  # noqa: F811
    response = await service.get_news_beneficiaries(seed["dup_news_id"])

    assert response.status == "ok"
    assert response.rep_news_id == seed["rep_news_id"]
    assert len(response.items) == 1
    item = response.items[0]
    assert item.ticker == seed["supplier_ticker"]  # 루트 기업에 공급하는 유일한 상장 이웃
    assert item.track == "supply" and item.market == "KOSDAQ"
    assert "HBM" in item.matched_items
    assert item.rank == 1 and item.evidence  # 근거 링크 포함

    # 무캐시 — 같은 클러스터의 다른 뉴스 id 로 재호출하면 워크플로우가 다시 돈다.
    calls_before = llm_stub["plan_calls"]
    again = await service.get_news_beneficiaries(seed["rep_news_id"])
    assert llm_stub["plan_calls"] == calls_before + 1
    assert again.news_id == seed["rep_news_id"]
    assert again.items[0].ticker == item.ticker  # 결정적 파이프라인 — 결과는 동일


async def test_plan_llm_failure_raises_generation_error(seed, llm_stub, monkeypatch):  # noqa: F811
    async def boom(prompt):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(llm, "plan_news", boom)
    # 폴백 계획 없음 — 장애는 계획을 지어내지 않고 503 으로 올라간다.
    with pytest.raises(service.BeneficiaryGenerationError):
        await service.get_news_beneficiaries(seed["dup_news_id"])


async def test_news_without_relations_stops_with_reason(seed, llm_stub, conn):  # noqa: F811
    async with conn.cursor() as cur:
        await cur.execute("INSERT INTO news (title) VALUES ('무관') RETURNING id")
        bare_id = (await cur.fetchone())["id"]
    await conn.commit()
    try:
        response = await service.get_news_beneficiaries(bare_id)
        assert response.status == "no_root_companies" and response.items == []
        assert response.reason  # 어디서 멈췄는지 사유가 응답에 실린다
        assert llm_stub["plan_calls"] == 0  # 루트 기업 0명 — LLM 은 돌지 않는다
    finally:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM news WHERE id = %s", (bare_id,))
        await conn.commit()


async def test_not_positive_returns_200_with_empty_items(seed, monkeypatch):  # noqa: F811
    """악재는 오류가 아니라 정상 종료다 — 503 이 아니라 200 + 빈 목록.

    news_id 는 seed 가 심은 실물 행을 쓴다 — 임의 상수(예: 1)는 로컬 DB 에
    해당 행이 없으면 NewsNotFoundError 로 먼저 죽어 이 테스트가 검증하려는
    지점(그래프가 not_positive 를 낸 뒤의 매핑)에 닿지도 못한다.
    """

    async def _fake_graph(state, config=None):
        return {"status": "not_positive", "reason": "호재로 보기 어려운 뉴스입니다.",
                "items": [], "pool_size": 0}

    monkeypatch.setattr(service.beneficiary_graph, "ainvoke", _fake_graph)

    response = await service.get_news_beneficiaries(news_id=seed["dup_news_id"])

    assert response.status == "not_positive"
    assert response.items == []
    assert response.prompt_version == "c1"


@pytest_asyncio.fixture
async def theme_reason_vector(seed):  # noqa: F811
    """rival 기업의 theme1 편입 사유에 실 Titan 임베딩을 심는다 — theme_track e2e 전용.

    root 가 아니라 rival 에 심는다: expand_theme 은 derive_exclusions 로 루트
    기업 자신과 relation_lines 당사자(root, partner)를 배제한다. root 에
    심으면 벡터 검색은 히트해도 배제 필터가 곧바로 지워, theme 트랙이 원인
    불명으로 빈손이 된다(test_repository_integration.scenario_reason_vector 와
    같은 함정). rival 은 당사자도 루트도 아니라 배제되지 않는다.
    """

    reason_text = f"초고압 변압기 및 전력기기 전문 제조 {seed['uid']}"
    vector = (await embed.embed_queries([reason_text]))[0]
    await neo4j_client.execute(
        """
MATCH (c:Company {name: $name})-[b:BELONGS_TO]->(t:Theme {name: $theme})
SET b.reason = $reason, b.reason_embedding = $embedding
""",
        {"name": seed["rival_name"], "theme": seed["theme1"],
         "reason": reason_text, "embedding": vector},
    )
    return reason_text


async def test_theme_track_runs_end_to_end_and_recommends_theme_candidate(
    seed, llm_stub, theme_reason_vector, monkeypatch  # noqa: F811
):
    """theme_track 이 실제로 벡터 검색·필터까지 실행돼 시나리오 후보를 낸다.

    회귀 대상: 공유 llm_stub 의 plan 은 scenario_probes 가 항상 비어 있어
    (다른 테스트들이 이 단축 경로에 의존한다), theme_track 은 workflow.py 의
    "probe 0개면 서브그래프를 호출하지 않는다" 분기를 매번 타고 만다 —
    expand_theme(실 Neo4j 벡터 검색)이 그래프 전체 안에서 한 번도 실행된 적이
    없었다. 이 테스트만 probe 를 채운 plan 으로 교체해 실 서브그래프를 끝까지
    태우고, rival 기업이 theme 트랙 후보로 응답에 도달하는지 확인한다 — 응답이
    200 이라는 것만으로는 theme 트랙이 조용히 빈손이어도 통과하므로, 후보
    도달 자체를 단언한다.
    """

    async def fake_plan_with_probe(prompt):
        return NewsPlan(
            event_summary="호재", polarity="positive", core_items=["HBM"],
            scenario_probes=[ScenarioProbe(
                stage=1, hypothesis="전력기기 수요 확대", query=theme_reason_vector,
            )],
        )

    async def fake_filter_theme(prompt):
        ids = re.findall(r"\[(t\d+)\]", prompt)
        return FilterOutput(strong=ids, weak=[])

    async def fake_evaluate_multi(prompt):
        # 공유 llm_stub 의 fake_evaluate 는 후보 1개(cids[0])만 추천한다 —
        # 이 테스트는 supply(공급사)·theme(rival) 두 후보가 동시에 뜨므로,
        # 등장하는 모든 후보를 각자의 스코프 eid 로 근거 삼아 추천하는
        # 버전이 필요하다.
        blocks = re.split(r"(?=\[후보 c\d+\])", prompt)
        insights = []
        for block in blocks:
            match = re.match(r"\[후보 (c\d+)\]", block)
            if not match:
                continue
            eids = re.findall(r"\[(e\d+)\]", block)
            if not eids:
                continue
            insights.append(EvaluatorInsight(
                candidate_id=match.group(1), impact="benefit", confidence="medium",
                rationale=f"체크리스트 통과 [{eids[0]}]", evidence_ids=eids,
            ))
        return EvaluatorOutput(event_interpretation="사건 해석", insights=insights,
                                no_impact_ids=[])

    monkeypatch.setattr(llm, "plan_news", fake_plan_with_probe)
    monkeypatch.setattr(llm, "filter_theme", fake_filter_theme)
    monkeypatch.setattr(llm, "evaluate_beneficiary", fake_evaluate_multi)

    response = await service.get_news_beneficiaries(seed["dup_news_id"])

    assert response.status == "ok"
    by_ticker = {item.ticker: item for item in response.items}
    assert seed["rival_ticker"] in by_ticker  # theme 트랙 산출물이 실제로 응답에 도달
    rival_item = by_ticker[seed["rival_ticker"]]
    assert rival_item.track in ("theme", "both")
    assert seed["theme1"] in rival_item.matched_themes
