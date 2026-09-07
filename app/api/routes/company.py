import logging

from fastapi import APIRouter, HTTPException, Query

import repository
from enums import Market, MarketIndex
from schemas import CompanyEventsResponse, CompanyResponse, SupplyChainResponse

router = APIRouter(prefix="/api/v1", tags=["Companies"])
logger = logging.getLogger(__name__)


@router.get("/companies/{ticker}", response_model=CompanyResponse)
async def get_company(ticker: str) -> CompanyResponse:
    """특정 기업과 1홉 관계에 있는 모든 간선과 연결된 노드(기업·테마·이벤트)를 조회한다."""
    company = await repository.get_company(ticker)
    if company is None:
        logger.info("Company not found: %s", ticker)
        raise HTTPException(status_code=404, detail=f"Company not found: {ticker}")
    return company


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


@router.get("/companies/{ticker}/events", response_model=CompanyEventsResponse)
async def get_company_events(
    ticker: str,
    hop: int = Query(1, ge=1, le=3),
) -> CompanyEventsResponse:
    """특정 기업을 중심으로 hop 이내의 이벤트 서브그래프를 조회한다.

    HAS_EVENT 간선을 방향 없이 따라가므로 홉마다 기업과 이벤트가 번갈아 나온다.
    hop=1 은 기업의 이벤트, hop=2 는 그 이벤트를 공유하는 다른 기업, hop=3 은 그 기업들의 이벤트까지 포함한다.
    """
    events = await repository.get_company_events(ticker, hop)
    if events is None:
        logger.info("Company not found: %s", ticker)
        raise HTTPException(status_code=404, detail=f"Company not found: {ticker}")
    return events
