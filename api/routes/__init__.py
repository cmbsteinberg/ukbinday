from fastapi import APIRouter

from api.routes.internal import router as internal_router
from api.routes.lookup import router as lookup_router
from api.routes.meta import router as meta_router

router = APIRouter()
router.include_router(lookup_router)
router.include_router(meta_router)
router.include_router(internal_router)
