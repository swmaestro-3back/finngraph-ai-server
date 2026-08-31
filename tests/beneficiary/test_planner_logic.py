"""planner 순수 로직 — 계획 새니타이즈·제외 집합 (DB 없음)."""

from __future__ import annotations

from beneficiary.models import RootCompany, NewsPlan, RelationLine, RivalProbe
from beneficiary.agent.nodes.planner import sanitize_plan
from beneficiary.agent.nodes.common import derive_exclusions


def _line(subject="루트 기업", s_code="000001", obj="상대", o_code=None, item=None,
          polarity="affirmed", s_impact=None):
    return RelationLine(subject_name=subject, subject_code=s_code, relation="SUPPLIES_TO",
                        object_name=obj, object_code=o_code, item=item,
                        polarity=polarity, subject_impact=s_impact, object_impact=None)


THEMES = {"루트 기업": [{"name": "테마A", "description": "", "member_count": 2},
                   {"name": "테마B", "description": "", "member_count": 3},
                   {"name": "테마C", "description": "", "member_count": 4},
                   {"name": "테마D", "description": "", "member_count": 5}]}


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


def test_derive_exclusions_unions_names_and_tickers():
    # 루트 기업는 상장 국내 기업뿐(build_plan 이 필터) — 비상장 당사자(고객사)는
    # relation_lines 의 object name 경유로 제외 집합에 들어간다.
    root_companies = [RootCompany(company_id=1, name="루트 기업", ticker="000001", description=None),
               RootCompany(company_id=2, name="부루트 기업", ticker="000002", description=None)]
    lines = [_line(obj="상대", o_code="000009"), _line(obj="고객사", o_code=None)]
    names, tickers = derive_exclusions(root_companies, lines)
    assert names == {"루트 기업", "상대", "고객사", "부루트 기업"}
    assert tickers == {"000001", "000002", "000009"}
