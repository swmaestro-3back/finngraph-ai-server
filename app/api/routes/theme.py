import logging

from fastapi import APIRouter, HTTPException

import repository
from schemas import ThemeResponse

router = APIRouter(prefix="/api/v1", tags=["Themes"])
logger = logging.getLogger(__name__)


@router.get("/themes/{name:path}", response_model=ThemeResponse)
async def get_theme(name: str) -> ThemeResponse:
    """특정 테마에 대한 정보와 그 테마에 속한 기업(테마주)들을 조회한다."""
    theme = await repository.get_theme(name)
    if theme is None:
        logger.info("Theme not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Theme not found: {name}")
    return theme
