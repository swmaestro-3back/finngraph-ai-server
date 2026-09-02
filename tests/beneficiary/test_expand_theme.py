"""theme 트랙 순수 로직 — 병합·정렬·절단 (DB·LLM 없음)."""

from __future__ import annotations

from beneficiary.models import ScenarioProbe, ThemeCandidate
from beneficiary.agent.subgraphs.theme.nodes import (
    MATCHED_REASONS_CAP,
    MATCHED_THEMES_CAP,
    THEME_POOL_CAP,
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


def test_matched_themes_and_reasons_capped_across_probes():
    # 티커 하나에 캡을 넘는 서로 다른 테마·사유를 여러 probe 에 걸쳐 공급한다.
    p1_rows = [_row("005930", theme=f"테마{i}", reason=f"사유{i}", score=0.9) for i in range(3)]
    p2_rows = [_row("005930", theme=f"테마{i}", reason=f"사유{i}", score=0.8) for i in range(3, 7)]
    merged = merge_theme_rows([(P1, p1_rows), (P2, p2_rows)])

    assert len(merged) == 1
    hit = merged[0]
    assert len(hit.matched_themes) == MATCHED_THEMES_CAP
    assert len(hit.matched_reasons) == MATCHED_REASONS_CAP


def test_pool_cap_truncation_keeps_sort_selected_survivors_and_assigns_tids_after_cut():
    total = THEME_POOL_CAP + 5
    # 인덱스가 클수록 점수가 높다 — 정렬 전에 원본 순서로 앞 60개를 잘랐다면
    # 정확히 반대(가장 낮은 점수 60개)가 살아남는다.
    hits = [
        ThemeCandidate(
            tid=None, stage=1, hypothesis="가설", ticker=f"{i:06d}", name="회사",
            company_id=1, market="KOSPI", score=float(i),
        )
        for i in range(total)
    ]
    ordered = truncate_and_assign_tids(hits)

    assert len(ordered) == THEME_POOL_CAP
    assert ordered[0].tid == "t01"
    assert ordered[-1].tid == f"t{THEME_POOL_CAP:02d}"

    survivor_tickers = {h.ticker for h in ordered}
    expected_survivors = {f"{i:06d}" for i in range(total - THEME_POOL_CAP, total)}
    assert survivor_tickers == expected_survivors
