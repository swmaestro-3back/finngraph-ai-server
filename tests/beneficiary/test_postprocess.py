"""v2 validate_and_rank — 후보별 eid 스코프·시장 쿼터 코드 강제 (LLM 없음)."""

from __future__ import annotations

from beneficiary.models import Candidate, JudgeInsight, JudgeOutput
from beneficiary.utils.postprocess import validate_and_rank


def _candidate(cid, ticker, market):
    c = Candidate(ticker=ticker, name=f"기업{ticker}", company_id=1, track="supply", market=market)
    c.cid = cid
    return c


def _insight(cid, eids, rationale="체크 통과 [e01]"):
    return JudgeInsight(candidate_id=cid, impact="benefit", confidence="high",
                        rationale=rationale, evidence_ids=eids)


BY_CID = {
    "c01": _candidate("c01", "000001", "KOSPI"),
    "c02": _candidate("c02", "000002", "KOSPI"),
    "c03": _candidate("c03", "000003", "KOSPI"),
    "c04": _candidate("c04", "000004", "KOSDAQ"),
}
EIDS = {"c01": {"e01"}, "c02": {"e02"}, "c03": {"e03"}, "c04": {"e04"}}


def test_cross_candidate_eid_citation_is_dropped():
    judge = JudgeOutput(event_interpretation="해석", insights=[
        _insight("c01", ["e01"]),
        _insight("c02", ["e01"]),  # 남의 근거만 인용 → 접지 실패로 폐기
    ])
    items = validate_and_rank(judge, BY_CID, EIDS)
    assert [item.candidate.cid for item in items] == ["c01"]


def test_market_quota_trims_to_two_preserving_order():
    judge = JudgeOutput(event_interpretation="해석", insights=[
        _insight("c01", ["e01"]), _insight("c02", ["e02"]),
        _insight("c03", ["e03"]),  # KOSPI 3번째 → 절단
        _insight("c04", ["e04"]),
    ])
    items = validate_and_rank(judge, BY_CID, EIDS)
    assert [item.candidate.cid for item in items] == ["c01", "c02", "c04"]
    assert [item.rank for item in items] == [1, 2, 3]


def test_v1_rules_survive_unknown_cid_dup_and_citationless_rationale():
    judge = JudgeOutput(event_interpretation="해석", insights=[
        _insight("cXX", ["e01"]),                       # 비실존 cid 폐기
        _insight("c01", ["e01", "eZZ"]),                # 비실존 eid 필터
        _insight("c01", ["e01"]),                       # 중복 cid — 첫 판정만
        _insight("c04", ["e04"], rationale="인용 없음"),  # 인용 없는 rationale → low
    ])
    items = validate_and_rank(judge, BY_CID, EIDS)
    assert len(items) == 2
    assert items[0].evidence_ids == ["e01"]
    assert items[1].confidence == "low"
