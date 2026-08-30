"""패킹 형식·cid/eid 부여 규칙 테스트 — 형식 변경 시 PROMPT_VERSION 인상 필요."""

from __future__ import annotations

from beneficiary.models import (
    RootCompany,
    Candidate,
    SupplyChainCandidate,
    Evidence,
    NewsContext,
    NewsPlan,
    RelationLine,
    RivalCandidate,
)
from beneficiary.utils.packer import (
    pack_judge_context,
    pack_plan_context,
    pack_rival_filter_context,
    pack_supply_filter_context,
)

NEWS = NewsContext(title="타이틀", summary="요약", published_at="2026-08-30", link="https://n.example/1")
ROOT = RootCompany(company_id=1, name="루트기업", ticker="000001", description="설명")
PLAN = NewsPlan(event_summary="사건", polarity="positive", core_items=["HBM"])


def _edge(gid="g01", items=("HBM",)):
    return SupplyChainCandidate(gid=gid, root_name="루트기업", subject_name="공급사", object_name="루트기업",
                         ticker="000002", name="공급사", company_id=2, market="KOSPI",
                         disclosure_items=list(items), news_items=[], disclosure_count=2,
                         news_mention_count=5)


def test_pack_plan_context_lists_root_companies_themes_and_relations():
    lines = [RelationLine(subject_name="루트기업", subject_code="000001", relation="SUPPLIES_TO",
                          object_name="상대기업", object_code="000009", item="HBM",
                          polarity="affirmed", subject_impact="negative", object_impact="neutral")]
    themes = {"루트기업": [{"name": "테마A", "description": "설명A", "member_count": 2}]}
    prompt = pack_plan_context(NEWS, [ROOT], lines, themes)
    assert "타이틀" in prompt and "루트기업" in prompt
    assert "테마A" in prompt and "SUPPLIES_TO" in prompt and "affirmed" in prompt


def test_pack_supply_filter_lines_show_items_or_placeholder():
    prompt = pack_supply_filter_context(PLAN, [_edge(), _edge(gid="g02", items=())])
    assert "[g01]" in prompt and "HBM" in prompt and "공시2·뉴스5" in prompt
    assert "items: (없음)" in prompt  # 빈 아이템 간선 표기


def test_pack_rival_filter_cards():
    rival = RivalCandidate(kid="k01", subject_name="루트기업", ticker="000003", name="경쟁사",
                           company_id=3, market="KOSPI", shared_themes=2,
                           via_themes=["테마A", "테마B"], reasons=["대체 생산"],
                           supplied_items=["HBM2"])
    empty = RivalCandidate(kid="k02", subject_name="루트기업", ticker="000004", name="무보", company_id=4)
    prompt = pack_rival_filter_context(PLAN, [rival, empty])
    assert "[k01]" in prompt and "공유 테마 2" in prompt and "HBM2" in prompt and "대체 생산" in prompt
    assert "공급 아이템: (없음)" in prompt


def test_pack_judge_assigns_scoped_eids_and_marks_promotion():
    c1 = Candidate(ticker="000002", name="공급사", company_id=2, track="supply", market="KOSPI",
                   matched_items=["HBM"], relation_lines=["공급사 →공급→ 루트기업"],
                   evidence=[Evidence(type="disclosure", text="근거1", date="2026-08-01"),
                             Evidence(type="news", text="근거2", date="2026-08-02")])
    c2 = Candidate(ticker="000003", name="경쟁사", company_id=3, track="rival", market="KOSDAQ",
                   relevance="weak", promoted=True, via_themes=["테마A"],
                   evidence=[Evidence(type="news", text="트리거", link="https://n.example/1")])
    packed = pack_judge_context(NEWS, [ROOT], PLAN, [c1, c2], fallback_note="계획 폴백")
    assert list(packed.by_cid) == ["c01", "c02"]
    assert packed.eids_by_cid["c01"] == {"e01", "e02"}
    assert packed.eids_by_cid["c02"] == {"e03"}  # eid 는 전역 연번, 스코프는 후보별
    assert c1.cid == "c01" and c1.evidence[0].eid == "e01"
    assert "트랙 공급" in packed.prompt and "트랙 경쟁" in packed.prompt
    assert "weak(승격)" in packed.prompt and "계획 폴백" in packed.prompt
    assert "매칭 아이템: HBM" in packed.prompt
