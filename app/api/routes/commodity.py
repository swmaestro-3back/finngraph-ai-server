import logging

from fastapi import APIRouter, HTTPException

import crud
from schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["commodity"])
logger = logging.getLogger(__name__)


@router.get("/commodity/{name}", response_model=GraphResponse)
async def get_commodity(name: str) -> GraphResponse:
    """해당 원자재 기준 1홉 이웃 전체(subgraph)를 반환한다."""
    graph = await crud.get_commodity_graph(name)
    if graph is None:
        logger.info("Commodity not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Commodity not found: {name}")
    return graph
