"""
GET /api/v1/session/{session_id}/status
GET /api/v1/session/{session_id}/stream
GET /api/v1/session/{session_id}/intelligence
GET /api/v1/session/history

Unified session tracking endpoints for all analysis modes.
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.db.schemas import (
    SessionStatusResponse,
    SessionHistoryItem,
    SessionHistoryResponse,
)
from app.db.repository import SessionRepository
from app.core.logging import get_logger
from app.services.knowledge_store import build_knowledge_snapshot
from app.services.llm_handler import LLM_TIMEOUT_BACKGROUND
from app.services.memory_service import get_memory_profile
from app.services.report_service import build_project_report
from app.services.job_manager import get_cached_job_state

logger = get_logger("api.session")
router = APIRouter()


class SessionReportResponse(BaseModel):
    session_id: str
    type: str
    report: str


class SessionIntelligenceResponse(BaseModel):
    session_id: str
    project: dict = {}
    workflows: list[dict] = []
    graph: dict = {}
    memory_profile: dict = {}


class SessionResultResponse(BaseModel):
    session_id: str
    task_id: Optional[str] = None
    job_id: Optional[str] = None
    type: str
    status: str
    progress: int = 0
    stage: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None


def _status_value(value) -> str:
    return getattr(value, "value", str(value))


def _build_status_response(session, *, include_result: bool = False) -> SessionStatusResponse:
    status_value = _status_value(session.status)
    error_value = session.error
    stage_value = session.stage
    if LLM_TIMEOUT_BACKGROUND.lower() in str(session.error or "").lower():
        status_value = "processing"
        error_value = None
        if not str(stage_value or "").strip():
            stage_value = "LLM timeout; analysis still running in background"
    result_payload = None
    if include_result and status_value == "completed" and session.result is not None:
        result_payload = session.result

    return SessionStatusResponse(
        session_id=session.session_id,
        task_id=session.job_id or session.session_id,
        job_id=session.job_id,
        type=session.type,
        status=status_value,
        progress=session.progress,
        stage=stage_value,
        title=session.title,
        preview=session.preview,
        source_ref=session.source_ref,
        structure=session.structure,
        result=result_payload,
        error=error_value,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get(
    "/{session_id}/status",
    response_model=SessionStatusResponse,
    summary="Get session status",
    description="Returns the current status of an analysis session, including result if completed.",
    responses={
        200: {"description": "Session status retrieved"},
        404: {"description": "Session not found"},
    },
)
async def get_session_status(session_id: str):
    """Retrieve the status and result of a session by ID."""
    session = await SessionRepository.get_by_id(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    logger.info(
        f"Session status check",
        extra={"extra_data": {"session_id": session_id, "status": session.status.value}},
    )

    return _build_status_response(session, include_result=False)


@router.get(
    "/status/{job_id}",
    response_model=SessionStatusResponse,
    summary="Get analysis job status",
    description="Alias for session status using the async job identifier.",
)
async def get_job_status(job_id: str):
    cached = get_cached_job_state(job_id)
    session = await SessionRepository.get_by_job_id(job_id)
    if session is None:
        session = await SessionRepository.get_by_id(job_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    response = _build_status_response(session, include_result=False)
    if cached and _status_value(session.status) != "completed":
        response.progress = int(cached.get("progress", response.progress))
        response.stage = str(cached.get("stage", response.stage))
        response.error = cached.get("error", response.error)
    return response


@router.get(
    "/result/{task_id}",
    response_model=SessionResultResponse,
    summary="Get analysis result",
    description="Returns the final structured analysis result only when the job is completed.",
)
async def get_result(task_id: str):
    session = await SessionRepository.get_by_job_id(task_id)
    if session is None:
        session = await SessionRepository.get_by_id(task_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Job '{task_id}' not found")

    status_value = _status_value(session.status)
    result_payload = session.result.model_dump() if hasattr(session.result, "model_dump") else session.result
    if status_value != "completed" or not isinstance(result_payload, dict):
        pending_response = SessionResultResponse(
            session_id=session.session_id,
            task_id=session.job_id or session.session_id,
            job_id=session.job_id,
            type=_status_value(session.type),
            status=status_value,
            progress=session.progress,
            stage=session.stage,
            result=None,
            error=session.error,
        )
        return JSONResponse(status_code=202, content=pending_response.model_dump())

    return SessionResultResponse(
        session_id=session.session_id,
        task_id=session.job_id or session.session_id,
        job_id=session.job_id,
        type=_status_value(session.type),
        status=status_value,
        progress=session.progress,
        stage=session.stage,
        result=result_payload,
        error=session.error,
    )


@router.get(
    "/{session_id}/intelligence",
    response_model=SessionIntelligenceResponse,
    summary="Get persisted intelligence for a session",
)
async def get_session_intelligence(session_id: str):
    session = await SessionRepository.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if getattr(session.status, "value", session.status) != "completed":
        return SessionIntelligenceResponse(
            session_id=session_id,
            project={"status": getattr(session.status, "value", str(session.status)), "message": "Analysis in progress"},
            workflows=[],
            graph={},
            memory_profile={},
        )
    knowledge_snapshot = await build_knowledge_snapshot(session_id)
    memory_profile = await get_memory_profile(session_id)
    return SessionIntelligenceResponse(
        session_id=session_id,
        project=dict(knowledge_snapshot.get("project", {}) or {}),
        workflows=list(knowledge_snapshot.get("workflows", [])),
        graph=dict(knowledge_snapshot.get("graph", {}) or {}),
        memory_profile=dict(memory_profile or {}),
    )


@router.get(
    "/{session_id}/stream",
    summary="Stream live analysis updates",
    description="Streams real-time session progress and partial results using server-sent events.",
)
async def stream_session_status(session_id: str):
    async def event_stream():
        last_payload = None
        while True:
            session = await SessionRepository.get_by_id(session_id)
            if session is None:
                payload = {"status": "failed", "error": f"Session '{session_id}' not found"}
                yield f"data: {json.dumps(payload)}\n\n"
                break

            payload = {
                "session_id": session.session_id,
                "job_id": session.job_id,
                "type": session.type.value,
                "status": session.status.value,
                "progress": session.progress,
                "stage": session.stage,
                "title": session.title,
                "preview": session.preview,
                "source_ref": session.source_ref,
                "structure": session.structure,
                "result": (
                    session.result.model_dump() if session.status.value == "completed" and hasattr(session.result, "model_dump")
                    else session.result if session.status.value == "completed"
                    else None
                ),
                "error": session.error,
            }

            if payload != last_payload:
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                last_payload = payload

            if session.status in {"completed", "failed"} or getattr(session.status, "value", "") in {"completed", "failed"}:
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{session_id}/report",
    response_model=SessionReportResponse,
    summary="Generate project report",
    description="Builds a professional project report from stored analysis data.",
    responses={
        200: {"description": "Project report generated"},
        404: {"description": "Session not found"},
    },
)
async def get_session_report(session_id: str):
    session = await SessionRepository.get_by_id(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if getattr(session.status, "value", session.status) != "completed" or session.result is None:
        return SessionReportResponse(
            session_id=session.session_id,
            type=session.type.value,
            report="Analysis in progress",
        )

    result_dict = session.result.model_dump() if hasattr(session.result, "model_dump") else dict(session.result)
    knowledge_snapshot = await build_knowledge_snapshot(session_id)
    report = build_project_report(result_dict, session.type.value, knowledge_snapshot)

    return SessionReportResponse(
        session_id=session.session_id,
        type=session.type.value,
        report=report,
    )


@router.get(
    "/history",
    response_model=SessionHistoryResponse,
    summary="List session history",
    description="Returns paginated session history, optionally filtered by type.",
    responses={
        200: {"description": "Session history retrieved"},
    },
)
async def get_session_history(
    type: Optional[str] = Query(
        default=None,
        description="Filter by session type: code, folder, or repo",
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
):
    """List all analysis sessions with optional type filtering."""
    # Validate type filter if provided
    if type and type not in ("code", "folder", "repo"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type filter: '{type}'. Must be 'code', 'folder', or 'repo'.",
        )

    sessions, total = await SessionRepository.list_sessions(
        type_filter=type,
        skip=skip,
        limit=limit,
    )

    items = [
        SessionHistoryItem(
            session_id=s.session_id,
            type=s.type,
            title=s.title,
            status=s.status,
            preview=s.preview,
            created_at=s.created_at,
        )
        for s in sessions
    ]

    return SessionHistoryResponse(
        sessions=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.delete(
    "/{session_id}",
    summary="Delete session",
    description="Deletes a session from history.",
    responses={
        200: {"description": "Session deleted"},
        404: {"description": "Session not found"},
    },
)
async def delete_session(session_id: str):
    session = await SessionRepository.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    deleted = await SessionRepository.delete_by_id(session_id)
    if not deleted:
        raise HTTPException(status_code=500, detail=f"Failed to delete session '{session_id}'")

    return {"ok": True, "session_id": session_id}
