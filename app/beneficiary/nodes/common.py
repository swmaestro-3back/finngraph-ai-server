"""트랙 공통 순수 유틸 — 시장 필터와 제외 집합 유도.

제외 집합은 상태에 두지 않는다 — 각 expand 노드가 root_companies + relation_lines
에서 필요 시 유도한다(스펙 §4.1).
"""

from __future__ import annotations

from beneficiary.models import RootCompany, RelationLine

MARKETS = ("KOSPI", "KOSDAQ")  # 추천 대상 시장 — 그 외(KONEX 등)는 제외


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


def apply_market_filter(candidates: list, market_rows: list[dict]) -> list:
    """market ∈ {KOSPI, KOSDAQ} 만 유지하고 시장·시총을 주입한다 (트랙 공통 규칙).

    fetch_market_info 결과에 없는 티커(비활성·미상장)는 제거. 입력 순서 보존.
    candidates 항목은 .ticker/.market/.market_cap 속성만 있으면 된다
    (SupplyChainCandidate·RivalCandidate 공용).
    """

    by_ticker = {row["ticker"]: row for row in market_rows}
    kept = []
    for candidate in candidates:
        info = by_ticker.get(candidate.ticker)
        if info is None or info["market"] not in MARKETS:
            continue
        candidate.market = info["market"]
        if info["market_cap"] is not None:
            candidate.market_cap = int(info["market_cap"])
        kept.append(candidate)
    return kept
