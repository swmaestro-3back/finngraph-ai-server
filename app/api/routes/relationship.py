import logging

from fastapi import APIRouter, HTTPException

import crud
from schemas import RelationshipDetail

router = APIRouter(prefix="/api/v1", tags=["relationship"])
logger = logging.getLogger(__name__)


@router.get("/relationship/{element_id:path}", response_model=RelationshipDetail)
async def get_relationship(element_id: str) -> RelationshipDetail:
    """간선 클릭 시 해당 관계의 full provenance를 지연 조회한다.

    element_id는 서브그래프 응답의 relationships[].id 값을 그대로 넘긴다.
    (`4:uuid:12` 형태라 콜론이 들어가므로 path 변환자를 쓴다.)
    """
    detail = await crud.get_relationship_detail(element_id)
    if detail is None:
        logger.info("Relationship not found: %s", element_id)
        raise HTTPException(status_code=404, detail=f"Relationship not found: {element_id}")
    return detail
