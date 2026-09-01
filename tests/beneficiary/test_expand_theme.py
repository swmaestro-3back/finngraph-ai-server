"""theme 트랙 순수 로직 — 병합·정렬·절단 (DB·LLM 없음)."""

from __future__ import annotations

from beneficiary.models import ScenarioProbe
from beneficiary.agent.tracks.theme.nodes import (
    merge_theme_rows,
    truncate_and_assign_tids,
)

P1 = ScenarioProbe(stage=1, hypothesis="전력망 증설로 변압기 수요", query="변압기")
P2 = ScenarioProbe(stage=2, hypothesis="변압기 증산으로 규소강판 수요", query="규소강판")


def _row(ticker, name="회사", theme="테마A", reason="사유", score=0.9, market="KOSPI"):
    return {"ticker": ticker, "name": name, "company_id": 1, "market": market,
            "theme_name": theme, "reason": reason, "score": score}


def test_merge_folds_by_ticker_and_keeps_best_scoring_probe():
    merged = merge_theme_rows([
        (P2, [_row("005930", theme="테마B", reason="r2", score=0.85)]),
        (P1, [_row("005930", theme="테마A", reason="r1", score=0.92)]),
    ])
    assert len(merged) == 1
    hit = merged[0]
    assert hit.score == 0.92
    assert hit.stage == 1 and hit.hypothesis == P1.hypothesis   # 최고 점수 probe 승계
    assert set(hit.matched_themes) == {"테마B", "테마A"}   # 테마명 원문 — 대괄호는 reason 에만


def test_merge_prefers_lower_stage_on_score_tie():
    merged = merge_theme_rows([
        (P2, [_row("005930", score=0.90)]),
        (P1, [_row("005930", score=0.90)]),
    ])
    assert merged[0].stage == 1


def test_reason_text_preserves_theme_attribution():
    merged = merge_theme_rows([(P1, [_row("005930", theme="전력설비", reason="변압기 주력")])])
    assert merged[0].matched_reasons == ["[전력설비] 변압기 주력"]


def test_truncate_sorts_stage_first_then_score_then_ticker():
    hits = merge_theme_rows([
        (P2, [_row("000100", score=0.99)]),
        (P1, [_row("000300", score=0.70)]),
        (P1, [_row("000200", score=0.70)]),
    ])
    ordered = truncate_and_assign_tids(hits)
    assert [h.ticker for h in ordered] == ["000200", "000300", "000100"]
    assert [h.tid for h in ordered] == ["t01", "t02", "t03"]
