"""beneficiary 서비스 — 뉴스 해석 → 워크플로우 실행 → 응답 조립.

응답 캐시는 없다 — 매 호출 재계산한다(관측·회귀 확인은 LangSmith 트레이스로).
"""

from __future__ import annotations

import logging
import time

from graph import repository
from graph.api_models import BeneficiaryItemOut, BeneficiaryResponse, EvidenceOut
from graph.models import NewsContext, RankedItem
from graph.prompts import DISCLAIMER, PROMPT_VERSION
from graph.state import GraphState
from graph.workflow import beneficiary_graph
from core import postgres_database

logger = logging.getLogger(__name__)


class NewsNotFoundError(Exception):
    pass


class BeneficiaryGenerationError(Exception):
    pass


async def get_news_beneficiaries(news_id: int) -> BeneficiaryResponse:
    async with postgres_database.connection() as conn:
        resolved = await repository.resolve_news_with_link(conn, news_id)
        if resolved is None:
            raise NewsNotFoundError(f"news not found: {news_id}")
        rep_news_id = resolved["rep_news_id"]

    started = time.monotonic()
    news = NewsContext(
        title=resolved["title"] or "",
        summary=resolved["summary"],
        published_at=str(resolved["published_at"]) if resolved["published_at"] else None,
        link=resolved["link"],
    )

    state: GraphState = await beneficiary_graph.ainvoke(
        {"rep_news_id": rep_news_id, "news": news}
    )

    if state.get("error"):
        # 인프라 장애를 "후보 없음" 으로 둔갑시키지 않는다 — 503, 비캐시.
        raise BeneficiaryGenerationError(f"beneficiary 에이전트 실패: {state['error']}")

    items = state.get("items", [])
    status = "ok" if items else "no_candidates"
    logger.info(
        "수혜주 생성: %.1fs (풀 %d → 추천 %d, status=%s)",
        time.monotonic() - started, state.get("pool_size", 0), len(items), status,
    )

    return BeneficiaryResponse(
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


def _item_out(item: RankedItem) -> BeneficiaryItemOut:
    candidate = item.candidate
    return BeneficiaryItemOut(
        ticker=candidate.ticker,
        name=candidate.name,
        market=candidate.market,
        track=candidate.track,
        matched_items=candidate.matched_items,
        via_themes=candidate.via_themes,
        impact=item.impact,
        confidence=item.confidence,
        rationale=item.rationale,
        caveats=item.caveats,
        evidence=[
            EvidenceOut(type=e.type, text=e.text, date=e.date, link=e.link)
            for e in _selected_evidence(item)
        ],
        rank=item.rank,
    )
