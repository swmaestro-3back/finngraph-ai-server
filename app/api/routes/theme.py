import logging

from fastapi import APIRouter, HTTPException

import crud
from schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["theme"])
logger = logging.getLogger(__name__)


@router.get("/theme/{name}", response_model=GraphResponse)
async def get_theme(name: str) -> GraphResponse:
    """해당 테마 노드 + BELONGS_TO로 연결된 Stock 목록을 반환한다."""
    graph = await crud.get_theme_graph(name)
    if graph is None:
        logger.info("Theme not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Theme not found: {name}")
    return graph
