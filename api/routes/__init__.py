from fastapi import APIRouter

from api.routes.internal import router as internal_router
from api.routes.meta import router as meta_router
from api.routes.v2 import router as v2_router

router = APIRouter()
router.include_router(meta_router)
router.include_router(internal_router)
router.include_router(v2_router)

__all__ = ["router"]
