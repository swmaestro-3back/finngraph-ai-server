from fastapi import APIRouter

from api.routes import news, relationship, stock, theme

api_router = APIRouter()

api_router.include_router(stock.router)
api_router.include_router(theme.router)
api_router.include_router(relationship.router)
api_router.include_router(news.router)
