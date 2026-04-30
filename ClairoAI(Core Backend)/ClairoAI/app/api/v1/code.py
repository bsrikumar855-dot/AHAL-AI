"""
POST /api/v1/code/analyze

Asynchronous code analysis endpoint.
Returns a processing session immediately and completes semantic analysis in the background.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.db.schemas import CodeAnalyzeRequest, SessionStatusResponse
from app.services.analysis_service import create_task_record
from app.services.job_manager import process_code_analysis_session

logger = get_logger("api.code")
router = APIRouter()


@router.post(
    "/analyze",
    response_model=SessionStatusResponse,
    status_code=202,
    summary="Start code analysis",
    description="Queues code analysis and returns a processing session immediately.",
)
async def analyze_code(request: CodeAnalyzeRequest, background_tasks: BackgroundTasks):
    requested_session_id = str(request.session_id or uuid.uuid4())
    user_code = request.code

    logger.info(
        "Code analysis request received",
        extra={"extra_data": {"session_id": requested_session_id, "content_length": len(user_code)}},
    )

    title = _derive_title(user_code)

    try:
        session = SessionDocument(
            session_id=requested_session_id,
            type=SessionType.CODE,
            title=title,
            status=SessionStatus.PROCESSING,
            preview=user_code[:200].strip(),
            source_ref="inline-code",
            structure=[],
            summary="",
            result=None,
            progress=0,
            stage="upload",
            job_id=requested_session_id,
        )
        session_id = await SessionRepository.create(session)
        create_task_record(
            session_id,
            task_type=SessionType.CODE.value,
            title=title,
            preview=user_code[:200].strip(),
            source_ref="inline-code",
            progress=0,
            stage="upload",
        )
    except Exception as err:
        logger.error(f"Failed to create code session: {err}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Code analysis is warming up.",
                "details": str(err),
            },
        )

    try:
        background_tasks.add_task(process_code_analysis_session, session_id, user_code, request.mode)
    except Exception as err:
        logger.error(f"Failed to start code analysis background job: {err}")
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            progress=100,
            stage="finalize",
            error="Fresh analysis failed",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Code analysis startup is delayed.",
                "details": str(err),
            },
        )

    return SessionStatusResponse(
        session_id=session_id,
        task_id=session_id,
        job_id=session_id,
        type=SessionType.CODE,
        status=SessionStatus.PROCESSING,
        progress=0,
        stage="upload",
        title=title,
        preview=user_code[:200].strip(),
        source_ref="inline-code",
        structure=[],
        result=None,
        error=None,
    )


def _derive_title(code: str) -> str:
    for line in code.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//", "/*", "*", "---")):
            return stripped[:80]
    return "Code Analysis"
