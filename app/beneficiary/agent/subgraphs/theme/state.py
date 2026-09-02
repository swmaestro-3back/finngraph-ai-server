from __future__ import annotations

from typing import TypedDict

from beneficiary.models import (
    NewsContext,
    NewsPlan,
    RelationLine,
    RootCompany,
    ThemeCandidate,
    SubgraphResult,
)


class ThemeTrackState(TypedDict, total=False):
    news: NewsContext
    plan: NewsPlan
    root_companies: list[RootCompany]
    relation_lines: list[RelationLine]

    hits: list[ThemeCandidate]
    strong_ids: list[str]  # 관측 전용 — 부모로 올라가지 않는다
    weak_ids: list[str]
    outcome: SubgraphResult
