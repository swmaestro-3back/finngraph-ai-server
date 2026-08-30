"""beneficiary 워크플로우의 GraphState.

strong_ids/weak_ids 는 관측·테스트 전용 요약(LangSmith 트레이스 가독성)이다 —
분류의 원천은 후보 객체의 relevance 이며 다운스트림 로직은 이 키를 읽지 않는다.
edges/rivals 는 실행 경로(극성 트랙)당 한쪽만 채워진다.
"""

from __future__ import annotations

from typing import TypedDict

from graph.models import (
    RootCompany,
    Candidate,
    SupplyChainCandidate,
    NewsContext,
    NewsPlan,
    RankedItem,
    RelationLine,
    RivalCandidate,
)


class GraphState(TypedDict, total=False):
    # 입력 (service 주입)
    rep_news_id: int
    news: NewsContext

    # analyze_news
    # root_companies 는 상장 국내 루트 기업만 — 이관된 repository.fetch_root_companies 행(dict)을
    # analyze_news 가 필터·변환해 RootCompany(전 필드 확정)로 넣는다.
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]
    plan: NewsPlan | None
    plan_fallback: bool
    probe_fallback: bool

    # 트랙별 원시 후보
    edges: list[SupplyChainCandidate]
    rivals: list[RivalCandidate]

    # filter_*
    strong_ids: list[str]
    weak_ids: list[str]
    filter_fallback: bool

    # select_candidates
    candidates: list[Candidate]

    # judge
    items: list[RankedItem]
    pool_size: int
    event_interpretation: str | None
    error: str | None
