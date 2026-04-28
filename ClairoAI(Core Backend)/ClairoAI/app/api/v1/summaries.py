"""
GET /api/v1/summaries

List stored summaries with optional filtering and pagination.
"""

from typing import Optional
from fastapi import APIRouter, Query

from app.db.schemas import SummaryListResponse, SummaryResponse
from app.db.repository import SummaryRepository
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("api.summaries")
router = APIRouter()


@router.get(
    "/summaries",
    response_model=SummaryListResponse,
    summary="List stored summaries",
    description="Retrieve a paginated list of stored summaries with optional filters.",
    responses={
        200: {"description": "Summaries retrieved"},
    },
)
async def list_summaries(
    project: Optional[str] = Query(
        default=None,
        description="Filter by project identifier",
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status (pending, processing, completed, failed)",
    ),
    flagged: Optional[bool] = Query(
        default=None,
        description="Filter by flagged_for_review status",
    ),
    skip: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip (pagination offset)",
    ),
    limit: int = Query(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of records to return",
    ),
):
    """
    List summaries with optional filtering.

    Supports filtering by project, status, and flagged state.
    Results are sorted by creation date (newest first).
    """
    settings = get_settings()
    page_size = limit or settings.DEFAULT_PAGE_SIZE

    summaries, total = await SummaryRepository.list_summaries(
        project=project,
        status=status,
        flagged=flagged,
        skip=skip,
        limit=page_size,
    )

    logger.info(
        "Summaries listed",
        extra={"extra_data": {
            "total": total,
            "returned": len(summaries),
            "skip": skip,
            "limit": page_size,
        }},
    )

    return SummaryListResponse(
        summaries=[
            SummaryResponse(
                id=s.id,
                project=s.project,
                input_type=s.input_type,
                summary=s.summary,
                status=s.status,
                flagged_for_review=s.flagged_for_review,
                created_at=s.created_at,
                updated_at=s.updated_at,
                metadata=s.metadata,
            )
            for s in summaries
        ],
        total=total,
        skip=skip,
        limit=page_size,
    )
