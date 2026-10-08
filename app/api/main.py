from fastapi import APIRouter

from api.routes import company, news, relationship, theme

api_router = APIRouter()

api_router.include_router(company.router)
api_router.include_router(theme.router)
api_router.include_router(news.router)
api_router.include_router(relationship.router)
