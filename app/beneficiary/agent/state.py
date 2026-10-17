"""beneficiary 워크플로우의 GraphState.

strong_ids/weak_ids 는 트랙 내부 관측용(LangSmith 트레이스 가독성) 요약이다 —
분류의 원천은 후보 객체의 relevance 이며, 각 트랙 서브그래프 자체 state 에만
있고 이 부모 state 에는 올라오지 않는다.

종료 신호는 둘뿐이다 — error 는 장애(→ 503), status 는 정상 종료다. 노드는
더 진행할 수 없다고 판단하면 그 자리에서 status·reason 을 넣고 반환하고,
라우터는 그걸 보고 END 로 보낸다. 대체값을 지어내는 폴백은 없다.
"""

from __future__ import annotations

from typing import TypedDict

from beneficiary.models import (
    RootCompany,
    Candidate,
    NewsContext,
    NewsPlan,
    RankedItem,
    RelationLine,
    SupplySubgraphResult,
    ThemeSubgraphResult,
)


class GraphState(TypedDict, total=False):
    # Initial Inputs
    rep_news_id: int
    news: NewsContext

    # Planner
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]
    plan: NewsPlan | None

    # Subgraph Results
    supply_result: SupplySubgraphResult | None
    theme_result: ThemeSubgraphResult | None

    # candidate_selector
    candidates: list[Candidate]

    # evaluator
    items: list[RankedItem]
    event_interpretation: str | None
    analysis_note: str | None  # 한 탐색 축이 비었거나 실패했을 때의 분석 성격

    # 종료 신호 — status 는 ok | not_positive | no_root_companies | no_pool |
    # no_candidates | no_beneficiaries, reason 은 그 사유를 설명하는 사용자용 한 문장이다.
    status: str
    reason: str | None
    error: str | None
