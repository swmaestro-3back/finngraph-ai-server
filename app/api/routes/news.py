import logging

from fastapi import APIRouter, HTTPException, Query

import crud
from schemas import NewsGraphResponse

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)


@router.get("/news/{news_id}/graph", response_model=NewsGraphResponse)
async def get_news_graph(
    news_id: str,
    hop: int = Query(1, ge=1, le=3),
) -> NewsGraphResponse:

    graph = await crud.get_news_graph(news_id, hop)
    if graph is None:
        logger.info("News not found: %s", news_id)
        raise HTTPException(status_code=404, detail=f"News not found: {news_id}")
    return graph
