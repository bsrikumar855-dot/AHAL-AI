"""Prompt builder for fast, grounded Workspace Assistant chat."""

from __future__ import annotations

from typing import Any


SYSTEM_PROMPT = """You are a senior software architect and AI engineer.

Answer using the provided project intelligence first and the LLM second.
Always ground explanations in the known modules, workflows, and relationships.
Return three clear sections in this order:
1. Summary
2. Developer Explanation
3. Architect Explanation
Each section should explain why the system is designed this way, not just what it does.
Never use broken-system language. Prefer phrases like "partial analysis completed" and "using inferred insights".
If a detail is missing, infer carefully from the available architecture, modules, and summary.
Give practical, engineer-friendly answers with clear reasoning.
"""

_MAX_LIST_ITEMS = 6
_MAX_TEXT_CHARS = 320
_MAX_RAW_CONTEXT_CHARS = 1200


def _stringify_list(values: list[Any], empty_value: str = "Not available") -> str:
    cleaned = [" ".join(str(value).split()) for value in values if str(value).strip()][: _MAX_LIST_ITEMS]
    return ", ".join(cleaned) if cleaned else empty_value


def _clip(value: Any, limit: int = _MAX_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "Not available"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_memory(history: list[dict[str, Any]]) -> str:
    if not history:
        return "No recent conversation history."

    parts: list[str] = []
    for item in history[-3:]:
        question = " ".join(str(item.get("question", "")).split())
        answer = " ".join(str(item.get("answer", "")).split())
        if question:
            parts.append(f"User: {question}")
        if answer:
            clipped = answer if len(answer) <= 240 else answer[:237].rstrip() + "..."
            parts.append(f"Assistant: {clipped}")

    return "\n".join(parts) if parts else "No recent conversation history."


def build_chat_prompt(
    *,
    chat_mode: str,
    question: str,
    structured_context: dict[str, Any],
    raw_context: str,
    recent_history: list[dict[str, Any]],
    reasoning_context: dict[str, Any] | None = None,
) -> str:
    """Build the final raw-text chat prompt sent to the LLM."""
    reasoning_context = reasoning_context or {}
    explanations = reasoning_context.get("explanations", {}) if isinstance(reasoning_context.get("explanations", {}), dict) else {}
    prompt_context = (
        f"Mode: {chat_mode}\n"
        f"Intent: {_clip(reasoning_context.get('intent', 'structure'), 80)}\n"
        f"Goal: {_clip(structured_context.get('project_goal'))}\n"
        f"Architecture: {_clip(structured_context.get('architecture_style'))}\n"
        f"Summary: {_clip(structured_context.get('summary'))}\n"
        f"Architecture Notes: {_clip(structured_context.get('architecture_notes'))}\n"
        f"Key Modules: {_stringify_list(structured_context.get('key_modules', []))}\n"
        f"Core Features: {_stringify_list(structured_context.get('core_features', []))}\n"
        f"Risks: {_stringify_list(structured_context.get('risks', []))}\n"
        f"Known Issues: {_stringify_list(structured_context.get('issues', []))}\n"
        f"Open Work: {_stringify_list(structured_context.get('remaining', []))}\n"
        f"File Structure: {_stringify_list(structured_context.get('related_files', []))}\n"
        f"Relevant Workflows: {_stringify_list([item.get('name', '') for item in reasoning_context.get('relevant_workflows', []) if item.get('name')], 'Not available')}\n"
        f"Relevant Graph Paths: {_stringify_list(reasoning_context.get('graph_paths', []), 'Not available')}\n"
        f"Memory Focus: {_clip(structured_context.get('memory_focus', ''), 140)}\n"
        f"Viewed Modules: {_stringify_list(structured_context.get('modules_viewed', []), 'Not available')}\n"
        f"Viewed Files: {_stringify_list(structured_context.get('files_viewed', []), 'Not available')}\n"
        f"Engineer Summary: {_clip(explanations.get('summary', ''), 220)}\n"
        f"Developer View: {_clip(explanations.get('developer', ''), 320)}\n"
        f"Architect View: {_clip(explanations.get('architect', ''), 320)}\n"
        f"Session Title: {_clip(structured_context.get('session_title'), 120)}\n"
        f"Session Preview: {_clip(structured_context.get('session_preview'), 180)}"
    )
    compact_raw_context = _clip(
        reasoning_context.get("context_string", "") or raw_context,
        _MAX_RAW_CONTEXT_CHARS,
    )

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"ANALYSIS CONTEXT:\n{prompt_context}\n\n"
        f"COMPACT ANALYSIS SNAPSHOT:\n{compact_raw_context}\n\n"
        f"RECENT CONVERSATION:\n{_format_memory(recent_history)}\n\n"
        f"USER QUESTION:\n{question.strip()}\n\n"
        "ASSISTANT ANSWER:"
    )
