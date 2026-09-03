"""패킹 형식·cid/eid 부여 규칙 테스트 — 형식 변경 시 PROMPT_VERSION 인상 필요."""

from __future__ import annotations

from beneficiary.models import (
    RootCompany,
    Candidate,
    ScenarioProbe,
    SupplyEdgeCandidate,
    Evidence,
    NewsContext,
    NewsPlan,
    RelationLine,
    ThemeCandidate,
)
from beneficiary.agent.utils.packer import (
    pack_evaluator_context,
    pack_plan_context,
    pack_supply_filter_context,
    pack_theme_filter_context,
)

NEWS = NewsContext(title="타이틀", summary="요약", published_at="2026-08-30", link="https://n.example/1")
ROOT = RootCompany(company_id=1, name="루트기업", ticker="000001", description="설명")
PLAN = NewsPlan(event_summary="사건", polarity="positive", core_items=["HBM"])
PLAN_WITH_AXES = NewsPlan(
    event_summary="사건", polarity="positive", core_items=["HBM"],
    demand_shift="증설 지출은 공정 장비로 간다.", certainty="MOU 단계다.",
)
THEME_PLAN = NewsPlan(
    event_summary="사건", polarity="positive",
    scenario_probes=[ScenarioProbe(stage=1, hypothesis="직접 수혜 가설", query="q1"),
                      ScenarioProbe(stage=2, hypothesis="2차 파생 가설", query="q2")],
)


def _edge(gid="g01", items=("HBM",)):
    return SupplyEdgeCandidate(gid=gid, root_name="루트기업", supplier_name="공급사",
                         supplier_ticker="000002", supplier_id=2, supplier_market="KOSPI",
                         disclosure_items=list(items), news_items=[], disclosure_count=2,
                         news_mention_count=5)


def _hit(tid="t01", stage=1):
    return ThemeCandidate(tid=tid, stage=stage, hypothesis="직접 수혜 가설", ticker="000003",
                          name="테마사", company_id=3, market="KOSDAQ", score=0.72,
                          matched_themes=["테마A", "테마B"],
                          matched_reasons=["[테마A] 이유1", "[테마B] 이유2"])


def test_pack_plan_context_lists_root_companies_and_relations():
    lines = [RelationLine(subject_name="루트기업", subject_code="000001", relation="SUPPLIES_TO",
                          object_name="상대기업", object_code="000009", item="HBM",
                          polarity="affirmed", subject_impact="negative", object_impact="neutral")]
    prompt = pack_plan_context(NEWS, [ROOT], lines)
    assert "타이틀" in prompt and "루트기업" in prompt
    assert "SUPPLIES_TO" in prompt and "affirmed" in prompt


def test_pack_supply_filter_lines_show_items_or_placeholder():
    prompt = pack_supply_filter_context(PLAN, [_edge(), _edge(gid="g02", items=())])
    assert "[g01]" in prompt and "HBM" in prompt and "공시2·뉴스5" in prompt
    assert "items: (없음)" in prompt  # 빈 아이템 간선 표기


def test_pack_theme_filter_lists_hypotheses_and_reasons():
    prompt = pack_theme_filter_context(THEME_PLAN, [_hit()])
    assert "(stage 1) 직접 수혜 가설" in prompt and "(stage 2) 2차 파생 가설" in prompt
    assert "[t01] (stage 1) 테마사 (000003) | 가설: 직접 수혜 가설 | 테마: 테마A, 테마B" in prompt
    assert "편입 사유: [테마A] 이유1" in prompt and "편입 사유: [테마B] 이유2" in prompt


def test_pack_theme_filter_candidate_line_shows_own_hypothesis_when_stage_ambiguous():
    # 같은 stage 에 가설이 두 개면 stage 번호만으로는 후보가 어느 가설에 매칭됐는지
    # 알 수 없다 — 후보 자신의 hypothesis 를 그 줄에 직접 박아야 한다.
    plan = NewsPlan(
        event_summary="사건", polarity="positive",
        scenario_probes=[ScenarioProbe(stage=1, hypothesis="가설 A", query="qA"),
                          ScenarioProbe(stage=1, hypothesis="가설 B", query="qB")],
    )
    hit_a = ThemeCandidate(tid="t01", stage=1, hypothesis="가설 A", ticker="000003",
                           name="테마사A", company_id=3, market="KOSDAQ",
                           matched_themes=["테마A"], matched_reasons=["이유1"])
    hit_b = ThemeCandidate(tid="t02", stage=1, hypothesis="가설 B", ticker="000004",
                           name="테마사B", company_id=4, market="KOSDAQ",
                           matched_themes=["테마B"], matched_reasons=["이유2"])
    prompt = pack_theme_filter_context(plan, [hit_a, hit_b])
    line_a = next(line for line in prompt.splitlines() if line.startswith("[t01]"))
    line_b = next(line for line in prompt.splitlines() if line.startswith("[t02]"))
    assert "가설 A" in line_a and "가설 B" not in line_a
    assert "가설 B" in line_b and "가설 A" not in line_b


def test_pack_judge_assigns_scoped_eids_and_marks_promotion():
    c1 = Candidate(ticker="000002", name="공급사", company_id=2, track="supply", market="KOSPI",
                   matched_items=["HBM"], relation_lines=["공급사 →공급→ 루트기업"],
                   evidence=[Evidence(type="disclosure", text="근거1", date="2026-08-01"),
                             Evidence(type="news", text="근거2", date="2026-08-02")])
    c2 = Candidate(ticker="000003", name="테마사", company_id=3, track="theme", market="KOSDAQ",
                   relevance="weak", promoted=True, matched_themes=["테마A"],
                   evidence=[Evidence(type="news", text="트리거", link="https://n.example/1")])
    packed = pack_evaluator_context(NEWS, [ROOT], PLAN, [c1, c2])
    assert list(packed.by_cid) == ["c01", "c02"]
    assert packed.eids_by_cid["c01"] == {"e01", "e02"}
    assert packed.eids_by_cid["c02"] == {"e03"}  # eid 는 전역 연번, 스코프는 후보별
    assert c1.cid == "c01" and c1.evidence[0].eid == "e01"
    assert "트랙 공급" in packed.prompt and "트랙 시나리오 테마" in packed.prompt
    assert "weak(승격)" in packed.prompt
    assert "매칭 아이템: HBM" in packed.prompt


def test_pack_judge_shows_stage_label_only_for_staged_candidates():
    c1 = Candidate(ticker="000002", name="공급사", company_id=2, track="supply", market="KOSPI")
    c2 = Candidate(ticker="000003", name="테마사", company_id=3, track="theme", market="KOSDAQ",
                   stage=2)
    packed = pack_evaluator_context(NEWS, [ROOT], PLAN, [c1, c2])
    line1 = next(line for line in packed.prompt.splitlines() if line.startswith("[후보 c01]"))
    line2 = next(line for line in packed.prompt.splitlines() if line.startswith("[후보 c02]"))
    assert "차 파급" not in line1
    assert "2차 파급" in line2


def test_plan_block_renders_axes_as_their_own_labeled_lines():
    """수요 이동·확정성은 별도 줄 — 프롬프트가 라벨로 지목해 규칙을 건다."""
    prompt = pack_supply_filter_context(PLAN_WITH_AXES, [])
    lines = prompt.splitlines()
    assert any(line.startswith("[수요 이동] 증설 지출은") for line in lines)
    assert any(line.startswith("[확정성] MOU 단계다.") for line in lines)


def test_plan_block_omits_axes_when_planner_left_them_empty():
    lines = pack_supply_filter_context(PLAN, []).splitlines()
    assert not any(line.startswith("[수요 이동]") or line.startswith("[확정성]")
                   for line in lines)
