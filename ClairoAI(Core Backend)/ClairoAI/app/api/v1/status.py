"""
GET /api/v1/status/{job_id}

Returns the current processing status of an async summarization job.
"""

from fastapi import APIRouter

from app.db.schemas import StatusResponse
from app.db.repository import JobRepository
from app.core.exceptions import JobNotFoundError
from app.core.logging import get_logger

logger = get_logger("api.status")
router = APIRouter()


@router.get(
    "/status/{job_id}",
    response_model=StatusResponse,
    summary="Check job status",
    description="Returns the current status of a summarization job.",
    responses={
        200: {"description": "Job status retrieved"},
        404: {"description": "Job not found"},
    },
)
async def get_job_status(job_id: str):
    """
    Retrieve the status of a previously submitted job.

    Returns the job status, and on completion, the resulting summary ID.
    """
    job = await JobRepository.get_by_id(job_id)

    if job is None:
        raise JobNotFoundError(job_id)

    logger.info(
        f"Status check",
        extra={"extra_data": {"job_id": job_id, "status": job.status.value}},
    )

    return StatusResponse(
        job_id=job.job_id,
        status=job.status,
        result_id=job.result_id,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
