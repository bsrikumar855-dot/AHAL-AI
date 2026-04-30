"""
POST /api/v1/repo/analyze

Asynchronous repository analysis endpoint.
Starts a background repository job immediately and returns a processing session.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.db.schemas import RepoAnalyzeRequest, SessionStatusResponse
from app.services.analysis_service import create_task_record
from app.services.job_manager import process_repo_analysis_job

logger = get_logger("api.repo")
router = APIRouter()


@router.post(
    "/analyze",
    response_model=SessionStatusResponse,
    status_code=202,
    summary="Start repository analysis",
    description="Queues a GitHub repository analysis job and returns a processing session immediately.",
    responses={
        202: {"description": "Analysis job created successfully"},
        422: {"description": "Invalid input"},
        500: {"description": "Unable to start analysis"},
    },
)
async def analyze_repo(request: RepoAnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Starts repo analysis in the background and returns a processing session.
    Clients should poll the session status endpoint for progress and fetch the result endpoint once completed.
    """
    repo_url = request.repo_url
    requested_session_id = str(request.session_id or uuid.uuid4())

    logger.info(
        "Repo analysis request received",
        extra={"extra_data": {"session_id": requested_session_id, "repo_url": repo_url}},
    )

    try:
        repo_name = repo_url.rstrip("/").split("/")[-1] or "repository"
        session_kwargs = {
            "type": SessionType.REPO,
            "title": f"Repo: {repo_name}",
            "status": SessionStatus.PROCESSING,
            "preview": repo_url,
            "source_ref": repo_url,
            "summary": "",
            "result": None,
            "progress": 0,
            "stage": "upload",
            "job_id": requested_session_id,
        }
        session_kwargs["session_id"] = requested_session_id

        session = SessionDocument(**session_kwargs)
        session_id = await SessionRepository.create(session)
        create_task_record(
            session_id,
            task_type=SessionType.REPO.value,
            title=f"Repo: {repo_name}",
            preview=repo_url,
            source_ref=repo_url,
            progress=0,
            stage="upload",
        )
    except Exception as err:
        logger.error(f"Failed to create repo session: {err}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Repository analysis is warming up.",
                "details": str(err),
            },
        )

    try:
        background_tasks.add_task(process_repo_analysis_job, session_id, repo_url)
    except Exception as err:
        logger.error(f"Failed to start repo background job: {err}")
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            error="Fresh analysis failed",
            progress=100,
            stage="finalize",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Repository analysis startup is delayed.",
                "details": str(err),
            },
        )

    return SessionStatusResponse(
        session_id=session_id,
        task_id=session_id,
        job_id=session_id,
        type=SessionType.REPO,
        status=SessionStatus.PROCESSING,
        title=f"Repo: {repo_url.rstrip('/').split('/')[-1] or 'repository'}",
        preview=repo_url,
        source_ref=repo_url,
        structure=[],
        result=None,
        error=None,
        progress=0,
        stage="upload",
    )
