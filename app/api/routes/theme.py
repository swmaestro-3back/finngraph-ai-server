import logging

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph import repository
from knowledge_graph.schemas import GraphResponse

router = APIRouter(prefix="/api/v1", tags=["Themes"])
logger = logging.getLogger(__name__)


@router.get("/themes/{name}", response_model=GraphResponse)
async def get_theme(
    name: str,
    hop: int = Query(1, ge=1, le=3),
) -> GraphResponse:
    """
    특정 테마에 속한 주식들을 반환한다.
    hop에 대한 기본값은 1(소속 주식만)이고, 최대 3까지 지정가능하다.
    hop이 2 이상이면 각 소속 주식에서 바깥으로 hop-1 만큼 더 확장한다.
    """
    graph = await repository.get_theme_graph(name, hop)
    if graph is None:
        logger.info("Theme not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Theme not found: {name}")
    return graph
