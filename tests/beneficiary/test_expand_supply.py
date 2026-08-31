"""expand_supply 순수 로직 — 중복 제거·절단 타이브레이커·gid 부여 (DB 없음)."""

from __future__ import annotations

from beneficiary.agent.tracks.supply.nodes import SUPPLY_POOL_CAP, build_edge_candidates, truncate_and_assign_gids


def _row(subject, obj="루트 기업", ticker="000002", dc=1, nc=0):
    return {"ticker": ticker, "name": subject, "company_id": 1, "market": "KOSPI",
            "subject_name": subject,
            "object_name": obj, "disclosure_count": dc, "news_mention_count": nc,
            "disclosure_items": ["HBM"], "news_items": [], "last_mentioned_at": None}


def test_build_dedupes_same_edge_and_keeps_root_index():
    edges = build_edge_candidates([
        (0, "루트 기업", [_row("공급사A", ticker="000002"), _row("공급사A", ticker="000002")]),
        (1, "부루트 기업", [_row("공급사B", obj="부루트 기업", ticker="000003")]),
    ])
    assert [(e.subject_name, e.object_name, e.root_index) for e in edges] == [
        ("공급사A", "루트 기업", 0), ("공급사B", "부루트 기업", 1),
    ]


def test_gid_order_is_root_then_count_desc_then_ticker():
    edges = build_edge_candidates([
        (0, "루트 기업", [_row("공급사B", ticker="000003", dc=1),
                     _row("공급사A", ticker="000002", dc=5),
                     _row("공급사C", ticker="000001", dc=1)]),  # dc 동점 → ticker asc
        (1, "부루트 기업", [_row("공급사D", obj="부루트 기업", ticker="000009", dc=9)]),
    ])
    ordered = truncate_and_assign_gids(edges)
    assert [(e.gid, e.subject_name) for e in ordered] == [
        ("g01", "공급사A"), ("g02", "공급사C"), ("g03", "공급사B"), ("g04", "공급사D"),
    ]


def test_truncation_evicts_lowest_count_sum():
    rows = [_row(f"공급사{i}", ticker=f"{i:06d}", dc=2) for i in range(SUPPLY_POOL_CAP)]
    rows.append(_row("영건공급사", ticker="999999", dc=0, nc=0))  # 유일한 합 0 간선
    ordered = truncate_and_assign_gids(build_edge_candidates([(0, "루트 기업", rows)]))
    assert len(ordered) == SUPPLY_POOL_CAP
    assert all(e.ticker != "999999" for e in ordered)  # 최저 합 간선이 밀려난다
    kept_sums = [e.disclosure_count + e.news_mention_count for e in ordered]
    assert min(kept_sums) == 2 and len({e.gid for e in ordered}) == SUPPLY_POOL_CAP
