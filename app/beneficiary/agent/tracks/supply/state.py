from __future__ import annotations

from typing import TypedDict

from beneficiary.models import (
    NewsContext,
    NewsPlan,
    RelationLine,
    RootCompany,
    SupplyChainCandidate,
    TrackOutcome,
)


class SupplyTrackState(TypedDict, total=False):
    # 입력 (래퍼가 주입)
    news: NewsContext
    plan: NewsPlan
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]

    edges: list[SupplyChainCandidate]
    strong_ids: list[str]  # 관측 전용 — 부모로 올라가지 않는다
    weak_ids: list[str]
    outcome: TrackOutcome
