"""
POST /api/v1/query

Accepts a natural language question and returns a grounded answer
based on stored summaries. Uses the fast Gemma 2B model.
"""

from fastapi import APIRouter

from app.db.schemas import QueryRequest, QueryResponse
from app.services.query_engine import QueryEngine
from app.core.logging import get_logger
from app.core.exceptions import InputValidationError

logger = get_logger("api.query")
router = APIRouter()


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Query stored knowledge",
    description="Ask a question and get an answer grounded in stored summaries.",
    responses={
        200: {"description": "Answer generated"},
        422: {"description": "Invalid query"},
    },
)
async def query_knowledge(request: QueryRequest):
    """
    Generate a grounded answer from stored summaries.

    The query engine retrieves relevant summaries via text search,
    optionally augments with RAG context, and generates an answer
    using the fast LLM model with a strict "context only" prompt.
    """
    if not request.question.strip():
        raise InputValidationError("Question cannot be empty")

    logger.info(
        "Query request received",
        extra={"extra_data": {
            "question_length": len(request.question),
            "project_filter": request.project,
            "mode": request.mode,
        }},
    )

    engine = QueryEngine()
    response = await engine.answer(
        question=request.question,
        project=request.project,
        max_context=request.max_context_summaries,
        repo_id=request.repo_id,
        mode=request.mode,
    )

    return response
