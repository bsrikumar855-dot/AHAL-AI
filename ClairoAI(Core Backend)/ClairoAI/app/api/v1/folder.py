"""
POST /api/v1/folder/analyze

Asynchronous folder analysis endpoint.
Returns a processing session immediately and completes deep analysis in the background.
"""

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.db.schemas import SessionStatusResponse
from app.services.folder_analyzer import FolderAnalyzer
from app.services.job_manager import process_folder_analysis_session, start_background_job

logger = get_logger("api.folder")
router = APIRouter()


@router.post(
    "/analyze",
    response_model=SessionStatusResponse,
    status_code=202,
    summary="Start folder analysis",
    description="Queues uploaded project analysis and returns a processing session immediately.",
)
async def analyze_folder(
    file: UploadFile = File(..., description="Project .zip file"),
    mode: str = Form(default="online"),
    session_id: str | None = Form(default=None),
):
    settings = get_settings()
    requested_session_id = str(uuid.uuid4())
    print("SESSION:", requested_session_id)
    print("NEW ANALYSIS GENERATED")

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail={"error": "Only .zip files are supported"})

    file_bytes = await file.read()
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail={"error": "Uploaded file is empty"})
    if len(file_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail={"error": f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB"},
        )

    analyzer = FolderAnalyzer()
    try:
        _file_contents, selected_files, _arch_hints, quick_result = await analyzer.prepare_analysis(file_bytes, file.filename)
    except Exception as err:
        logger.error(f"Folder fast scan failed: {err}")
        selected_files = {}
        quick_result = analyzer.generate_minimal_analysis({}, file.filename)

    structure = list(selected_files.keys())[:30]
    preview = f"Uploaded {file.filename} ({len(file_bytes)} bytes)"
    try:
        session = SessionDocument(
            session_id=requested_session_id,
            type=SessionType.FOLDER,
            title=f"Project: {file.filename}",
            status=SessionStatus.PROCESSING,
            preview=preview,
            source_ref=file.filename,
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
            result=quick_result,
            progress=30,
            stage="Static project scan completed",
            job_id=requested_session_id,
        )
        created_session_id = await SessionRepository.create(session)
    except Exception as err:
        logger.error(f"Failed to create folder session: {err}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Folder analysis is warming up. Please retry in a moment.",
                "details": str(err),
            },
        )

    try:
        start_background_job(process_folder_analysis_session(created_session_id, file_bytes, file.filename, mode))
    except Exception as err:
        logger.error(f"Failed to start folder analysis background job: {err}")
        await SessionRepository.update_status(
            session_id=created_session_id,
            status=SessionStatus.FAILED,
            progress=100,
            stage="Analysis startup delayed",
            result=None,
            error="Fresh analysis failed",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Folder analysis startup is delayed. Please retry in a moment.",
                "details": str(err),
            },
        )

    return SessionStatusResponse(
        session_id=created_session_id,
        job_id=created_session_id,
        type=SessionType.FOLDER,
        status=SessionStatus.PROCESSING,
        progress=30,
        stage="Static project scan completed",
        title=f"Project: {file.filename}",
        preview=preview,
        source_ref=file.filename,
        structure=structure,
        result=quick_result,
        error=None,
    )
