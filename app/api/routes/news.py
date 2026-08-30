import logging

from fastapi import APIRouter, HTTPException  # noqa: F401 — Task 15 의 라우트가 사용

router = APIRouter(prefix="/api/v1", tags=["News"])
logger = logging.getLogger(__name__)
