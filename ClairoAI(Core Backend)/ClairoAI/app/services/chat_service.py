"""Production chat service for the Workspace Assistant."""

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.db.mongodb import mongodb
from app.services.chat_prompt_builder import build_chat_prompt
from app.services.context_builder import CHAT_MODES, build_chat_context
from app.services.memory_service import record_chat_turn
from app.services.reasoning_engine import build_reasoning_context, detect_question_intent
from app.services.llm_handler import generate_chat_response_async

logger = get_logger("services.chat")

_CHAT_TIMEOUT_SECONDS = 60
_SHORT_MEMORY_LIMIT = 3
_DEFAULT_LLM_MODE = "online"
_CHAT_CACHE_TTL_SECONDS = 600
_CHAT_RESPONSE_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}


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


def _build_cache_key(session_id: str, chat_mode: str, question: str, structured: Dict[str, Any]) -> str:
    signature = "|".join([
        session_id,
        chat_mode,
        " ".join(question.strip().lower().split()),
        structured.get("project_goal", ""),
        structured.get("architecture_style", ""),
        "|".join(structured.get("key_modules", [])[:6]),
        "|".join(structured.get("core_features", [])[:6]),
        structured.get("summary", ""),
    ])
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _get_cached_response(cache_key: str) -> Dict[str, Any] | None:
    cached = _CHAT_RESPONSE_CACHE.get(cache_key)
    if not cached:
        return None

    expires_at, payload = cached
    if expires_at <= time.time():
        _CHAT_RESPONSE_CACHE.pop(cache_key, None)
        return None

    return dict(payload)


def _set_cached_response(cache_key: str, payload: Dict[str, Any]) -> None:
    _CHAT_RESPONSE_CACHE[cache_key] = (time.time() + _CHAT_CACHE_TTL_SECONDS, dict(payload))

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

    sections: list[str] = [
        "Based on the latest analyzed project context, here is the best grounded explanation.",
        f"The project appears to be centered on {goal or 'the analyzed application workflow'}, with a {architecture or chat_mode + ' oriented structure'}."
    ]

    if summary:
        sections.append(summary)
    if modules:
        sections.append(f"The most important modules in this context are {', '.join(modules)}, which suggests the system organizes {focus}.")
    if features:
        sections.append(f"Key implemented capabilities include {', '.join(features)}.")
    if risks or issues:
        combined = risks + [item for item in issues if item not in risks]
        sections.append(f"Important caveats to keep in mind are {', '.join(combined[:4])}.")
    if remaining:
        sections.append(f"Open work or likely next improvements include {', '.join(remaining)}.")

    answer = "\n\n".join(sections).strip()
    return {
        "answer": answer,
        "source": chat_mode,
        "related_files": _clean_list(structured.get("related_files", []), 6),
        "modules_involved": modules,
        "session_id": session_id,
        "suggested_questions": _build_suggested_questions(chat_mode, modules, reasoning.get("relevant_workflows", [])),
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

    parts = [
        f"Summary: {str(explanations.get('summary', '')).strip() or str(structured.get('summary', '')).strip() or 'The analyzed system is grounded in the stored project knowledge.'}",
        f"Developer Explanation: {str(explanations.get('developer', '')).strip() or 'The developer-facing explanation is based on the stored modules and workflows.'}",
        f"Architect Explanation: {str(explanations.get('architect', '')).strip() or 'The architect-facing explanation is based on the detected architecture and dependency relationships.'}",
    ]
    if workflows:
        workflow_steps = []
        for workflow in workflows[:2]:
            name = workflow.get("name", "Primary Flow")
            steps = " -> ".join(_clean_list(workflow.get("steps", []), 8))
            workflow_steps.append(f"{name}: {steps}")
        if workflow_steps:
            parts.append("Workflow Details: " + " | ".join(workflow_steps))
    if graph_paths:
        parts.append("Relationship Paths: " + " | ".join(graph_paths[:4]))
    if modules:
        parts.append("Modules Involved: " + ", ".join(modules))

    answer = "\n\n".join(parts)
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
    
    print(f"\n[CHAT] REQUEST: mode={chat_mode} session={session_id}")
    print(f"[CHAT] QUESTION: {question}")

    # 1. Load context from session or latest analysis
    context_data = await build_chat_context(session_id=session_id, chat_mode=chat_mode)
    context_string = context_data.get("context_string", "")
    structured = context_data.get("structured", {})
    resolved_session_id = str(context_data.get("session_id", session_id or ""))
    reasoning = await build_reasoning_context(resolved_session_id, question, chat_mode) if resolved_session_id else {
        "intent": detect_question_intent(question, chat_mode),
        "relevant_modules": [],
        "relevant_workflows": [],
        "graph_paths": [],
        "explanations": {},
        "context_string": "",
    }

    if not context_string:
        print("[CHAT] No stored analysis context found for this request.")
        context_string = "No stored analysis context was found. Answer with the best engineering guidance possible and clearly infer from the question."

    # 2. Get recent history for memory
    history = await get_chat_history(resolved_session_id, chat_mode=chat_mode, limit=_SHORT_MEMORY_LIMIT)
    history_tail = history[-_SHORT_MEMORY_LIMIT:]
    cache_key = _build_cache_key(resolved_session_id, chat_mode, question, structured)
    cached = _get_cached_response(cache_key)
    if cached:
        cached["session_id"] = resolved_session_id
        print("[CHAT] Cache hit")
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

    print(f"[CHAT] DEBUG - PROMPT (first 500 chars):\n{prompt[:500]}...")
    print("[CHAT] STATUS: Thinking...")

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

        print(f"[CHAT] DEBUG - LLM RESPONSE:\n{response_text[:300]}...")

        # metadata extrapolation from grounding
        related_files = _clean_list(structured.get("related_files", []), 6)
        modules_involved = _clean_list(structured.get("key_modules", []), 6)

        result = {
            "answer": response_text.strip(),
            "source": chat_mode,
            "related_files": related_files,
            "modules_involved": modules_involved,
            "session_id": resolved_session_id,
            "suggested_questions": _build_suggested_questions(chat_mode, modules_involved, reasoning.get("relevant_workflows", [])),
        }
        _set_cached_response(cache_key, result)

    except Exception as e:
        logger.error(f"Chat execution failed, serving fallback: {e}")
        print(f"[CHAT] STATUS: Analyzing deeply, this may take a few seconds...")
        result = _knowledge_first_fallback(question, chat_mode, structured, reasoning, resolved_session_id)
        _set_cached_response(cache_key, result)

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    print(f"[CHAT] COMPLETED in {elapsed_ms}ms\n")

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
