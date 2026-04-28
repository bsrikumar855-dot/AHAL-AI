"""
ContextBridge AI — Application Entry Point

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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import register_exception_handlers
from app.db.mongodb import mongodb
from app.api.v1.router import router as v1_router

# Initialize structured logging
setup_logging()
logger = get_logger("main")


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
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "AI-powered developer tool that transforms code changes "
            "into structured, queryable knowledge using Gemma models."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
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
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


# Create the app instance
app = create_app()
