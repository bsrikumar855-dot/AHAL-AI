"""
POST /api/v1/repo/analyze

Asynchronous repository analysis endpoint.
Starts a background repository job immediately and returns a processing session.
"""

import uuid

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.db.schemas import RepoAnalyzeRequest, SessionStatusResponse
from app.services.job_manager import process_repo_analysis_job, start_background_job
from app.services.repo_service import generate_minimal_analysis

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
    requested_session_id = str(uuid.uuid4())

    logger.info(f"Repo analysis request received for {repo_url}")
    print("SESSION:", requested_session_id)
    print("NEW ANALYSIS GENERATED")
    print(f"[REPO ANALYZE] QUEUED URL: {repo_url}")

    try:
        repo_name = repo_url.rstrip("/").split("/")[-1] or "repository"
        initial_result = generate_minimal_analysis([], repo_url)
        session_kwargs = {
            "type": SessionType.REPO,
            "title": f"Repo: {repo_name}",
            "status": SessionStatus.PROCESSING,
            "preview": repo_url,
            "source_ref": repo_url,
            "summary": initial_result.get("summary_blocks", {}).get("what", ""),
            "result": initial_result,
            "progress": 0,
            "stage": "Queued repository analysis",
            "job_id": requested_session_id,
        }
        session_kwargs["session_id"] = requested_session_id

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
            error="Fresh analysis failed",
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
        result=initial_result,
        error=None,
        progress=0,
        stage="Queued repository analysis",
    )
