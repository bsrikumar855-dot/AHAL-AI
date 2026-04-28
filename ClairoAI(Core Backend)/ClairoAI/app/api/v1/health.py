"""
GET /api/v1/health

System health check endpoint.
Reports status of all dependencies (MongoDB, Ollama, disk space).
"""

import time
import shutil

from fastapi import APIRouter

from app.db.schemas import HealthResponse, HealthCheck
from app.db.mongodb import mongodb
from app.services.llm.factory import get_llm_provider
from app.services.rag import RAGService
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("api.health")
router = APIRouter()

# Track app start time for uptime calculation
_start_time = time.time()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    description="Reports the health status of all system components.",
    responses={
        200: {"description": "System health report"},
    },
)
async def health_check():
    """
    Check the health of all system dependencies:
    - MongoDB: connection and ping
    - LLM (Ollama): reachability
    - Disk: available space
    - RAG: circuit breaker state (if enabled)
    """
    settings = get_settings()
    checks: dict[str, HealthCheck] = {}

    # ── MongoDB ──────────────────────────────────────────────────
    try:
        db_healthy = await mongodb.is_healthy()
        checks["database"] = HealthCheck(
            status="healthy" if db_healthy else "unhealthy",
            details="MongoDB connection active" if db_healthy else "MongoDB unreachable",
        )
    except Exception as e:
        checks["database"] = HealthCheck(
            status="unhealthy",
            details=f"MongoDB error: {str(e)}",
        )

    # ── LLM (Ollama) ────────────────────────────────────────────
    try:
        llm = get_llm_provider("query")
        llm_healthy = await llm.health_check()
        checks["llm"] = HealthCheck(
            status="healthy" if llm_healthy else "unhealthy",
            details=f"Ollama reachable at {settings.OLLAMA_BASE_URL}" if llm_healthy
                    else "Ollama not reachable",
        )
    except Exception as e:
        checks["llm"] = HealthCheck(
            status="unhealthy",
            details=f"LLM health check failed: {str(e)}",
        )

    # ── Disk Space ───────────────────────────────────────────────
    try:
        disk = shutil.disk_usage("/")
        free_gb = disk.free / (1024 ** 3)
        disk_status = "healthy" if free_gb > 1.0 else "degraded" if free_gb > 0.5 else "unhealthy"
        checks["disk"] = HealthCheck(
            status=disk_status,
            details=f"{free_gb:.1f}GB free",
        )
    except Exception:
        checks["disk"] = HealthCheck(
            status="healthy",
            details="Disk check not available on this platform",
        )

    # ── RAG (if enabled) ────────────────────────────────────────
    if settings.RAG_ENABLED:
        rag = RAGService()
        rag_health = await rag.health_check()
        circuit_state = rag_health.get("circuit_state", "unknown")
        checks["rag"] = HealthCheck(
            status="healthy" if circuit_state == "closed" else "degraded",
            details=f"Circuit breaker: {circuit_state}",
        )

    # ── Overall status ──────────────────────────────────────────
    statuses = [c.status for c in checks.values()]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    uptime = time.time() - _start_time

    return HealthResponse(
        status=overall,
        version=settings.APP_VERSION,
        checks=checks,
        uptime_seconds=round(uptime, 1),
    )
