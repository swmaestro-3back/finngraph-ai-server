import logging

from fastapi import APIRouter, HTTPException

import crud
from schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["stock"])
logger = logging.getLogger(__name__)


@router.get("/stock/{ticker}", response_model=GraphResponse)
async def get_stock(ticker: str) -> GraphResponse:
    """해당 티커 Stock 기준 3홉 내 모든 노드/관계(subgraph)를 반환한다."""
    graph = await crud.get_stock_graph(ticker)
    if graph is None:
        logger.info("Stock not found: %s", ticker)
        raise HTTPException(status_code=404, detail=f"Stock not found: {ticker}")
    return graph
