"""인사이트 서비스(supply_chain 단일 에이전트) 통합 테스트 — LLM 스텁, DB 실물.

검증하는 계약: object company ticker 로 Neo4j 유입 SUPPLIES_TO 탐색(subject
제외) → 시장별 시총 상위 후보 심사·랭킹, 앵커 없음 → no_candidates,
심사 실패 → 에러, 근거 id 접지, 재무 테이블이 심사 프롬프트에 포함되는지.
저장·캐시는 없다 — 실행 관측은 LangSmith 트레이싱 소관.
"""

from __future__ import annotations

import re

import pytest
import pytest_asyncio

from core import postgres_database
from graph.models import JudgeInsight, JudgeOutput
from graph.utils import llm
from insights import service

# DB 시드는 리포지토리 테스트의 픽스처를 재사용한다. graph_seed 가 Neo4j 쪽
# Company·SUPPLIES_TO 간선(+드라이버 수명)을 시드한다.
from tests.insights.test_repository_integration import conn, graph_seed, seed  # noqa: F401

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def pg_pool():
    await postgres_database.open()
    yield
    await postgres_database.close()


@pytest.fixture
def llm_stub(monkeypatch):
    state = {"calls": 0, "prompts": []}

    async def fake_judge(prompt: str) -> JudgeOutput:
        state["calls"] += 1
        state["prompts"].append(prompt)
        cids = re.findall(r"\[후보 (c\d+)\]", prompt)
        eids = re.findall(r"\[(e\d+)\]", prompt)
        return JudgeOutput(
            event_interpretation="공급망 해석",
            insights=[
                JudgeInsight(
                    candidate_id=cids[0],
                    impact="benefit",
                    confidence="medium",
                    rationale=f"체크리스트 1~3 통과 [{eids[0]}]",
                    evidence_ids=[eids[0]],
                )
            ],
            no_impact_ids=cids[1:],
        )

    monkeypatch.setattr(llm, "judge_supply", fake_judge)
    return state


async def test_unknown_news_raises_not_found(llm_stub):
    with pytest.raises(service.NewsNotFoundError):
        await service.get_news_insights(-1)


async def test_supply_agent_ranks_inbound_supplier_candidate(graph_seed, llm_stub):  # noqa: F811
    first = await service.get_news_insights(graph_seed["dup_news_id"])  # 클러스터 대표로 정규화

    assert first.status == "ok"
    assert first.rep_news_id == graph_seed["rep_news_id"]
    assert first.event_interpretation == "공급망 해석"
    assert len(first.items) == 1

    item = first.items[0]
    assert item.rank == 1
    # subject(앵커기업)에 공급하는 유입 이웃 중 뉴스 당사자(상대기업) 제외 = 동료기업.
    assert item.ticker == graph_seed["fellow_ticker"]
    assert item.path_type == ["supply_chain"]

    # 후보 구성: 동료기업(c01, KOSPI 시총 상위)뿐 — 유출 방향인 제3기업과
    # 상대기업·비상장은 패킹되지 않는다.
    prompt = llm_stub["prompts"][0]
    assert f"[후보 c01] {graph_seed['fellow_name']}" in prompt
    assert "KOSPI" in prompt.split("[후보 c01]")[1]  # 후보 카드에 시장 표기
    assert "[후보 c02]" not in prompt
    assert graph_seed["third_name"] not in prompt.split("[후보")[1]
    assert graph_seed["partner_name"] not in prompt.split("[후보")[1]  # 후보 카드에 없음
    assert graph_seed["unlisted_name"] not in prompt

    # 재무 테이블(table RAG)이 심사 프롬프트에 들어간다.
    assert "매출액 | 영업이익" in prompt
    assert "202512" in prompt
    assert "PER 8.4" in prompt


async def test_news_without_anchors_returns_no_candidates(graph_seed, llm_stub):  # noqa: F811
    news_id = graph_seed["bare_news_id"]  # 트리플이 없는 뉴스 = 앵커 없음

    result = await service.get_news_insights(news_id)

    assert result.status == "no_candidates"
    assert result.items == []
    assert llm_stub["calls"] == 0


async def test_judge_failure_raises(graph_seed, llm_stub, monkeypatch):  # noqa: F811
    async def broken_judge(prompt: str) -> JudgeOutput:
        raise RuntimeError("judge model down")

    monkeypatch.setattr(llm, "judge_supply", broken_judge)

    with pytest.raises(service.InsightGenerationError):
        await service.get_news_insights(graph_seed["rep_news_id"])
