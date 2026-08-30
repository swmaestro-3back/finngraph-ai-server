"""beneficiary 서비스 통합 테스트 — LLM 스텁, DB 실물 (Task 4 시드 재사용).

검증 계약: 호재 트랙 e2e(공급사 추천·market/track/matched_items 매핑),
악재 트랙 e2e(경쟁사 추천·트리거 뉴스 근거), 캐시 저장·히트(LLM 재호출 없음),
폴백 응답 비캐시, 루트 기업 없음 no_candidates, 미존재 뉴스 404.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from beneficiary import service
from beneficiary.models import FilterOutput, JudgeInsight, JudgeOutput, NewsPlan, RivalProbe
from beneficiary.utils import llm
from core import postgres_database

# Task 4 픽스처 재사용 (PG + Neo4j 시드, uid 유일화·정리 포함)
from tests.beneficiary.test_repository_integration import conn, seed  # noqa: F401

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def pg_pool():
    await postgres_database.open()
    yield
    await postgres_database.close()


@pytest.fixture
def llm_stub(monkeypatch):
    """3단 LLM 스텁 — polarity 는 테스트가 지정, filter 는 전부 strong, judge 는 전원 추천."""

    state = {"plan_calls": 0, "filter_calls": 0, "judge_calls": 0, "polarity": "positive"}

    async def fake_plan(prompt):
        state["plan_calls"] += 1
        if state["polarity"] == "negative":
            probes = [RivalProbe(subject_name=state["root_name"], themes=state["themes"])]
            return NewsPlan(event_summary="악재", polarity="negative",
                            core_items=["HBM"], rival_probes=probes)
        return NewsPlan(event_summary="호재", polarity="positive", core_items=["HBM"])

    async def fake_filter(prompt):
        state["filter_calls"] += 1
        import re
        ids = re.findall(r"\[([gk]\d+)\]", prompt)
        return FilterOutput(strong=ids, weak=[])

    async def fake_judge(prompt):
        state["judge_calls"] += 1
        import re
        cids = re.findall(r"\[후보 (c\d+)\]", prompt)
        eids = re.findall(r"\[(e\d+)\]", prompt)
        return JudgeOutput(
            event_interpretation="사건 해석",
            insights=[JudgeInsight(candidate_id=cids[0], impact="benefit",
                                   confidence="medium",
                                   rationale=f"체크리스트 통과 [{eids[0]}]",
                                   # 전체 인용 — 후처리의 후보별 스코프가 그 후보
                                   # 자신의 eid 만 남긴다(악재 테스트의 theme 근거 포함).
                                   evidence_ids=eids)],
            no_impact_ids=cids[1:],
        )

    monkeypatch.setattr(llm, "plan_news", fake_plan)
    monkeypatch.setattr(llm, "filter_supply", fake_filter)
    monkeypatch.setattr(llm, "filter_rivals", fake_filter)
    monkeypatch.setattr(llm, "judge_beneficiary", fake_judge)
    return state


async def test_unknown_news_raises_not_found(llm_stub):
    with pytest.raises(service.NewsNotFoundError):
        await service.get_news_beneficiaries(-1)


async def test_positive_track_recommends_supplier_and_caches(seed, llm_stub):  # noqa: F811
    response = await service.get_news_beneficiaries(seed["dup_news_id"])

    assert response.status == "ok"
    assert response.rep_news_id == seed["rep_news_id"]
    assert len(response.items) == 1
    item = response.items[0]
    assert item.ticker == seed["supplier_ticker"]  # 루트 기업에 공급하는 유일한 상장 이웃
    assert item.track == "supply" and item.market == "KOSDAQ"
    assert "HBM" in item.matched_items
    assert item.rank == 1 and item.evidence  # 근거 링크 포함

    # 캐시 히트 — 같은 클러스터의 다른 뉴스 id 로 재호출해도 LLM 이 다시 돌지 않는다.
    calls_before = (llm_stub["plan_calls"], llm_stub["judge_calls"])
    again = await service.get_news_beneficiaries(seed["rep_news_id"])
    assert (llm_stub["plan_calls"], llm_stub["judge_calls"]) == calls_before
    assert again.news_id == seed["rep_news_id"]  # 캐시 페이로드의 news_id 는 요청 값으로 교체
    assert again.items[0].ticker == item.ticker


async def test_negative_track_recommends_rival_with_trigger_news_evidence(seed, llm_stub):  # noqa: F811
    llm_stub["polarity"] = "negative"
    llm_stub["root_name"] = seed["root_name"]
    llm_stub["themes"] = [seed["theme1"], seed["theme2"]]

    response = await service.get_news_beneficiaries(seed["dup_news_id"])

    assert response.status == "ok"
    item = response.items[0]
    assert item.ticker == seed["rival_ticker"]  # 자회사·당사자·이웃 제외 후 유일한 경쟁사
    assert item.track == "rival" and set(item.via_themes) == {seed["theme1"], seed["theme2"]}
    evidence_types = [e.type for e in item.evidence]
    assert "news" in evidence_types and "theme" in evidence_types
    news_evidence = next(e for e in item.evidence if e.type == "news")
    assert news_evidence.link == f"https://news.example/{seed['uid']}"  # 트리거 원 뉴스 링크


async def test_plan_fallback_response_is_not_cached(seed, llm_stub, conn, monkeypatch):  # noqa: F811
    async def boom(prompt):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(llm, "plan_news", boom)
    response = await service.get_news_beneficiaries(seed["dup_news_id"])
    assert response.status in ("ok", "no_candidates")  # 폴백 계획으로 계속 진행은 한다

    from beneficiary import repository
    cached = await repository.fetch_cached_payload(conn, seed["rep_news_id"], response.prompt_version)
    assert cached is None  # 폴백 응답은 캐시 금지


async def test_news_without_relations_returns_no_candidates(seed, llm_stub, conn):  # noqa: F811
    async with conn.cursor() as cur:
        await cur.execute("INSERT INTO news (title) VALUES ('무관') RETURNING id")
        bare_id = (await cur.fetchone())["id"]
    await conn.commit()
    try:
        response = await service.get_news_beneficiaries(bare_id)
        assert response.status == "no_candidates" and response.items == []
        assert llm_stub["plan_calls"] == 0  # 루트 기업 0명 — LLM 은 돌지 않는다
    finally:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM news WHERE id = %s", (bare_id,))
        await conn.commit()
