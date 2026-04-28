"""
POST /api/v1/repo/analyze

Asynchronous repository analysis endpoint.
Starts a background repository job immediately and returns a processing session.
"""

import uuid

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository, ensure_valid_session_id
from app.db.schemas import RepoAnalyzeRequest, SessionStatusResponse
from app.services.job_manager import process_repo_analysis_job, start_background_job

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
async def analyze_repo(request: RepoAnalyzeRequest):
    """
    Starts repo analysis in the background and returns a processing session.
    Clients should poll the session status endpoint for progress and partial results.
    """
    repo_url = request.repo_url
    requested_session_id = ensure_valid_session_id(request.session_id)

    logger.info(f"Repo analysis request received for {repo_url}")
    print(f"[REPO ANALYZE] QUEUED URL: {repo_url}")

    try:
        repo_name = repo_url.rstrip("/").split("/")[-1] or "repository"
        session_kwargs = {
            "type": SessionType.REPO,
            "title": f"Repo: {repo_name}",
            "status": SessionStatus.PROCESSING,
            "preview": repo_url,
            "source_ref": repo_url,
            "progress": 0,
            "stage": "Queued repository analysis",
            "job_id": requested_session_id or str(uuid.uuid4()),
        }
        session_kwargs["session_id"] = requested_session_id or str(uuid.uuid4())

        session = SessionDocument(**session_kwargs)
        session_id = await SessionRepository.create(session)
    except Exception as err:
        print(f"ERROR: Failed to create repo session: {err}")
        logger.error(f"Failed to create repo session: {err}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Repository analysis is warming up. Please retry in a moment.",
                "details": str(err),
            },
        )

    try:
        start_background_job(process_repo_analysis_job(session_id, repo_url))
    except Exception as err:
        print(f"ERROR: Failed to start repo background job: {err}")
        logger.error(f"Failed to start repo background job: {err}")
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            error="Repository scan started with partial context. Full analysis will resume when processing capacity is available.",
            progress=100,
            stage="Analysis startup delayed",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Repository analysis startup is delayed. Please retry in a moment.",
                "details": str(err),
            },
        )

    return SessionStatusResponse(
        session_id=session_id,
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
        stage="Queued repository analysis",
    )
