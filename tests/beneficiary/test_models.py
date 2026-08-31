"""LLM 구조화 출력 계약의 강제 규칙 확인 — 이진 극성, benefit 단일 impact."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from beneficiary.models import (
    Candidate,
    SupplyChainCandidate,
    FilterOutput,
    EvaluatorInsight,
    NewsPlan,
)


def test_news_plan_forces_binary_polarity():
    plan = NewsPlan(event_summary="s", polarity="negative")
    assert plan.core_items == []
    with pytest.raises(ValidationError):
        NewsPlan(event_summary="s", polarity="mixed")


def test_judge_insight_allows_benefit_only():
    ok = EvaluatorInsight(candidate_id="c01", impact="benefit", confidence="high", rationale="r [e01]")
    assert ok.evidence_ids == []
    with pytest.raises(ValidationError):
        EvaluatorInsight(candidate_id="c01", impact="damage", confidence="high", rationale="r")


def test_filter_output_defaults_empty():
    out = FilterOutput()
    assert out.strong == [] and out.weak == []


def test_candidate_defaults():
    c = Candidate(ticker="000001", name="회사", company_id=1, track="supply")
    assert c.relevance == "strong" and c.promoted is False
    assert c.matched_items == [] and c.source_edges == [] and c.evidence == []
    e = SupplyChainCandidate(gid=None, root_name="a", subject_name="s", object_name="o",
                      ticker="000002", name="공급사", company_id=2)
    assert e.relevance is None and e.disclosure_items == []
