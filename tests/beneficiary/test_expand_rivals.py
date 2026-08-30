"""expand_rivals 순수 로직 — probe 간 병합·상한·kid 부여 (DB 없음)."""

from __future__ import annotations

from beneficiary.nodes.rivals import (
    RIVAL_POOL_CAP,
    flatten_items,
    merge_rival_rows,
    truncate_and_assign_kids,
)


def _row(name, ticker, shared=1, via=("테마A",), reasons=("사유",), items=(["HBM"],)):
    return {"ticker": ticker, "name": name, "company_id": 1, "shared_themes": shared,
            "via_themes": list(via), "reasons": list(reasons), "item_arrays": list(items)}


def test_flatten_items_dedupes_and_caps_preserving_order():
    arrays = [["HBM", "DDR5"], None, ["HBM", "CXL"], [f"기타{i}" for i in range(20)]]
    flat = flatten_items(arrays, cap=10)
    assert flat[:3] == ["HBM", "DDR5", "CXL"] and len(flat) == 10


def test_merge_takes_max_shared_and_unions_with_caps():
    merged = merge_rival_rows([
        ("루트 기업1", [_row("경쟁사", "000003", shared=1, via=("테마A",), reasons=("사유1",))]),
        ("루트 기업2", [_row("경쟁사", "000003", shared=3,
                        via=("테마B", "테마C", "테마D", "테마E", "테마F"),
                        reasons=("사유2", "사유3", "사유4"))]),
    ])
    assert len(merged) == 1
    rival = merged[0]
    assert rival.shared_themes == 3
    assert rival.subject_name == "루트 기업2"  # 최대 shared 를 준 probe 의 루트 기업
    assert len(rival.via_themes) == 5  # 합집합 상한 5 (첫 등장 순서 유지)
    assert rival.via_themes[0] == "테마A"
    assert len(rival.reasons) == 3  # 합집합 상한 3
    assert rival.supplied_items == ["HBM"]


def test_kid_order_is_shared_desc_then_ticker_and_caps_at_60():
    # Fixture: tickers in reverse order within each shared_themes group
    # to ensure tie-break sorting is actually tested
    rows = [("루트 기업", [_row(f"경쟁{i}", f"{(RIVAL_POOL_CAP + 20 - i):06d}", shared=(i % 5) + 1)
                      for i in range(RIVAL_POOL_CAP + 20)])]
    rivals = truncate_and_assign_kids(merge_rival_rows(rows))
    assert len(rivals) == RIVAL_POOL_CAP
    assert rivals[0].kid == "k01"
    assert all(rivals[i].shared_themes >= rivals[i + 1].shared_themes
               for i in range(len(rivals) - 1))
    same = [r for r in rivals if r.shared_themes == 5]
    assert same == sorted(same, key=lambda r: r.ticker)  # 동점 ticker asc
