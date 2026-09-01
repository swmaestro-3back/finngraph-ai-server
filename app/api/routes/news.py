import logging

from fastapi import APIRouter, HTTPException

from beneficiary import service as beneficiary_service
from beneficiary.schemas import BeneficiaryResponse

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)


@router.get("/news/{news_id}/beneficiaries", response_model=BeneficiaryResponse)
async def get_news_beneficiaries(news_id: int) -> BeneficiaryResponse:
    """
    호재 뉴스의 수혜 종목을 병렬 2트랙(공급망 / 시나리오 테마)으로 추천한다.
    악재는 not_positive 로 정상 종료(200, 빈 목록)한다.

    캐시 없음 — 매 호출 워크플로우 실행에 동기 대기한다(~20초).
    """
    try:
        return await beneficiary_service.get_news_beneficiaries(news_id)
    except beneficiary_service.NewsNotFoundError:
        logger.info("News not found: %s", news_id)
        raise HTTPException(status_code=404, detail=f"News not found: {news_id}")
    except beneficiary_service.BeneficiaryGenerationError:
        logger.exception("Beneficiary generation failed: news_id=%s", news_id)
        raise HTTPException(status_code=503, detail="Beneficiary generation failed. Retry later.")
