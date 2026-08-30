"""beneficiary 서비스 — 뉴스 해석 → 캐시 조회 → 워크플로우 실행 → 저장·응답.

캐시 저장 조건(스펙 §7): status == "ok" 이고 폴백 플래그가 없으며 items 가
비어 있지 않은 응답만 저장한다. no_candidates 는 ETL 원장 적재 지연 레이스로도
발생하므로 영구 캐시 금지 — 재계산은 싸다. 무효화는 prompt_version 인상뿐.
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
        cached = await repository.fetch_cached_payload(conn, rep_news_id, PROMPT_VERSION)

    if cached is not None:
        # payload 의 news_id 는 최초 요청자의 값이라 현재 요청 값으로 교체한다.
        return BeneficiaryResponse.model_validate(cached).model_copy(
            update={"news_id": news_id}
        )

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

    response = BeneficiaryResponse(
        news_id=news_id,
        rep_news_id=rep_news_id,
        status=status,
        event_interpretation=state.get("event_interpretation"),
        items=[_item_out(item) for item in items],
        prompt_version=PROMPT_VERSION,
        disclaimer=DISCLAIMER,
    )

    fallback = bool(
        state.get("plan_fallback") or state.get("probe_fallback") or state.get("filter_fallback")
    )
    if status == "ok" and not fallback and response.items:
        async with postgres_database.connection() as conn:
            await repository.store_payload(
                conn, rep_news_id, PROMPT_VERSION, response.model_dump(mode="json")
            )
    return response


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
