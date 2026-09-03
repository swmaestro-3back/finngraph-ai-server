import logging

from fastapi import APIRouter, HTTPException, Query

import repository
from enums import Market, MarketIndex
from schemas import SupplyChainResponse

router = APIRouter(prefix="/api/v1", tags=["Companies"])
logger = logging.getLogger(__name__)


@router.get("/companies/{ticker}/supplychain", response_model=SupplyChainResponse)
async def get_company_supplychain(
    ticker: str,
    hop: int = Query(1, ge=1, le=3),
    market: Market | None = Query(None, description="해당 시장에 상장된 기업으로만 경로를 제한한다."),
    index: MarketIndex | None = Query(None, description="해당 지수 구성종목으로만 경로를 제한한다."),
) -> SupplyChainResponse:
    """특정 기업을 중심으로 hop 이내의 공급망을 조회한다."""
    if market is not None and index is not None:
        raise HTTPException(status_code=400, detail="market과 index는 함께 사용할 수 없습니다.")

    supplychain = await repository.get_company_supplychain(ticker, hop, market, index)
    if supplychain is None:
        logger.info("Company not found: %s", ticker)
        raise HTTPException(status_code=404, detail=f"Company not found: {ticker}")
    return supplychain
