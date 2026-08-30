import logging

from fastapi import APIRouter, HTTPException

from graph import service as beneficiary_service
from graph.api_models import BeneficiaryResponse

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)


@router.get("/news/{news_id}/beneficiaries", response_model=BeneficiaryResponse)
async def get_news_beneficiaries(news_id: int) -> BeneficiaryResponse:
    """
    뉴스 사건의 수혜 종목을 극성 2트랙(공급망/경쟁사)으로 추천한다.

    캐시 히트 시 수 ms, 미스 시 워크플로우 실행에 동기 대기한다(~20초).
    ok + 비폴백 + 추천 있음 응답만 news_beneficiaries 에 캐시된다.
    """
    try:
        return await beneficiary_service.get_news_beneficiaries(news_id)
    except beneficiary_service.NewsNotFoundError:
        logger.info("News not found: %s", news_id)
        raise HTTPException(status_code=404, detail=f"News not found: {news_id}")
    except beneficiary_service.BeneficiaryGenerationError:
        logger.exception("Beneficiary generation failed: news_id=%s", news_id)
        raise HTTPException(status_code=503, detail="Beneficiary generation failed. Retry later.")
