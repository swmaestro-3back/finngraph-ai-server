"""트랙 공통 순수 유틸 — 제외 집합 유도.

제외 집합은 상태에 두지 않는다 — 각 expand 노드가 root_companies + relation_lines
에서 필요 시 유도한다(스펙 §4.1).
"""

from __future__ import annotations

from beneficiary.models import RootCompany, RelationLine


def derive_exclusions(
    root_companies: list[RootCompany], relation_lines: list[RelationLine]
) -> tuple[set[str], set[str]]:
    """뉴스 당사자 전원의 (names, tickers) — 후보에서 배제할 집합.

    subject ticker 는 fetch_root_companies 의 3단계 해석 결과(root.ticker),
    object ticker 는 원장 object_code 만 쓴다 — name 제외가 대부분을 커버한다.
    """

    names = {line.subject_name for line in relation_lines} | {
        line.object_name for line in relation_lines
    }
    names |= {root.name for root in root_companies}
    tickers = {root.ticker for root in root_companies if root.ticker} | {
        line.object_code for line in relation_lines if line.object_code
    }
    return names, tickers
