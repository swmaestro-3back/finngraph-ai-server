from fastapi import APIRouter

from api.routes import commodity, product, relationship, stock, theme

api_router = APIRouter()

api_router.include_router(stock.router)
api_router.include_router(theme.router)
api_router.include_router(product.router)
api_router.include_router(commodity.router)
api_router.include_router(relationship.router)