"""
POST /api/v1/folder/analyze

Asynchronous folder analysis endpoint.
Returns a processing session immediately and completes deep analysis in the background.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import SessionDocument, SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.db.schemas import SessionStatusResponse
from app.services.analysis_service import create_task_record
from app.services.job_manager import process_folder_analysis_session

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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Project .zip file"),
    mode: str = Form(default="online"),
    session_id: str | None = Form(default=None),
):
    settings = get_settings()
    requested_session_id = str(session_id or uuid.uuid4())
    logger.info(
        "Folder analysis request received",
        extra={"extra_data": {"session_id": requested_session_id, "filename": file.filename}},
    )

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail={"error": "Only .zip files are supported"})

    try:
        file_bytes = await file.read()
        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) == 0:
            raise HTTPException(status_code=400, detail={"error": "Uploaded file is empty"})
        if len(file_bytes) > max_size:
            raise HTTPException(
                status_code=400,
                detail={"error": f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB"},
            )

        preview = f"Uploaded {file.filename} ({len(file_bytes)} bytes)"
        try:
            session = SessionDocument(
                session_id=requested_session_id,
                type=SessionType.FOLDER,
                title=f"Project: {file.filename}",
                status=SessionStatus.PROCESSING,
                preview=preview,
                source_ref=file.filename,
                structure=[],
                summary="",
                result=None,
                progress=0,
                stage="upload",
                job_id=requested_session_id,
            )
            created_session_id = await SessionRepository.create(session)
            create_task_record(
                created_session_id,
                task_type=SessionType.FOLDER.value,
                title=f"Project: {file.filename}",
                preview=preview,
                source_ref=file.filename,
                progress=0,
                stage="upload",
            )
        except Exception as err:
            logger.error(f"Failed to create folder session: {err}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Folder analysis is warming up.",
                    "details": str(err),
                },
            )

        try:
            background_tasks.add_task(process_folder_analysis_session, created_session_id, file_bytes, file.filename, mode)
        except Exception as err:
            logger.error(f"Failed to start folder analysis background job: {err}")
            await SessionRepository.update_status(
                session_id=created_session_id,
                status=SessionStatus.FAILED,
                progress=100,
                stage="finalize",
                error="Fresh analysis failed",
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Folder analysis startup is delayed.",
                    "details": str(err),
                },
            )

        return SessionStatusResponse(
            session_id=created_session_id,
            task_id=created_session_id,
            job_id=created_session_id,
            type=SessionType.FOLDER,
            status=SessionStatus.PROCESSING,
            progress=0,
            stage="upload",
            title=f"Project: {file.filename}",
            preview=preview,
            source_ref=file.filename,
            structure=[],
            result=None,
            error=None,
        )
    finally:
        await file.close()
