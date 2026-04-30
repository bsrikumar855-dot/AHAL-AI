"""
AHAL AI — Application Entry Point

FastAPI app factory with:
- Lifespan management (MongoDB connect/disconnect)
- CORS middleware
- Request logging middleware (structured, with timing)
- Global exception handlers
- Versioned API routing

Run: uvicorn app.main:app --reload
"""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import register_exception_handlers
from app.core.product_identity import PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_GOAL, get_product_summary
from app.db.mongodb import mongodb
from app.db.repository import SessionRepository
from app.api.v1.router import router as v1_router
from app.services.analysis_service import get_task_record, update_task_record

# Initialize structured logging
setup_logging()
logger = get_logger("main")


def _parse_allowed_origins(value: str) -> list[str]:
    origins: list[str] = []
    for origin in str(value or "").split(","):
        cleaned = origin.strip()
        if cleaned and cleaned not in origins:
            origins.append(cleaned)
    return origins or ["http://localhost:3000"]


# ── Lifespan ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle events.
    - Startup: connect to MongoDB, create indexes
    - Shutdown: close MongoDB connection
    """
    settings = get_settings()
    logger.info(
        f"Starting {settings.APP_NAME} v{settings.APP_VERSION}",
        extra={"extra_data": {"debug": settings.DEBUG}},
    )

    # Startup
    await mongodb.connect()
    logger.info("Application started successfully")

    yield

    # Shutdown
    await mongodb.disconnect()
    logger.info("Application shut down gracefully")


# ── App Factory ──────────────────────────────────────────────────


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    This factory pattern makes testing easier — you can
    create app instances with different configurations.
    """
    settings = get_settings()

    app = FastAPI(
        title=PRODUCT_NAME,
        version=settings.APP_VERSION,
        description=PRODUCT_GOAL,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────
    allowed_origins = _parse_allowed_origins(settings.CORS_ALLOWED_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials="*" not in allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception Handlers ───────────────────────────────────
    register_exception_handlers(app)

    # ── Request Logging Middleware ────────────────────────────
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """Log every request with timing and correlation ID."""
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # Attach correlation ID to request state
        request.state.correlation_id = correlation_id

        logger.info(
            f"→ {request.method} {request.url.path}",
            extra={"extra_data": {
                "correlation_id": correlation_id,
                "method": request.method,
                "path": str(request.url.path),
                "query": str(request.query_params),
            }},
        )

        response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 1)
        logger.info(
            f"← {response.status_code} ({duration_ms}ms)",
            extra={"extra_data": {
                "correlation_id": correlation_id,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }},
        )

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    # ── Routes ───────────────────────────────────────────────
    app.include_router(v1_router)

    # ── Root endpoint ────────────────────────────────────────
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": PRODUCT_NAME,
            "tagline": PRODUCT_TAGLINE,
            "version": settings.APP_VERSION,
            "summary": get_product_summary(),
            "docs": "/docs",
            "health": "/api/v1/health",
            "identity": "/api/v1/identity",
        }

    @app.get("/status/{task_id}", tags=["Tasks"])
    async def task_status(task_id: str):
        task = get_task_record(task_id)
        session = await SessionRepository.get_by_job_id(task_id)
        if session is None:
            session = await SessionRepository.get_by_id(task_id)

        if session is not None:
            status_value = getattr(session.status, "value", str(session.status))
            result_payload = session.result.model_dump() if hasattr(session.result, "model_dump") else session.result
            task = update_task_record(
                task_id,
                status=session.status,
                progress=session.progress,
                stage=session.stage,
                result=result_payload if status_value == "completed" and isinstance(result_payload, dict) else None,
                error=session.error,
                structure=session.structure,
                title=session.title,
                preview=session.preview,
                source_ref=session.source_ref,
            )
            task.update(
                {
                    "task_id": task_id,
                    "session_id": session.session_id,
                    "job_id": session.job_id or task_id,
                    "type": getattr(session.type, "value", str(session.type)),
                }
            )
            if status_value != "completed":
                task["result"] = None
            task.pop("partial_result", None)
            return JSONResponse(content=jsonable_encoder(task))

        if task is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        if task.get("status") != "completed":
            task["result"] = None
        task.pop("partial_result", None)
        return JSONResponse(content=jsonable_encoder(task))

    return app


# Create the app instance
app = create_app()
