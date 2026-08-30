"""analyze_news 순수 로직 — 폴백 계획·새니타이즈·probe 보강·제외 집합 (DB 없음)."""

from __future__ import annotations

from beneficiary.models import RootCompany, NewsPlan, RelationLine, RivalProbe
from beneficiary.nodes.analyze import build_fallback_plan, build_probe_fallback, sanitize_plan
from beneficiary.nodes.common import derive_exclusions


def _line(subject="루트 기업", s_code="000001", obj="상대", o_code=None, item=None,
          polarity="affirmed", s_impact=None):
    return RelationLine(subject_name=subject, subject_code=s_code, relation="SUPPLIES_TO",
                        object_name=obj, object_code=o_code, item=item,
                        polarity=polarity, subject_impact=s_impact, object_impact=None)


THEMES = {"루트 기업": [{"name": "테마A", "description": "", "member_count": 2},
                   {"name": "테마B", "description": "", "member_count": 3},
                   {"name": "테마C", "description": "", "member_count": 4},
                   {"name": "테마D", "description": "", "member_count": 5}]}


def test_fallback_plan_votes_affirmed_pos_neg_only():
    lines = [
        _line(item="HBM", s_impact="negative"),
        _line(item="DDR5", s_impact="negative"),
        _line(item="TC본더", s_impact="positive"),
        _line(item="오염아이템", polarity="denied", s_impact="negative"),  # 폴백에서 제외
        _line(item=None, s_impact="neutral"),  # neutral 미투표
    ]
    plan = build_fallback_plan(lines)
    assert plan.polarity == "negative"
    assert plan.core_items == ["HBM", "DDR5", "TC본더"]  # affirmed 만, 순서 보존
    assert plan.rival_probes == [] and plan.event_summary.startswith("(자동 폴백)")


def test_fallback_plan_tie_or_empty_defaults_positive():
    assert build_fallback_plan([]).polarity == "positive"
    tie = [_line(s_impact="positive"), _line(s_impact="negative")]
    assert build_fallback_plan(tie).polarity == "positive"


def test_fallback_plan_caps_core_items_at_five():
    lines = [_line(item=f"아이템{i}", s_impact="positive") for i in range(7)]
    assert len(build_fallback_plan(lines).core_items) == 5


def test_sanitize_drops_unknown_subjects_and_themes_and_dedups():
    plan = NewsPlan(
        event_summary="s", polarity="negative", core_items=["HBM", "HBM", "a", "b", "c", "d"],
        rival_probes=[
            RivalProbe(subject_name="루트 기업", themes=["테마A", "없는테마", "테마B"]),
            RivalProbe(subject_name="루트 기업", themes=["테마C"]),  # 중복 subject — 첫 것만
            RivalProbe(subject_name="약칭기업", themes=["테마A"]),  # 목록 밖 — 폐기
        ],
    )
    clean = sanitize_plan(plan, THEMES)
    assert clean.core_items == ["HBM", "a", "b", "c", "d"]  # dedup + 상한 5
    assert len(clean.rival_probes) == 1
    assert clean.rival_probes[0].subject_name == "루트 기업"
    assert clean.rival_probes[0].themes == ["테마A", "테마B"]


def test_sanitize_clears_probes_on_positive():
    plan = NewsPlan(event_summary="s", polarity="positive",
                    rival_probes=[RivalProbe(subject_name="루트 기업", themes=["테마A"])])
    assert sanitize_plan(plan, THEMES).rival_probes == []


def test_probe_fallback_takes_top3_specific_themes():
    probes = build_probe_fallback(THEMES)
    assert probes == [RivalProbe(subject_name="루트 기업", themes=["테마A", "테마B", "테마C"])]
    assert build_probe_fallback({}) == []


def test_derive_exclusions_unions_names_and_tickers():
    # 루트 기업는 상장 국내 기업뿐(analyze_news 가 필터) — 비상장 당사자(고객사)는
    # relation_lines 의 object name 경유로 제외 집합에 들어간다.
    root_companies = [RootCompany(company_id=1, name="루트 기업", ticker="000001", description=None),
               RootCompany(company_id=2, name="부루트 기업", ticker="000002", description=None)]
    lines = [_line(obj="상대", o_code="000009"), _line(obj="고객사", o_code=None)]
    names, tickers = derive_exclusions(root_companies, lines)
    assert names == {"루트 기업", "상대", "고객사", "부루트 기업"}
    assert tickers == {"000001", "000002", "000009"}
