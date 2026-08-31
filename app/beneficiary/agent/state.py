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
    SupplyChainCandidate,
    NewsContext,
    NewsPlan,
    RankedItem,
    RelationLine,
    ThemeCandidate,
    TrackOutcome,
)


class GraphState(TypedDict, total=False):
    # 입력 (service 주입)
    rep_news_id: int
    news: NewsContext

    # planner
    # root_companies 는 상장 국내 루트 기업만 — repository.fetch_root_companies 행(dict)을
    # build_plan 이 필터·변환해 RootCompany(전 필드 확정)로 넣는다.
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]
    plan: NewsPlan | None

    # 트랙별 원시 후보 — 각 트랙 서브그래프만 자기 키를 쓴다(동시 쓰기 없음)
    edges: list[SupplyChainCandidate]
    theme_hits: list[ThemeCandidate]

    # 트랙 신호 — status/error 를 트랙 로컬로 담는다. 팬인에서 집계한다.
    supply_outcome: TrackOutcome | None
    theme_outcome: TrackOutcome | None

    # candidate_selector
    candidates: list[Candidate]

    # evaluator
    items: list[RankedItem]
    pool_size: int
    event_interpretation: str | None

    # 종료 신호 — status 는 ok | not_positive | no_root_companies | no_pool |
    # no_candidates | no_beneficiaries, reason 은 그 사유를 설명하는 사용자용 한 문장이다.
    status: str
    reason: str | None
    error: str | None
