"""Production chat service for the Workspace Assistant."""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.mongodb import mongodb
from app.services.chat_prompt_builder import build_chat_prompt
from app.services.context_builder import CHAT_MODES, build_chat_context
from app.services.memory_service import record_chat_turn
from app.services.reasoning_engine import build_reasoning_context, detect_question_intent
from app.services.llm_handler import generate_chat_response_async

logger = get_logger("services.chat")

_CHAT_TIMEOUT_SECONDS = 30
_SHORT_MEMORY_LIMIT = 3
_DEFAULT_LLM_MODE = "online"
_CHAT_RESPONSE_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}
_BANNED_CHAT_PHRASES = (
    "i am grounding this answer",
    "based on the provided context",
    "based on the latest analyzed project context",
    "refining the deeper answer",
    "analyzing",
    "from the system",
)
_SENSITIVE_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\[^\s,;]+"),
    re.compile(r"(?<!\w)/(?:home|users|var|etc|app|tmp)/[^\s,;]+", re.IGNORECASE),
    re.compile(r"\b[\w.-]*\.env(?:\.[\w.-]+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
)


def _normalize_chat_mode(chat_mode: str | None) -> str:
    candidate = str(chat_mode or "code").strip().lower()
    return candidate if candidate in CHAT_MODES else "code"


def _clean_list(values: list[Any], limit: int = 10) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value).split())
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


def _build_cache_key(
    session_id: str,
    chat_mode: str,
    question: str,
    structured: Dict[str, Any],
    recent_history: list[Dict[str, Any]],
) -> str:
    history_signature = "|".join(
        f"{item.get('question', '')}:{item.get('answer', '')}"
        for item in recent_history[-_SHORT_MEMORY_LIMIT:]
    )
    signature = "|".join([
        session_id,
        chat_mode,
        " ".join(question.strip().lower().split()),
        history_signature,
        structured.get("project_goal", ""),
        structured.get("architecture_style", ""),
        "|".join(structured.get("key_modules", [])[:6]),
        "|".join(structured.get("core_features", [])[:6]),
        structured.get("summary", ""),
    ])
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _get_cached_response(cache_key: str) -> Dict[str, Any] | None:
    settings = get_settings()
    if not settings.CHAT_CACHE_ENABLED:
        return None

    cached = _CHAT_RESPONSE_CACHE.get(cache_key)
    if not cached:
        return None

    expires_at, payload = cached
    if expires_at <= time.time():
        _CHAT_RESPONSE_CACHE.pop(cache_key, None)
        return None

    return dict(payload)


def _set_cached_response(cache_key: str, payload: Dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.CHAT_CACHE_ENABLED:
        return

    ttl_seconds = max(0, int(settings.CHAT_CACHE_TTL_SECONDS))
    if ttl_seconds == 0:
        return

    _CHAT_RESPONSE_CACHE[cache_key] = (time.time() + ttl_seconds, dict(payload))

    if len(_CHAT_RESPONSE_CACHE) > 256:
        oldest_key = min(_CHAT_RESPONSE_CACHE, key=lambda key: _CHAT_RESPONSE_CACHE[key][0])
        _CHAT_RESPONSE_CACHE.pop(oldest_key, None)


def _build_suggested_questions(chat_mode: str, modules: list[str], workflows: list[dict[str, Any]]) -> list[str]:
    suggestions = [
        "Explain system workflow",
        "What are the main risks?",
        "How can this be improved?",
    ]
    if workflows:
        suggestions.insert(0, f"Explain {workflows[0].get('name', 'the primary workflow')}")
    elif modules:
        suggestions.insert(0, f"Why is {modules[0]} important?")

    if chat_mode == "code":
        suggestions.append("What logic path should I review first?")
    elif chat_mode == "folder":
        suggestions.append("How is responsibility split across folders?")
    else:
        suggestions.append("What architectural decisions shape this repository?")

    return _clean_list(suggestions, 5)


def _sanitize_chat_answer(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""

    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[redacted]", text)

    filtered_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(phrase in lowered for phrase in _BANNED_CHAT_PHRASES):
            continue
        if lowered in {"summary", "developer explanation", "architect explanation"}:
            continue
        filtered_lines.append(line)

    if not filtered_lines:
        return ""

    return "\n".join(filtered_lines[:4])


def _fallback_chat_response(question: str, chat_mode: str, structured: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    modules = _clean_list(structured.get("key_modules", []), 6)
    features = _clean_list(structured.get("core_features", []), 5)
    risks = _clean_list(structured.get("risks", []), 4)
    remaining = _clean_list(structured.get("remaining", []), 4)
    issues = _clean_list(structured.get("issues", []), 4)
    summary = str(structured.get("summary", "")).strip()
    architecture = str(structured.get("architecture_style", "")).strip()
    goal = str(structured.get("project_goal", "")).strip()

    focus = "system design and responsibilities"
    lowered_question = question.lower()
    if "folder" in lowered_question or "structure" in lowered_question:
        focus = "folder layout and how responsibilities appear to be split"
    elif "risk" in lowered_question or "issue" in lowered_question:
        focus = "implementation risks and likely weak points"
    elif "feature" in lowered_question or "what does" in lowered_question:
        focus = "implemented capabilities and likely user-facing behavior"

    bullets: list[str] = []
    if goal:
        bullets.append(f"Main focus: {goal}")
    elif architecture:
        bullets.append(f"Structure: {architecture}")
    elif summary:
        bullets.append(summary)
    elif modules:
        bullets.append(f"Key parts: {', '.join(modules[:3])}")
    else:
        bullets.append(f"This looks focused on {focus}.")

    if features:
        bullets.append(f"Main behavior: {', '.join(features[:3])}")
    if risks or issues:
        combined = risks + [item for item in issues if item not in risks]
        bullets.append(f"Main risk: {', '.join(combined[:3])}")
    elif remaining:
        bullets.append(f"Next step: {remaining[0]}")

    answer = _sanitize_chat_answer("\n".join(bullets))
    return {
        "answer": answer,
        "source": chat_mode,
        "related_files": _clean_list(structured.get("related_files", []), 6),
        "modules_involved": modules,
        "session_id": session_id,
        "suggested_questions": _build_suggested_questions(chat_mode, modules, []),
    }


def _knowledge_first_fallback(
    question: str,
    chat_mode: str,
    structured: Dict[str, Any],
    reasoning: Dict[str, Any],
    session_id: str,
) -> Dict[str, Any]:
    explanations = reasoning.get("explanations", {}) if isinstance(reasoning.get("explanations", {}), dict) else {}
    workflows = reasoning.get("relevant_workflows", [])
    graph_paths = reasoning.get("graph_paths", [])
    modules = _clean_list(
        [module.get("name", "") for module in reasoning.get("relevant_modules", [])] + structured.get("key_modules", []),
        8,
    )

    parts: list[str] = []
    summary = str(explanations.get("summary", "")).strip() or str(structured.get("summary", "")).strip()
    developer = str(explanations.get("developer", "")).strip()
    architect = str(explanations.get("architect", "")).strip()

    if summary:
        parts.append(summary)
    if developer:
        parts.append(developer)
    elif modules:
        parts.append(f"Key parts: {', '.join(modules[:3])}")
    if architect:
        parts.append(architect)
    elif graph_paths:
        parts.append(f"Main flow: {graph_paths[0]}")
    elif workflows:
        first = workflows[0]
        steps = " -> ".join(_clean_list(first.get("steps", []), 4))
        if steps:
            parts.append(f"Flow: {steps}")

    answer = _sanitize_chat_answer("\n".join(parts))
    return {
        "answer": answer,
        "source": chat_mode,
        "related_files": _clean_list(structured.get("related_files", []), 8),
        "modules_involved": modules,
        "session_id": session_id,
    }


async def chat_ask(
    question: str,
    session_id: Optional[str] = None,
    mode: str = "code",
) -> Dict[str, Any]:
    """Handle a conversational request with full grounding and memory."""
    started = time.monotonic()
    chat_mode = _normalize_chat_mode(mode)
    requested_session_id = str(session_id or "").strip()

    if not requested_session_id:
        raise ValueError("Session ID is required")

    # 1. Load context from the requested session only
    context_data = await build_chat_context(session_id=requested_session_id, chat_mode=chat_mode)
    context_string = context_data.get("context_string", "")
    structured = context_data.get("structured", {})
    resolved_session_id = str(context_data.get("session_id", requested_session_id))
    if not resolved_session_id or resolved_session_id != requested_session_id:
        raise ValueError("Session ID is required")

    reasoning = await build_reasoning_context(resolved_session_id, question, chat_mode)

    if not context_string:
        raise ValueError("No stored analysis context found for this session")

    # 2. Get recent history for memory
    history = await get_chat_history(resolved_session_id, chat_mode=chat_mode, limit=_SHORT_MEMORY_LIMIT)
    history_tail = history[-_SHORT_MEMORY_LIMIT:]
    cache_key = _build_cache_key(resolved_session_id, chat_mode, question, structured, history_tail)
    cached = _get_cached_response(cache_key)
    if cached:
        cached["session_id"] = resolved_session_id
        return cached

    # 3. Build the technical grounding prompt
    prompt = build_chat_prompt(
        chat_mode=chat_mode,
        question=question,
        structured_context=structured,
        raw_context=context_string,
        recent_history=history_tail,
        reasoning_context=reasoning,
    )

    # 4. Generate LLM response (Raw Text)
    try:
        llm_task = asyncio.create_task(
            generate_chat_response_async(
                prompt,
                mode=_DEFAULT_LLM_MODE,
                timeout=_CHAT_TIMEOUT_SECONDS,
            )
        )
        response_text = await asyncio.wait_for(llm_task, timeout=_CHAT_TIMEOUT_SECONDS + 10)

        if not response_text or not response_text.strip():
            raise ValueError("Empty LLM response")

        related_files = _clean_list(structured.get("related_files", []), 6)
        modules_involved = _clean_list(structured.get("key_modules", []), 6)

        result = {
            "answer": _sanitize_chat_answer(response_text.strip()) or _sanitize_chat_answer(_knowledge_first_fallback(question, chat_mode, structured, reasoning, resolved_session_id)["answer"]),
            "source": chat_mode,
            "related_files": related_files,
            "modules_involved": modules_involved,
            "session_id": resolved_session_id,
            "suggested_questions": _build_suggested_questions(chat_mode, modules_involved, reasoning.get("relevant_workflows", [])),
        }
        _set_cached_response(cache_key, result)

    except Exception as e:
        logger.error(f"Chat execution failed, serving fallback: {e}")
        result = _knowledge_first_fallback(question, chat_mode, structured, reasoning, resolved_session_id)
        _set_cached_response(cache_key, result)

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    logger.info(f"Chat completed in {elapsed_ms}ms")

    # 5. Persistent history
    await _store_chat_history(resolved_session_id, question, result["answer"], chat_mode)
    await record_chat_turn(
        resolved_session_id,
        chat_mode,
        question,
        result["answer"],
        result.get("modules_involved", []),
    )
    
    return result


async def _store_chat_history(
    session_id: Optional[str],
    question: str,
    answer: str,
    chat_mode: str,
) -> None:
    """Non-fatal storage of chat history."""
    try:
        collection = mongodb.get_collection("chat_history")
        await collection.insert_one({
            "session_id": session_id or "",
            "chat_mode": chat_mode,
            "question": question,
            "answer": answer,
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"History storage failed: {e}")


async def get_chat_history(
    session_id: str,
    chat_mode: str,
    limit: int = 20,
) -> list[Dict[str, Any]]:
    """Retrieve mode-specific chat history sorted by time."""
    try:
        collection = mongodb.get_collection("chat_history")
        cursor = collection.find(
            {"session_id": session_id, "chat_mode": _normalize_chat_mode(chat_mode)},
            {"_id": 0},
        ).sort("timestamp", -1).limit(limit)

        history = []
        async for doc in cursor:
            history.append({
                "question": doc.get("question", ""),
                "answer": doc.get("answer", ""),
                "timestamp": doc.get("timestamp", "").isoformat()
                if isinstance(doc.get("timestamp"), datetime)
                else str(doc.get("timestamp", "")),
            })

        return list(reversed(history))
    except Exception as e:
        logger.warning(f"History fetch failed: {e}")
        return []
