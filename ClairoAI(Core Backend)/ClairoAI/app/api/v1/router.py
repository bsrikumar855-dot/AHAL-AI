"""
API v1 router aggregator.

Collects all v1 endpoint routers into a single router
that is mounted on the FastAPI app at /api/v1.
"""

from fastapi import APIRouter

from app.api.v1.summarize import router as summarize_router
from app.api.v1.status import router as status_router
from app.api.v1.query import router as query_router
from app.api.v1.summaries import router as summaries_router
from app.api.v1.health import router as health_router
from app.api.v1.repo import router as repo_router
from app.api.v1.code import router as code_router
from app.api.v1.folder import router as folder_router
from app.api.v1.session import router as session_router
from app.api.v1.chat import router as chat_router

router = APIRouter(prefix="/api/v1")

# ── Existing routes (preserved) ──
router.include_router(summarize_router, tags=["Summarization"])
router.include_router(status_router, tags=["Jobs"])
router.include_router(query_router, tags=["Query"])
router.include_router(summaries_router, tags=["Summaries"])
router.include_router(health_router, tags=["Health"])
router.include_router(repo_router, prefix="/repo", tags=["Repository Analysis"])

# ── Multi-session routes (new) ──
router.include_router(code_router, prefix="/code", tags=["Code Analysis"])
router.include_router(folder_router, prefix="/folder", tags=["Folder Analysis"])
router.include_router(session_router, prefix="/session", tags=["Sessions"])
router.include_router(chat_router, prefix="/chat", tags=["Chat"])
