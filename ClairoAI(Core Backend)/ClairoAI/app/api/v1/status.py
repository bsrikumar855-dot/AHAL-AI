"""
GET /api/v1/status/{job_id}

Returns the current processing status of an async summarization job.
"""

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.db.schemas import StatusResponse
from app.db.repository import JobRepository, SessionRepository
from app.core.exceptions import JobNotFoundError
from app.core.logging import get_logger
from app.services.analysis_service import get_task_record, update_task_record

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
    task = get_task_record(job_id)
    session = await SessionRepository.get_by_job_id(job_id)
    if session is None:
        session = await SessionRepository.get_by_id(job_id)

    if session is not None:
        status_value = getattr(session.status, "value", str(session.status))
        result_payload = session.result.model_dump() if hasattr(session.result, "model_dump") else session.result
        task = update_task_record(
            job_id,
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
                "task_id": job_id,
                "session_id": session.session_id,
                "job_id": session.job_id or job_id,
                "type": getattr(session.type, "value", str(session.type)),
            }
        )
        if status_value != "completed":
            task["result"] = None
        task.pop("partial_result", None)
        return JSONResponse(content=jsonable_encoder(task))

    if task is not None:
        if task.get("status") != "completed":
            task["result"] = None
        task.pop("partial_result", None)
        return JSONResponse(content=jsonable_encoder(task))

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
