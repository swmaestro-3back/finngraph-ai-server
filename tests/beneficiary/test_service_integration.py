"""beneficiary 서비스 통합 테스트 — LLM 스텁, DB 실물.

검증 계약: 호재 트랙 e2e(공급사 추천·market/track/matched_items 매핑),
무캐시(매 호출 재계산), LLM 장애는 503 강등, 루트 기업 없음
no_root_companies, 미존재 뉴스 404.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from beneficiary import service
from beneficiary.models import FilterOutput, EvaluatorInsight, EvaluatorOutput, NewsPlan
from beneficiary.agent.utils import llm
from core import postgres_client

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
        ids = re.findall(r"\[([gk]\d+)\]", prompt)
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
