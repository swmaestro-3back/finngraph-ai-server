import logging

from fastapi import APIRouter, HTTPException

from insights import service
from insights.models import InsightResponse

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)


@router.get("/news/{news_id}/insights", response_model=InsightResponse)
async def get_news_insights(news_id: int) -> InsightResponse:
    """
    뉴스 사건이 수혜/피해를 줄 종목을 근거와 함께 반환한다.

    호출마다 워크플로우를 실행하고 생성까지 동기 대기한다(최악 ~15초).
    저장·캐시는 없다 — 실행 관측은 LangSmith 트레이싱으로 한다.
    """
    try:
        return await service.get_news_insights(news_id)
    except service.NewsNotFoundError:
        logger.info("News not found: %s", news_id)
        raise HTTPException(status_code=404, detail=f"News not found: {news_id}")
    except service.InsightGenerationError:
        logger.exception("Insight generation failed: news_id=%s", news_id)
        raise HTTPException(status_code=503, detail="Insight generation failed. Retry later.")
