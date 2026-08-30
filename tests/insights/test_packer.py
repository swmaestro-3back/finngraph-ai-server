"""컨텍스트 패킹(후보 카드·재무 테이블 렌더링, id 부여) 테스트."""

from __future__ import annotations

from graph.models import Anchor, Candidate, Evidence, NewsContext
from graph.utils.packer import pack_judge_context

NEWS = NewsContext(title="삼성전자 HBM 공급 확대", summary="요약문", published_at="2026-08-27")
ANCHOR = Anchor(company_id=1, name="삼성전자", ticker="005930", description="반도체 제조")


def _candidates() -> list[Candidate]:
    return [
        Candidate(
            ticker="000660",
            name="SK하이닉스",
            company_id=2,
            relation_lines=["삼성전자 → SUPPLIES_TO → SK하이닉스"],
            evidence=[
                Evidence(type="disclosure", text="단일판매공급계약: HBM3E", date="2026-07-12"),
                Evidence(type="news", text="엔비디아에 HBM 공급 확대", date="2026-08-01"),
            ],
            disclosure_count=5,
            market="KOSPI",
            market_cap=190_000_000_000_000,
            financials=[
                {
                    "fiscal_yymm": "202512",
                    "revenue": 66_000_000_000_000,
                    "operating_income": 23_000_000_000_000,
                    "net_income": 19_000_000_000_000,
                    "roe": 28.1,
                    "eps": 27000.0,
                    "total_equity": 80_000_000_000_000,
                    "debt_ratio": 32.5,
                }
            ],
            valuation={"trade_date": "2026-08-26", "per": 8.4, "pbr": 2.1, "market_cap": 190_000_000_000_000},
        ),
        Candidate(
            ticker="373220",
            name="LG에너지솔루션",
            company_id=3,
            relation_lines=["LG에너지솔루션 → SUPPLIES_TO → 삼성전자"],
            evidence=[Evidence(type="news", text="배터리 셀 공급 계약")],
            disclosure_count=1,
        ),
    ]


def test_assigns_sequential_cids_and_unique_eids():
    packed = pack_judge_context(NEWS, [ANCHOR], candidates=_candidates())

    assert list(packed.by_cid.keys()) == ["c01", "c02"]
    assert packed.by_cid["c01"].ticker == "000660"
    # 근거 id 는 후보를 가로질러 유일하고 연속이다
    assert packed.known_eids == {"e01", "e02", "e03"}
    assert [e.eid for e in packed.by_cid["c02"].evidence] == ["e03"]


def test_judge_prompt_renders_cards_with_ids_evidence_and_financials():
    packed = pack_judge_context(NEWS, [ANCHOR], candidates=_candidates())

    assert "삼성전자 HBM 공급 확대" in packed.prompt
    assert (
        "[후보 c01] SK하이닉스 (000660, KOSPI) — 시총 190,000,000,000,000 / 공시 5건"
        in packed.prompt
    )
    # 시장 정보가 없는 후보는 명시적으로 표시된다
    assert "(373220, 시장 미상) — 시총 -" in packed.prompt
    assert "[e01] (disclosure 2026-07-12) 단일판매공급계약: HBM3E" in packed.prompt
    # 재무 테이블: 헤더 + 연도 행 + 밸류에이션
    assert "매출액 | 영업이익" in packed.prompt
    assert "202512" in packed.prompt
    assert "PER 8.4" in packed.prompt
    # 재무 데이터가 없는 후보는 명시적으로 표시된다
    assert "[재무] (데이터 없음)" in packed.prompt
