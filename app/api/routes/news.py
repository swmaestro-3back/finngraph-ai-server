import logging

from fastapi import APIRouter, HTTPException, Query

import repository
from beneficiary import service as beneficiary_service
from beneficiary.schemas import BeneficiaryResponse
from schemas import NewsGraphResponse

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)


@router.get("/news/{news_id}/graph", response_model=NewsGraphResponse)
async def get_news_graph(
    news_id: str,
    hop: int = Query(1, ge=1, le=3),
) -> NewsGraphResponse:
    """뉴스 한 건을 근거로 추출된 기업 간 관계(시드)와, hop ≥ 2 이면 그 기업들에서 기업 간 관계를 따라 펼친 서브그래프.

    테마·이벤트는 포함하지 않는다. 확장은 기업마다 근거가 많은 이웃 순으로 상한을 두고,
    전체 노드 상한에 걸리면 truncated=true 로 알린다. 응답의 seed_* 로 기사에서 온 것과 확장을 구분한다.
    """
    graph = await repository.get_news_graph(news_id, hop)
    if graph is None:
        logger.info("No relationships for news: %s", news_id)
        raise HTTPException(status_code=404, detail=f"News graph not found: {news_id}")
    return graph


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
