"""이슈 인사이트 서비스 — 뉴스 해석 → 워크플로우 실행 → 응답 조립.

생성 자체는 LangGraph 워크플로우(graph/workflow.py)가 수행한다:
START → collect_supply → supply_judge (supply_chain 단일 에이전트).

저장·캐시는 하지 않는다 — 실행 관측은 LangSmith 트레이싱으로 확인한다.
"""

from __future__ import annotations

import logging
import time

from core import postgres_database
from graph.models import NewsContext, RankedItem
from graph.prompts import DISCLAIMER, PROMPT_VERSION
from graph.state import GraphState
from graph.workflow import insight_graph
from insights import repository
from insights.models import (
    EvidenceOut,
    InsightItemOut,
    InsightResponse,
)

logger = logging.getLogger(__name__)


class NewsNotFoundError(Exception):
    pass


class InsightGenerationError(Exception):
    pass


async def get_news_insights(news_id: int) -> InsightResponse:
    async with postgres_database.connection() as conn:
        resolved = await repository.resolve_news(conn, news_id)
    if resolved is None:
        raise NewsNotFoundError(f"news not found: {news_id}")
    rep_news_id = resolved["rep_news_id"]

    started = time.monotonic()
    news = NewsContext(
        title=resolved["title"] or "",
        summary=resolved["summary"],
        published_at=str(resolved["published_at"]) if resolved["published_at"] else None,
    )

    state: GraphState = await insight_graph.ainvoke({"rep_news_id": rep_news_id, "news": news})

    if state.get("error"):
        raise InsightGenerationError(f"supply_chain 에이전트 실패: {state['error']}")

    items = state.get("items", [])
    logger.info(
        "인사이트 생성: %.1fs (공급망 후보 %d → 추천 %d개)",
        time.monotonic() - started,
        state.get("pool_size", 0),
        len(items),
    )

    status = "no_candidates" if not state.get("pool_size") else "ok"
    return InsightResponse(
        news_id=news_id,
        rep_news_id=rep_news_id,
        status=status,
        event_interpretation=state.get("event_interpretation"),
        items=[_item_out(item) for item in items],
        prompt_version=PROMPT_VERSION,
        disclaimer=DISCLAIMER,
    )


# ── 응답 조립 ────────────────────────────────────────────────────────────────


def _selected_evidence(item: RankedItem):
    by_eid = {evidence.eid: evidence for evidence in item.candidate.evidence}
    return [by_eid[eid] for eid in item.evidence_ids if eid in by_eid]


def _item_out(item: RankedItem) -> InsightItemOut:
    return InsightItemOut(
        ticker=item.candidate.ticker,
        name=item.candidate.name,
        impact=item.impact,
        confidence=item.confidence,
        path_type=["supply_chain"],
        themes=[],
        rationale=item.rationale,
        caveats=item.caveats,
        evidence=[
            EvidenceOut(type=e.type, text=e.text, date=e.date, link=e.link)
            for e in _selected_evidence(item)
        ],
        rank=item.rank,
    )
