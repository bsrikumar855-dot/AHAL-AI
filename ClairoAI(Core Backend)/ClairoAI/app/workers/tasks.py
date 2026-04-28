"""
Background task runner for async LLM processing.

LLM calls are expensive and slow — they MUST NOT block the API request.
This module provides the bridge between the API layer (which creates jobs)
and the services layer (which does the actual work).

Architecture note:
    Currently uses asyncio tasks via FastAPI's BackgroundTasks.
    The interface is designed so you can swap in Celery, ARQ, or
    any other task queue without changing the service layer.
"""

import asyncio
import traceback
from typing import Optional

from app.db.models import InputType, JobStatus, SessionStatus, UnifiedResult, SummaryBlocks
from app.db.repository import JobRepository, SessionRepository
from app.services.summarizer import SummarizationService
from app.services.file_handler import FileHandler
from app.services.repo_service import process_repo_analysis_session
from app.services.normalize import normalize_result
from app.core.logging import get_logger

logger = get_logger("worker")


async def process_summarization_job(
    job_id: str,
    input_content: str,
    input_type: str,
    project: str = "default",
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> None:
    """
    Execute the full summarization pipeline as a background task.

    This function is called by FastAPI's BackgroundTasks. It:
    1. Updates job status to 'processing'
    2. Handles file extraction (if project upload)
    3. Runs the summarization pipeline
    4. Updates job status to 'completed' or 'failed'

    All exceptions are caught and stored — the job never raises.

    Args:
        job_id:        The job record ID to update
        input_content: Raw text input (diff or commit message)
        input_type:    "diff", "commit", or "project"
        project:       Project identifier
        file_bytes:    Raw ZIP file bytes (for project uploads)
        filename:      Original filename (for project uploads)
    """
    logger.info(
        f"Starting background job",
        extra={"extra_data": {
            "job_id": job_id,
            "input_type": input_type,
            "project": project,
        }},
    )

    try:
        # Mark job as processing
        await JobRepository.update_status(job_id, JobStatus.PROCESSING)

        parsed_type = InputType(input_type)
        file_contents = None

        # Handle file upload extraction
        if parsed_type == InputType.PROJECT and file_bytes:
            logger.info(f"Extracting project upload: {filename}")
            handler = FileHandler()
            file_contents = await handler.process_upload(file_bytes, filename or "upload.zip")

            # Use file listing as the input_content for storage
            if not input_content:
                input_content = f"Project upload: {filename}\nFiles: {', '.join(sorted(file_contents.keys())[:20])}"

        # Run summarization pipeline
        service = SummarizationService()
        summary_doc = await service.summarize(
            input_content=input_content,
            input_type=parsed_type,
            project=project,
            file_contents=file_contents,
        )

        # Mark job as completed with reference to the summary
        await JobRepository.update_status(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result_id=summary_doc.id,
        )

        logger.info(
            f"Background job completed",
            extra={"extra_data": {
                "job_id": job_id,
                "summary_id": summary_doc.id,
                "flagged": summary_doc.flagged_for_review,
            }},
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(
            f"Background job failed",
            extra={"extra_data": {
                "job_id": job_id,
                "error": error_msg,
                "traceback": traceback.format_exc(),
            }},
        )

        # Mark job as failed
        await JobRepository.update_status(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=error_msg,
        )

async def process_repo_analyze_job(
    job_id: str,
    repo_url: str,
    session_id: Optional[str] = None,
) -> None:
    """
    Execute the full repository analysis pipeline as a background task.
    Now uses GitHub ZIP download instead of git clone.
    """
    logger.info(f"Starting repo analysis job for {repo_url}")

    try:
        await JobRepository.update_status(job_id, JobStatus.PROCESSING)

        if session_id:
            await process_repo_analysis_session(session_id, repo_url)

        await JobRepository.update_status(
            job_id=job_id,
            status=JobStatus.COMPLETED,
        )
        logger.info(f"Repo analysis completed for {repo_url}")

        # Update session with unified result if session tracking is active
        if session_id:
            try:
                session = await SessionRepository.get_by_id(session_id)
                if session and session.result is not None:
                    await SessionRepository.update_status(
                        session_id=session_id,
                        status=SessionStatus.COMPLETED,
                        result=session.result.model_dump() if hasattr(session.result, "model_dump") else dict(session.result),
                    )
            except Exception as session_err:
                logger.warning(f"Failed to update session {session_id}: {session_err}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Repo analysis job failed: {error_msg}\\n{traceback.format_exc()}")
        await JobRepository.update_status(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=error_msg,
        )

        # Mark session as failed too
        if session_id:
            try:
                await SessionRepository.update_status(
                    session_id=session_id,
                    status=SessionStatus.FAILED,
                    error=error_msg,
                )
            except Exception:
                pass
