import logging

from fastapi import APIRouter, HTTPException, Query

import crud
from schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["Products"])
logger = logging.getLogger(__name__)


@router.get("/products/{name}", response_model=GraphResponse)
async def get_product(
    name: str,
    hop: int = Query(1, ge=1, le=3),
) -> GraphResponse:
    """
    특정 제품(2차 상품, 중간재, 완제품 등)에 대한 hop 내 모든 node와 relationship을 subgraph로 반환한다.
    hop에 대한 기본값은 1이고, 최대 3까지 지정가능하다.
    """
    graph = await crud.get_product_graph(name, hop)
    if graph is None:
        logger.info("Product not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Product not found: {name}")
    return graph
