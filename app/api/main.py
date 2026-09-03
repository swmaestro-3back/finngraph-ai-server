from fastapi import APIRouter

from api.routes import company, theme

api_router = APIRouter()

api_router.include_router(company.router)
api_router.include_router(theme.router)
