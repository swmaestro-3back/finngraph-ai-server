"""심사 출력 후처리(검증·강등·랭킹) 테스트.

프롬프트를 신뢰하지 않는 안전망이 핵심이다 — 전달하지 않은 id 인용,
근거 인용 없는 판단을 코드에서 재강제한다. 순위는 심사 출력 순서를 따른다.
"""

from __future__ import annotations

from graph.models import Candidate, Evidence, JudgeInsight, JudgeOutput
from graph.utils.postprocess import validate_and_rank


def _candidate(cid: str, ticker: str) -> Candidate:
    return Candidate(
        ticker=ticker,
        name=f"기업{ticker}",
        company_id=None,
        relation_lines=[],
        evidence=[Evidence(type="news", text="근거", eid="e01")],
        cid=cid,
    )


def _insight(cid: str, impact: str = "benefit", confidence: str = "medium", **kwargs):
    defaults = {"rationale": "근거 기반 판단 [e01]", "evidence_ids": ["e01"]}
    defaults.update(kwargs)
    return JudgeInsight(candidate_id=cid, impact=impact, confidence=confidence, **defaults)


def _run(insights: list[JudgeInsight], candidates: list[Candidate], eids: set[str] = frozenset()):
    judge = JudgeOutput(event_interpretation="사건 해석", insights=insights, no_impact_ids=[])
    by_cid = {c.cid: c for c in candidates}
    return validate_and_rank(judge, by_cid, known_eids=eids or {"e01"})


def test_unknown_candidate_id_is_dropped():
    items = _run([_insight("c99")], [_candidate("c01", "005930")])

    assert items == []


def test_neutral_insight_is_dropped():
    items = _run([_insight("c01", impact="neutral")], [_candidate("c01", "005930")])

    assert items == []


def test_unknown_evidence_ids_are_filtered_and_ungrounded_item_dropped():
    candidate = _candidate("c01", "005930")

    filtered = _run([_insight("c01", evidence_ids=["e01", "e77"])], [candidate])
    assert filtered[0].evidence_ids == ["e01"]

    dropped = _run([_insight("c01", evidence_ids=["e77"])], [candidate])
    assert dropped == []


def test_rationale_without_citation_is_demoted_to_low():
    items = _run(
        [_insight("c01", rationale="인용 없는 판단")],
        [_candidate("c01", "005930")],
    )

    assert items[0].confidence == "low"


def test_duplicate_candidate_id_keeps_first_judgment_only():
    items = _run(
        [_insight("c01", confidence="high"), _insight("c01", confidence="low")],
        [_candidate("c01", "159010")],
    )

    assert len(items) == 1
    assert items[0].confidence == "high"


def test_ranking_follows_judge_output_order():
    """심사가 낸 순서 = 재무 체크리스트 랭킹이므로 그대로 보존한다."""
    candidates = [_candidate("c01", "S1"), _candidate("c02", "S2"), _candidate("c03", "S3")]
    insights = [
        _insight("c02", confidence="high"),
        _insight("c01", confidence="low"),
        _insight("c03", confidence="medium"),
    ]

    items = _run(insights, candidates)

    assert [(i.candidate.ticker, i.rank) for i in items] == [("S2", 1), ("S1", 2), ("S3", 3)]
