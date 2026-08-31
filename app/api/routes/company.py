import logging

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph import repository
from knowledge_graph.schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["Companies"])
logger = logging.getLogger(__name__)


@router.get("/companies/{ticker}", response_model=GraphResponse)
async def get_company(
    ticker: str,
    hop: int = Query(1, ge=1, le=3),
) -> GraphResponse:
    """
    특정 ticker값에 해당하는 기업에 대한 hop 내 모든 node와 relationship을 subgraph로 반환한다.
    hop에 대한 기본값은 1이고, 최대 3까지 지정가능하다.
    """
    graph = await repository.get_company_graph(ticker, hop)
    if graph is None:
        logger.info("Company not found: %s", ticker)
        raise HTTPException(status_code=404, detail=f"Company not found: {ticker}")
    return graph
