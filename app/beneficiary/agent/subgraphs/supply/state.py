from __future__ import annotations

from typing import TypedDict

from beneficiary.models import (
    NewsContext,
    NewsPlan,
    RelationLine,
    RootCompany,
    SupplyCandidate,
    SupplyEdgeCandidate,
    SubgraphResult,
)


class SupplyTrackState(TypedDict, total=False):
    news: NewsContext
    plan: NewsPlan
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]

    edges: list[SupplyEdgeCandidate]    # 공급망 간선 후보
    candidates: list[SupplyCandidate]   # 공급망 기업 후보
    strong_ids: list[str]
    weak_ids: list[str]
    outcome: SubgraphResult
