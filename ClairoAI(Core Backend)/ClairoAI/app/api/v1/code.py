"""
POST /api/v1/code/analyze

Asynchronous code analysis endpoint.
Returns a processing session immediately and completes semantic analysis in the background.
"""

import uuid

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository, ensure_valid_session_id
from app.db.schemas import CodeAnalyzeRequest, SessionStatusResponse
from app.services.code_analyzer import CodeAnalyzer
from app.services.job_manager import process_code_analysis_session, start_background_job

logger = get_logger("api.code")
router = APIRouter()


@router.post(
    "/analyze",
    response_model=SessionStatusResponse,
    status_code=202,
    summary="Start code analysis",
    description="Queues code analysis and returns a processing session immediately.",
)
async def analyze_code(request: CodeAnalyzeRequest):
    requested_session_id = ensure_valid_session_id(request.session_id) or str(uuid.uuid4())
    user_code = request.code

    logger.info(f"Code analysis request received ({len(user_code)} chars)")

    analyzer = CodeAnalyzer()
    quick_result = analyzer.build_quick_result(user_code)
    structure = quick_result.get("key_modules", [])[:20]
    title = _derive_title(user_code)

    try:
        session = SessionDocument(
            session_id=requested_session_id,
            type=SessionType.CODE,
            title=title,
            status=SessionStatus.PROCESSING,
            preview=user_code[:200].strip(),
            source_ref="inline-code",
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
            result=quick_result,
            progress=25,
            stage="Static code scan completed",
            job_id=requested_session_id,
        )
        session_id = await SessionRepository.create(session)
    except Exception as err:
        logger.error(f"Failed to create code session: {err}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Code analysis is warming up. Please retry in a moment.",
                "details": str(err),
            },
        )

    try:
        start_background_job(process_code_analysis_session(session_id, user_code, request.mode))
    except Exception as err:
        logger.error(f"Failed to start code analysis background job: {err}")
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            progress=100,
            stage="Analysis startup delayed",
            result=quick_result,
            error="Partial analysis completed. Full analysis will resume when processing capacity is available.",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Code analysis startup is delayed. Please retry in a moment.",
                "details": str(err),
            },
        )

    return SessionStatusResponse(
        session_id=session_id,
        job_id=session_id,
        type=SessionType.CODE,
        status=SessionStatus.PROCESSING,
        progress=25,
        stage="Static code scan completed",
        title=title,
        preview=user_code[:200].strip(),
        source_ref="inline-code",
        structure=structure,
        result=quick_result,
        error=None,
    )


def _derive_title(code: str) -> str:
    for line in code.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//", "/*", "*", "---")):
            return stripped[:80]
    return "Code Analysis"
