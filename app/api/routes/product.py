import logging

from fastapi import APIRouter, HTTPException

import crud
from schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["product"])
logger = logging.getLogger(__name__)


@router.get("/product/{name}", response_model=GraphResponse)
async def get_product(name: str) -> GraphResponse:
    """해당 제품 기준 1홉 이웃 전체(subgraph)를 반환한다."""
    graph = await crud.get_product_graph(name)
    if graph is None:
        logger.info("Product not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Product not found: {name}")
    return graph
