"""v2 validate_and_rank — 후보별 eid 스코프·시장 쿼터 코드 강제 (LLM 없음)."""

from __future__ import annotations

from beneficiary.models import Candidate, EvaluatorInsight, EvaluatorOutput, SubgraphResult
from beneficiary.agent.utils.postprocess import validate_and_rank
from beneficiary.agent.nodes.evaluator import build_track_note


def _candidate(cid, ticker, market):
    c = Candidate(ticker=ticker, name=f"기업{ticker}", company_id=1, track="supply", market=market)
    c.cid = cid
    return c


def _insight(cid, eids, rationale="HBM 납품 이력이 있고 영업이익이 3년 연속 늘었다."):
    return EvaluatorInsight(candidate_id=cid, impact="benefit", confidence="high",
                        rationale=rationale, evidence_ids=eids, caveats="부채비율이 높다.")


BY_CID = {
    "c01": _candidate("c01", "000001", "KOSPI"),
    "c02": _candidate("c02", "000002", "KOSPI"),
    "c03": _candidate("c03", "000003", "KOSPI"),
    "c04": _candidate("c04", "000004", "KOSDAQ"),
}
EIDS = {"c01": {"e01"}, "c02": {"e02"}, "c03": {"e03"}, "c04": {"e04"}}


def test_cross_candidate_eid_citation_is_dropped():
    evaluation = EvaluatorOutput(event_interpretation="해석", insights=[
        _insight("c01", ["e01"]),
        _insight("c02", ["e01"]),  # 남의 근거만 인용 → 접지 실패로 폐기
    ])
    items = validate_and_rank(evaluation, BY_CID, EIDS)
    assert [item.candidate.cid for item in items] == ["c01"]


def test_market_quota_trims_to_two_preserving_order():
    evaluation = EvaluatorOutput(event_interpretation="해석", insights=[
        _insight("c01", ["e01"]), _insight("c02", ["e02"]),
        _insight("c03", ["e03"]),  # KOSPI 3번째 → 절단
        _insight("c04", ["e04"]),
    ])
    items = validate_and_rank(evaluation, BY_CID, EIDS)
    assert [item.candidate.cid for item in items] == ["c01", "c02", "c04"]
    assert [item.rank for item in items] == [1, 2, 3]


def test_rules_reject_unknown_cid_and_dup_and_filter_unknown_eid():
    evaluation = EvaluatorOutput(event_interpretation="해석", insights=[
        _insight("cXX", ["e01"]),          # 비실존 cid 폐기
        _insight("c01", ["e01", "eZZ"]),   # 비실존 eid 필터
        _insight("c01", ["e01"]),          # 중복 cid — 첫 판정만
        _insight("c04", ["e04"]),
    ])
    items = validate_and_rank(evaluation, BY_CID, EIDS)
    assert len(items) == 2
    assert items[0].evidence_ids == ["e01"]


def test_confidence_is_taken_as_given_without_citation_in_prose():
    """본문 [eNN] 인용은 더 이상 요구하지 않는다 — 접지는 evidence_ids 가 맡는다."""
    evaluation = EvaluatorOutput(event_interpretation="해석", insights=[
        _insight("c01", ["e01"], rationale="인용 기호 없이 쓴 사용자용 서술."),
    ])
    items = validate_and_rank(evaluation, BY_CID, EIDS)
    assert [item.confidence for item in items] == ["high"]


def test_track_note_distinguishes_empty_from_failed():
    note = build_track_note(SubgraphResult(status="no_pool"), SubgraphResult())
    assert "공급망" in note and "찾지 못해" in note

    note = build_track_note(SubgraphResult(), SubgraphResult(error="boom"))
    assert "시나리오 테마" in note and "실패" in note

    assert build_track_note(SubgraphResult(), SubgraphResult()) is None


def test_track_note_covers_remaining_branches_and_error_precedence():
    # supply.error 단독 — 시나리오 테마 축만으로 도출됐다는 메시지 (공급망 축 실패)
    note = build_track_note(SubgraphResult(error="boom"), SubgraphResult())
    assert "공급망" in note and "실패" in note

    # theme.status 단독 — 공급망 축만으로 도출됐다는 메시지 (시나리오 테마 축이 비었음)
    note = build_track_note(SubgraphResult(), SubgraphResult(status="no_pool"))
    assert "시나리오 테마" in note and "찾지 못해" in note

    # 두 축 모두 신호가 있을 때: supply 는 status(비었음), theme 는 error(장애) —
    # error 가 축을 가리지 않고 status 보다 우선해야 한다. 우선순위가 뒤집히면
    # (status 를 error 보다 먼저 검사하면) 이 케이스는 supply.status 메시지
    # ("공급망...찾지 못해")를 반환해 아래 단언이 깨진다.
    note = build_track_note(SubgraphResult(status="no_pool"), SubgraphResult(error="boom"))
    assert "시나리오 테마" in note and "실패" in note


def test_caveats_are_left_untouched_by_postprocess():
    """캐비앗은 종목 한계만 담는다 — 탐색 축 현황은 응답의 analysis_note 로 나간다."""
    from beneficiary.models import Candidate, EvaluatorInsight, EvaluatorOutput, Evidence

    candidate = Candidate(ticker="000001", name="회사", company_id=1, track="theme",
                          market="KOSPI", cid="c01")
    candidate.evidence = [Evidence(type="theme", text="[테마A] 사유", eid="e01")]
    evaluation = EvaluatorOutput(
        event_interpretation="해석",
        insights=[EvaluatorInsight(candidate_id="c01", impact="benefit",
                                   confidence="medium",
                                   rationale="테마 편입 사유가 시나리오와 맞는다.",
                                   evidence_ids=["e01"], caveats="기존 캐비앗")],
    )

    items = validate_and_rank(evaluation, {"c01": candidate}, {"c01": {"e01"}})

    assert items and items[0].caveats == "기존 캐비앗"
