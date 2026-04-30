"""
POST /api/v1/summarize

Accepts code diffs, commit messages, or project uploads (.zip)
and dispatches async summarization jobs.

Supports two content types:
- application/json: for text-based input (diff, commit)
- multipart/form-data: for .zip file uploads
"""

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Optional

from app.db.models import JobRecord, InputType, JobStatus
from app.db.schemas import SummarizeTextRequest, JobResponse
from app.db.repository import JobRepository
from app.workers.tasks import process_summarization_job
from app.core.exceptions import InputValidationError, FileProcessingError
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger("api.summarize")
router = APIRouter()


@router.post(
    "/summarize",
    response_model=JobResponse,
    status_code=202,
    summary="Submit code for summarization",
    description="Accepts a diff, commit message, or project upload and "
                "returns a job ID for async tracking.",
    responses={
        202: {"description": "Job submitted successfully"},
        400: {"description": "Invalid file upload"},
        422: {"description": "Invalid input data"},
    },
)
async def summarize_text(
    background_tasks: BackgroundTasks,
    request: SummarizeTextRequest,
):
    """
    Handle JSON-based summarization requests (diff or commit text).
    """
    logger.info(
        "Summarize request received (text)",
        extra={"extra_data": {
            "input_type": request.input_type.value,
            "project": request.project,
            "content_length": len(request.content),
        }},
    )

    # Validate content
    if not request.content.strip():
        raise InputValidationError("Content cannot be empty")

    # Create job record
    job = JobRecord(
        input_type=request.input_type,
        project=request.project,
        status=JobStatus.PENDING,
    )
    await JobRepository.create(job)

    # Dispatch background task
    background_tasks.add_task(
        process_summarization_job,
        job_id=job.job_id,
        input_content=request.content,
        input_type=request.input_type.value,
        project=request.project,
    )

    logger.info(f"Job dispatched: {job.job_id}")

    return JobResponse(
        job_id=job.job_id,
        status=JobStatus.PENDING,
        message="Summarization job submitted successfully",
    )


@router.post(
    "/summarize/upload",
    response_model=JobResponse,
    status_code=202,
    summary="Upload a project for summarization",
    description="Accepts a .zip file upload and returns a job ID for async tracking.",
    responses={
        202: {"description": "Upload job submitted successfully"},
        400: {"description": "Invalid file"},
        422: {"description": "Validation error"},
    },
)
async def summarize_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Project .zip file"),
    project: str = Form(default="default", description="Project identifier"),
):
    """
    Handle file upload-based summarization requests (.zip projects).
    """
    settings = get_settings()

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise FileProcessingError("Only .zip files are supported")

    try:
        # Read file bytes
        file_bytes = await file.read()

        # Validate size
        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_size:
            raise FileProcessingError(
                f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB"
            )

        if len(file_bytes) == 0:
            raise FileProcessingError("Uploaded file is empty")

        logger.info(
            "Summarize request received (upload)",
            extra={"extra_data": {
                "filename": file.filename,
                "size_bytes": len(file_bytes),
                "project": project,
            }},
        )

        # Create job record
        job = JobRecord(
            input_type=InputType.PROJECT,
            project=project,
            status=JobStatus.PENDING,
        )
        await JobRepository.create(job)

        # Dispatch background task with file bytes
        background_tasks.add_task(
            process_summarization_job,
            job_id=job.job_id,
            input_content="",
            input_type=InputType.PROJECT.value,
            project=project,
            file_bytes=file_bytes,
            filename=file.filename,
        )

        logger.info(f"Upload job dispatched: {job.job_id}")

        return JobResponse(
            job_id=job.job_id,
            status=JobStatus.PENDING,
            message="Project upload submitted for summarization",
        )
    finally:
        await file.close()
