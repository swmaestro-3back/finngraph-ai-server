"""langgraph workflow에서 사용될 GraphState 정의.

supply_chain 에이전트 하나뿐이라 상태도 하나다:
입력(rep_news_id, news) → collect_supply 가 채우는 내부 키(anchors,
candidates) → supply_judge 가 채우는 산출 키(items, pool_size, ...).
"""

from __future__ import annotations

from typing import TypedDict

from graph.models import Anchor, Candidate, NewsContext, RankedItem


class GraphState(TypedDict, total=False):
    # 입력
    rep_news_id: int
    news: NewsContext

    # collect_supply 산출
    anchors: list[Anchor]
    candidates: list[Candidate]  # SUPPLIES_TO 1-hop 중 공시 수 상위 3개 (재무 포함)

    # supply_judge 산출
    items: list[RankedItem]
    pool_size: int
    event_interpretation: str | None
    raw: dict | None
    error: str | None
