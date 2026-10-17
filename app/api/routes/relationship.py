import logging

import psycopg
from fastapi import APIRouter, HTTPException, Query

import repository
from schemas import RelationshipEvidenceResponse

router = APIRouter(prefix="/api/v1", tags=["Relationships"])
logger = logging.getLogger(__name__)


@router.get("/relationships/{element_id}/evidence", response_model=RelationshipEvidenceResponse)
async def get_relationship_evidence(
    element_id: str,
    limit: int = Query(20, ge=1, le=50, description="돌려줄 최신 기사 수"),
) -> RelationshipEvidenceResponse:
    """기업 간 관계(공급·인수·투자)의 근거 기사와 공시.

    element_id 는 그래프 응답의 관계 id(Neo4j elementId)다. 기사 제목·날짜는 Postgres 에서 읽는다.
    """
    try:
        evidence = await repository.get_relationship_evidence(element_id, limit)
    except psycopg.Error:
        logger.exception("Evidence lookup failed: %s", element_id)
        raise HTTPException(status_code=503, detail="Evidence lookup failed. Retry later.")
    if evidence is None:
        logger.info("Relationship not found: %s", element_id)
        raise HTTPException(status_code=404, detail=f"Relationship not found: {element_id}")
    return evidence
