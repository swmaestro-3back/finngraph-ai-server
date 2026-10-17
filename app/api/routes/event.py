import logging

import psycopg
from fastapi import APIRouter, HTTPException, Query

import repository
from schemas import EventDetailResponse

router = APIRouter(prefix="/api/v1", tags=["Events"])
logger = logging.getLogger(__name__)


@router.get("/events/{cluster_id}", response_model=EventDetailResponse)
async def get_event_detail(
    cluster_id: int,
    limit: int = Query(20, ge=1, le=50, description="돌려줄 최신 기사 수"),
) -> EventDetailResponse:
    """이벤트(뉴스 클러스터)의 키워드·기사·관련 기업. cluster_id 는 그래프 이벤트 노드의 cluster_id 다."""
    try:
        detail = await repository.get_event_detail(cluster_id, limit)
    except psycopg.Error:
        logger.exception("Event lookup failed: %s", cluster_id)
        raise HTTPException(status_code=503, detail="Event lookup failed. Retry later.")
    if detail is None:
        logger.info("Event not found: %s", cluster_id)
        raise HTTPException(status_code=404, detail=f"Event not found: {cluster_id}")
    return detail
