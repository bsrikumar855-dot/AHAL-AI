"""
POST /api/v1/chat/ask
GET  /api/v1/chat/history/{session_id}?mode=code|folder|repo
POST /api/v1/chat/context
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.chat_service import chat_ask, get_chat_history
from app.core.logging import get_logger
from app.services.memory_service import update_session_focus

logger = get_logger("api.chat")
router = APIRouter()


# ── Request / Response Schemas ───────────────────────────────────


class ChatAskRequest(BaseModel):
    """Request body for chat question."""
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID to fetch context from. If empty, uses latest mode-specific analysis.",
    )
    question: str = Field(
        min_length=1,
        max_length=2000,
        description="The question to ask about analyzed code/project",
    )
    mode: str = Field(
        default="code",
        description="Chat mode: code | folder | repo",
    )


class ChatAskResponse(BaseModel):
    """Response for a chat question."""
    answer: str
    source: str = Field(description="code | folder | repo")
    related_files: list[str] = []
    modules_involved: list[str] = []
    session_id: str = ""
    suggested_questions: list[str] = []


class ChatHistoryItem(BaseModel):
    """Single chat history entry."""
    question: str
    answer: str
    timestamp: str


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    session_id: str
    history: list[ChatHistoryItem]
    count: int


class ChatContextSyncRequest(BaseModel):
    session_id: str
    mode: str = "code"
    focus: str = ""
    module: str = ""
    workflow: str = ""
    file_path: str = ""


class ChatContextSyncResponse(BaseModel):
    ok: bool = True
    focus: str = ""
    modules_viewed: list[str] = []
    workflows_viewed: list[str] = []
    files_viewed: list[str] = []


# ── Endpoints ────────────────────────────────────────────────────


@router.post(
    "/ask",
    response_model=ChatAskResponse,
    status_code=200,
    summary="Ask a question about analyzed code",
    description="Ask a context-aware question using stored analysis results as grounding.",
    responses={
        200: {"description": "Answer generated successfully"},
        422: {"description": "Invalid input"},
    },
)
async def ask_question(request: ChatAskRequest):
    logger.info(f"Chat question received: {request.question[:80]}...")
    print(f"[CHAT API] Question: {request.question[:100]}")
    print(f"[CHAT API] session_id={request.session_id}, mode={request.mode}")

    try:
        result = await chat_ask(
            question=request.question,
            session_id=request.session_id,
            mode=request.mode,
        )

        return ChatAskResponse(
            answer=result.get("answer", ""),
            source=result.get("source", request.mode),
            related_files=result.get("related_files", []),
            modules_involved=result.get("modules_involved", []),
            session_id=result.get("session_id", ""),
            suggested_questions=result.get("suggested_questions", []),
        )

    except Exception as e:
        logger.error(f"Chat endpoint failed: {e}")
        print(f"[CHAT API] ERROR: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "A grounded response is still being refined. Please try again in a moment.",
                "details": str(e),
            },
        )


@router.get(
    "/history/{session_id}",
    response_model=ChatHistoryResponse,
    summary="Get chat history for a session",
    description="Retrieve the chat history for a specific session.",
)
async def chat_history(
    session_id: str,
    mode: str = Query(default="code", description="code | folder | repo"),
):
    """Fetch chat history for a given session."""
    logger.info(f"Chat history requested for session {session_id} mode={mode}")

    try:
        history = await get_chat_history(session_id, chat_mode=mode, limit=50)
        items = [
            ChatHistoryItem(
                question=h.get("question", ""),
                answer=h.get("answer", ""),
                timestamp=h.get("timestamp", ""),
            )
            for h in history
        ]

        return ChatHistoryResponse(
            session_id=session_id,
            history=items,
            count=len(items),
        )

    except Exception as e:
        logger.error(f"Chat history fetch failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Chat history is still syncing. Please try again in a moment.",
                "details": str(e),
            },
        )


@router.post(
    "/context",
    response_model=ChatContextSyncResponse,
    summary="Sync live chat focus context",
    description="Updates the session memory profile based on the module, file, or workflow the user is exploring.",
)
async def sync_chat_context(request: ChatContextSyncRequest):
    try:
        profile = await update_session_focus(
            request.session_id,
            request.mode,
            focus=request.focus,
            module=request.module,
            workflow=request.workflow,
            file_path=request.file_path,
        )
        return ChatContextSyncResponse(
            ok=True,
            focus=str(profile.get("focus", "")),
            modules_viewed=list(profile.get("modules_viewed", [])),
            workflows_viewed=list(profile.get("workflows_viewed", [])),
            files_viewed=list(profile.get("files_viewed", [])),
        )
    except Exception as e:
        logger.error(f"Chat context sync failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Live chat context is still syncing. Please try again in a moment.",
                "details": str(e),
            },
        )
