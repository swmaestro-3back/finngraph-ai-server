"""finance_collector — 근거 선정 순서·후보당 상한·affirmed 0건 제거 (DB 는 모듈 시임으로 대체)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

import sys

from beneficiary.models import Candidate, SupplyChainCandidate, NewsContext
from beneficiary import repository

# Import the finance_collector submodule directly from sys.modules to bypass
# __init__.py shadowing
import beneficiary.agent.nodes.finance_collector
collector_module = sys.modules['beneficiary.agent.nodes.finance_collector']


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    @asynccontextmanager
    async def fake_connection():
        yield object()

    monkeypatch.setattr(collector_module.postgres_client, "connection", fake_connection)

    async def no_financials(conn, company_id, limit=4):
        return [{"fiscal_yymm": "202512", "revenue": 100}]

    async def no_valuation(conn, ticker):
        return None

    monkeypatch.setattr(repository, "fetch_financial_history", no_financials)
    monkeypatch.setattr(repository, "fetch_latest_valuation", no_valuation)


def _edge(gid, subject):
    return SupplyChainCandidate(gid=gid, root_name="루트 기업", supplier_name=subject,
                         supplier_ticker="000001", supplier_id=1)


def _supply_candidate(edges):
    return Candidate(ticker="000001", name="공급사", company_id=1, track="supply",
                     market="KOSPI", source_edges=edges)


NEWS = NewsContext(title="트리거", summary=None, published_at="2026-08-30",
                   link="https://n.example/1")


async def test_supply_evidence_follows_gid_order_and_caps_at_six(monkeypatch):
    calls = []

    async def fake_evidence(conn, subject, relation, obj, limit=3):
        calls.append(subject)
        return [{"id": 1, "source_type": "news", "evidence": f"{subject}-{i}",
                 "item": None, "mentioned_at": "2026-08-01", "rcept_no": None,
                 "link": "https://l"} for i in range(3)]

    monkeypatch.setattr(repository, "fetch_edge_evidence", fake_evidence)
    candidate = _supply_candidate([_edge("g01", "간선1"), _edge("g02", "간선2"),
                                   _edge("g03", "간선3")])
    result = await collector_module.collect_financials({"news": NEWS, "candidates": [candidate]})
    kept = result["candidates"][0]
    assert len(kept.evidence) == 6  # 간선당 3건 × 2간선에서 상한 도달
    assert calls == ["간선1", "간선2"]  # g03 은 호출조차 안 함
    assert kept.financials == [{"fiscal_yymm": "202512", "revenue": 100}]


async def test_supply_candidate_with_zero_affirmed_evidence_is_dropped(monkeypatch):
    async def empty_evidence(conn, subject, relation, obj, limit=3):
        return []

    monkeypatch.setattr(repository, "fetch_edge_evidence", empty_evidence)
    result = await collector_module.collect_financials(
        {"news": NEWS, "candidates": [_supply_candidate([_edge("g01", "간선1")])]}
    )
    assert result["candidates"] == [] and "error" not in result  # 규칙 제거 (노드 실패 아님)


async def test_theme_candidate_gets_news_and_theme_evidence():
    candidate = Candidate(ticker="000003", name="수혜사", company_id=3, track="theme",
                          market="KOSPI", matched_themes=["테마A"],
                          matched_reasons=["대체 생산 경쟁", "동일 제품"])
    result = await collector_module.collect_financials({"news": NEWS, "candidates": [candidate]})
    kept = result["candidates"][0]
    types = [e.type for e in kept.evidence]
    assert types == ["news", "theme", "theme"]
    assert kept.evidence[0].link == "https://n.example/1"  # 트리거 뉴스 근거
    assert "대체 생산 경쟁" in kept.evidence[1].text and kept.evidence[1].link is None


async def test_both_candidate_survives_without_supply_evidence(monkeypatch):
    """both 후보는 공시 근거가 없어도 테마 근거로 살아남는다."""
    candidate = Candidate(
        ticker="000001", name="회사", company_id=1, track="both",
        matched_reasons=["[테마A] 변압기 주력"], market="KOSPI",
        source_edges=[_edge("g01", "간선1")],
    )

    async def empty_evidence(conn, subject, relation, obj, limit=3):
        return []

    monkeypatch.setattr(repository, "fetch_edge_evidence", empty_evidence)

    result = await collector_module.collect_financials(
        {"news": NEWS, "candidates": [candidate]}
    )

    assert len(result["candidates"]) == 1
    types = {e.type for e in result["candidates"][0].evidence}
    assert "theme" in types


async def test_both_candidate_loads_supply_and_theme_evidence(monkeypatch):
    """both 후보는 공급망 축과 테마 축 근거를 모두 적재한다 (한쪽만이 아니다)."""
    async def fake_evidence(conn, subject, relation, obj, limit=3):
        return [{"id": 1, "source_type": "disclosure", "evidence": "공시내용",
                 "item": None, "mentioned_at": "2026-08-01", "rcept_no": None,
                 "link": "https://l"}]

    monkeypatch.setattr(repository, "fetch_edge_evidence", fake_evidence)

    candidate = Candidate(
        ticker="000004", name="회사4", company_id=4, track="both",
        matched_reasons=["[테마A] 변압기 주력"], market="KOSPI",
        source_edges=[_edge("g01", "간선1")],
    )

    result = await collector_module.collect_financials({"news": NEWS, "candidates": [candidate]})

    kept = result["candidates"][0]
    types = {e.type for e in kept.evidence}
    assert "disclosure" in types  # 공급망 축
    assert "theme" in types  # 테마 축
    assert "news" in types  # 트리거 호재 뉴스
