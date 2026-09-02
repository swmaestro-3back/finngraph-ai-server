"""planner 순수 로직 — 계획 새니타이즈·제외 집합 (DB 없음)."""

from __future__ import annotations

import pytest

from beneficiary.models import RootCompany, NewsPlan, NewsContext, RelationLine, ScenarioProbe
from beneficiary.agent.nodes import planner
from beneficiary.agent.nodes.planner import normalize_plan
from beneficiary.agent.nodes.common import derive_exclusions


async def _async(value):
    return value


def _news():
    return NewsContext(title="t", summary="s", published_at="2026-09-01", link=None)


def _line(subject="루트 기업", s_code="000001", obj="상대", o_code=None, item=None,
          polarity="affirmed", s_impact=None):
    return RelationLine(subject_name=subject, subject_code=s_code, relation="SUPPLIES_TO",
                        object_name=obj, object_code=o_code, item=item,
                        polarity=polarity, subject_impact=s_impact, object_impact=None)


def test_sanitize_dedups_and_caps_core_items():
    plan = NewsPlan(
        event_summary="s", polarity="positive", core_items=["HBM", "HBM", "a", "b", "c", "d"],
    )
    clean = normalize_plan(plan)
    assert clean.core_items == ["HBM", "a", "b", "c", "d"]  # dedup + 상한 5


@pytest.mark.asyncio
async def test_negative_polarity_stops_with_not_positive(monkeypatch):
    """악재 뉴스는 수혜 분석 대상이 아니다 — 정상 종료로 돌려보낸다."""
    root_rows = [{"company_id": 1, "name": "루트", "ticker": "005930", "description": None}]

    class _Conn:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(planner.postgres_client, "connection", lambda: _Conn())
    monkeypatch.setattr(planner.repository, "fetch_root_companies",
                        lambda conn, nid: _async(root_rows))
    monkeypatch.setattr(planner.repository, "fetch_relation_lines",
                        lambda conn, nid: _async([]))
    monkeypatch.setattr(planner.llm, "plan_news",
                        lambda prompt: _async(NewsPlan(event_summary="s", polarity="negative")))

    result = await planner.build_plan({"rep_news_id": 1, "news": _news()})

    assert result["status"] == "not_positive"
    assert "호재" in result["reason"]


def test_sanitize_dedups_probes_by_stage_and_query():
    plan = NewsPlan(
        event_summary="s", polarity="positive",
        scenario_probes=[
            ScenarioProbe(stage=1, hypothesis="h1", query="변압기"),
            ScenarioProbe(stage=1, hypothesis="다른 문장", query="변압기"),  # 중복
            ScenarioProbe(stage=2, hypothesis="h2", query="변압기"),        # stage 다름 — 유지
            ScenarioProbe(stage=1, hypothesis="h3", query="   "),           # 빈 query
        ],
    )
    probes = normalize_plan(plan).scenario_probes
    assert [(p.stage, p.query) for p in probes] == [(1, "변압기"), (2, "변압기")]


def test_sanitize_drops_probe_with_blank_hypothesis():
    """가설이 공백이면 query 가 멀쩡해도 버린다 — 가설은 evaluator 가 대조할 문장이다."""
    plan = NewsPlan(
        event_summary="s", polarity="positive",
        scenario_probes=[
            ScenarioProbe(stage=1, hypothesis="   ", query="변압기"),  # 빈 가설
            ScenarioProbe(stage=1, hypothesis="h", query="전선"),
        ],
    )
    probes = normalize_plan(plan).scenario_probes
    assert [(p.hypothesis, p.query) for p in probes] == [("h", "전선")]


def test_sanitize_caps_probes_at_four():
    plan = NewsPlan(
        event_summary="s", polarity="positive",
        scenario_probes=[ScenarioProbe(stage=1, hypothesis=f"h{i}", query=f"q{i}")
                         for i in range(6)],
    )
    assert len(normalize_plan(plan).scenario_probes) == 4


def test_sanitize_drops_probes_when_not_positive():
    plan = NewsPlan(
        event_summary="s", polarity="negative",
        scenario_probes=[ScenarioProbe(stage=1, hypothesis="h", query="q")],
    )
    assert normalize_plan(plan).scenario_probes == []


def test_derive_exclusions_unions_names_and_tickers():
    # 루트 기업는 상장 국내 기업뿐(build_plan 이 필터) — 비상장 당사자(고객사)는
    # relation_lines 의 object name 경유로 제외 집합에 들어간다.
    root_companies = [RootCompany(company_id=1, name="루트 기업", ticker="000001", description=None),
               RootCompany(company_id=2, name="부루트 기업", ticker="000002", description=None)]
    lines = [_line(obj="상대", o_code="000009"), _line(obj="고객사", o_code=None)]
    names, tickers = derive_exclusions(root_companies, lines)
    assert names == {"루트 기업", "상대", "고객사", "부루트 기업"}
    assert tickers == {"000001", "000002", "000009"}
