import logging

from fastapi import APIRouter, HTTPException

from knowledge_graph import repository
from knowledge_graph.schemas import RelationshipDetail

router = APIRouter(prefix="/api/v1", tags=["Relationships"])
logger = logging.getLogger(__name__)


@router.get("/relationships/{element_id:path}", response_model=RelationshipDetail)
async def get_relationship(element_id: str) -> RelationshipDetail:
    """특정 간선에 대한 정보를 조회한다.

    element_id로는 subgraph 응답의 relationships[].id 값을 그대로 사용한다.
    (`4:uuid:12` 형태라 콜론이 들어가므로 path 변환자를 쓴다.)
    """
    detail = await repository.get_relationship_detail(element_id)
    if detail is None:
        logger.info("Relationship not found: %s", element_id)
        raise HTTPException(status_code=404, detail=f"Relationship not found: {element_id}")
    return detail
