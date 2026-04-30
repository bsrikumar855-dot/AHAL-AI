"""
Mode-specific chat context builder.

Also exposes strict analysis-context helpers that only operate on uploaded
project files and do not pull in any stored system context.
"""

import os
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.db.mongodb import mongodb
from app.services.knowledge_store import build_knowledge_snapshot
from app.services.memory_service import get_memory_profile

logger = get_logger("services.context_builder")

MAX_CONTEXT_CHARS = 3200
MAX_CONTEXT_LINES_PER_FILE = 180
CHAT_MODES = {"code", "folder", "repo"}
BLOCKED_ANALYSIS_PATHS = [
    "app/",
    "services/",
    "core/",
    "db/",
    "api/",
    "repo_service.py",
    "code_analyzer.py",
    "folder_analyzer.py",
    "intelligence_engine.py",
    "knowledge_store.py",
    "chat_service.py",
]


def is_external_file(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    blocked = [item.lower() for item in BLOCKED_ANALYSIS_PATHS]
    return not any(item in normalized for item in blocked)


def filter_analysis_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered_files = [
        file_info
        for file_info in files
        if is_external_file(str(file_info.get("path", "")))
    ]
    return filtered_files


def validate_analysis_files(files: list[dict[str, Any]]) -> None:
    for file_info in files:
        path = str(file_info.get("path", "")).replace("\\", "/").lower()
        if "app/" in path or "services/" in path:
            raise ValueError("Context contamination detected")


def build_analysis_context(
    files: list[dict[str, Any]],
    *,
    max_chars_per_file: int = 500,
    max_context_chars: int = 3200,
) -> str:
    filtered_files = filter_analysis_files(files)
    validate_analysis_files(filtered_files)

    logger.debug(
        "Prepared analysis context",
        extra={"extra_data": {"file_count": len(filtered_files)}},
    )

    parts: list[str] = []
    total = 0
    for file_info in filtered_files:
        path = os.path.basename(str(file_info.get("path", "")).replace("\\", "/").strip())
        content = str(file_info.get("content", "") or "")
        if not path or not content.strip():
            continue
        line_count = int(file_info.get("line_count", 0) or 0)
        if line_count > MAX_CONTEXT_LINES_PER_FILE:
            continue

        lines = content.splitlines()
        truncated = "\n".join(lines[:MAX_CONTEXT_LINES_PER_FILE])
        if len(truncated) > max_chars_per_file:
            truncated = truncated[:max_chars_per_file].rstrip() + "\n...(trimmed)..."

        snippet = f"=== FILE: {path} ===\n{truncated}"
        if total + len(snippet) > max_context_chars:
            remaining = max_context_chars - total
            if remaining > 200:
                parts.append(snippet[:remaining])
            break

        parts.append(snippet)
        total += len(snippet)

    return "\n\n".join(parts)


async def _fetch_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        collection = mongodb.get_collection("sessions")
        doc = await collection.find_one({"_id": session_id})
        if doc:
            doc["session_id"] = doc.pop("_id")
        return doc
    except Exception as e:
        logger.warning(f"Failed to fetch session {session_id}: {e}")
        return None


async def _fetch_latest_session_by_type(session_type: str) -> Optional[Dict[str, Any]]:
    try:
        collection = mongodb.get_collection("sessions")
        doc = await collection.find_one(
            {"type": session_type},
            sort=[("created_at", -1)],
        )
        if doc:
            doc["session_id"] = doc.pop("_id")
        return doc
    except Exception as e:
        logger.warning(f"Failed to fetch latest {session_type} session: {e}")
        return None


def _clean_list(values: list[Any], limit: int) -> list[str]:
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


def _trim_text(value: Any, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _extract_structured_context(result: dict, chat_mode: str) -> Dict[str, Any]:
    summary_blocks = result.get("summary_blocks", {})
    if not isinstance(summary_blocks, dict):
        summary_blocks = {}

    modules = _clean_list(result.get("key_modules", []), 12)
    features = _clean_list(result.get("core_features", []), 10)
    risks = _clean_list(result.get("risks", []), 10)
    issues = _clean_list(summary_blocks.get("issues", []), 5)
    remaining = _clean_list(summary_blocks.get("remaining", []), 8)
    what = _trim_text(summary_blocks.get("what", ""), 500)
    why = _trim_text(summary_blocks.get("why", ""), 500)

    return {
        "chat_mode": chat_mode,
        "project_goal": _trim_text(result.get("project_goal", ""), 400),
        "architecture_style": _trim_text(result.get("architecture_style", ""), 300),
        "domain": _trim_text(result.get("domain", ""), 120),
        "purpose": _trim_text(result.get("purpose", ""), 260),
        "target_users": _trim_text(result.get("target_users", ""), 180),
        "system_type": _trim_text(result.get("system_type", ""), 120),
        "core_behavior": _trim_text(result.get("core_behavior", ""), 320),
        "key_capabilities": _clean_list(result.get("key_capabilities", []), 8),
        "workflow_summary": _trim_text(result.get("workflow_summary", ""), 320),
        "analysis_focus": _clean_list(result.get("analysis_focus", []), 8),
        "domain_confidence": _trim_text(result.get("domain_confidence", ""), 40),
        "validated_domain": _trim_text(result.get("validated_domain", ""), 120),
        "validated_behavior": _trim_text(result.get("validated_behavior", ""), 320),
        "verification_confidence": _trim_text(result.get("verification_confidence", ""), 40),
        "fact_entry_points": _clean_list(result.get("fact_entry_points", []), 6),
        "fact_modules": _clean_list(result.get("fact_modules", []), 8),
        "fact_actions": _clean_list(result.get("fact_actions", []), 8),
        "fact_flow": _trim_text(result.get("fact_flow", ""), 240),
        "project_type": _trim_text(result.get("project_type", ""), 40),
        "project_goal_confidence": _trim_text(result.get("project_goal_confidence", ""), 20),
        "key_modules": modules,
        "core_features": features,
        "risks": risks,
        "issues": issues,
        "remaining": remaining,
        "summary": what,
        "architecture_notes": why,
        "related_files": modules[:10],
    }


def _build_context_string(structured: Dict[str, Any], chat_mode: str) -> str:
    lines = [f"{chat_mode.upper()} ANALYSIS CONTEXT"]

    if structured.get("project_goal"):
        lines.append(f"Project Goal: {structured['project_goal']}")
    if structured.get("domain"):
        lines.append(f"Domain: {structured['domain']}")
    if structured.get("system_type"):
        lines.append(f"System Type: {structured['system_type']}")
    if structured.get("purpose"):
        lines.append(f"Purpose: {structured['purpose']}")
    if structured.get("target_users"):
        lines.append(f"Target Users: {structured['target_users']}")
    if structured.get("core_behavior"):
        lines.append(f"Core Behavior: {structured['core_behavior']}")
    if structured.get("key_capabilities"):
        lines.append("Key Capabilities: " + ", ".join(structured["key_capabilities"]))
    if structured.get("workflow_summary"):
        lines.append(f"Workflow Summary: {structured['workflow_summary']}")
    if structured.get("analysis_focus"):
        lines.append("Analysis Focus: " + ", ".join(structured["analysis_focus"]))
    if structured.get("domain_confidence"):
        lines.append(f"Domain Confidence: {structured['domain_confidence']}")
    if structured.get("validated_domain"):
        lines.append(f"Validated Domain: {structured['validated_domain']}")
    if structured.get("validated_behavior"):
        lines.append(f"Validated Behavior: {structured['validated_behavior']}")
    if structured.get("verification_confidence"):
        lines.append(f"Verification Confidence: {structured['verification_confidence']}")
    if structured.get("fact_entry_points"):
        lines.append("Fact Entry Points: " + ", ".join(structured["fact_entry_points"]))
    if structured.get("fact_modules"):
        lines.append("Fact Modules: " + ", ".join(structured["fact_modules"]))
    if structured.get("fact_actions"):
        lines.append("Fact Actions: " + ", ".join(structured["fact_actions"]))
    if structured.get("fact_flow"):
        lines.append(f"Fact Flow: {structured['fact_flow']}")
    if structured.get("project_type"):
        lines.append(f"Project Type: {structured['project_type']}")
    if structured.get("project_goal_confidence"):
        lines.append(f"Project Goal Confidence: {structured['project_goal_confidence']}")
    if structured.get("architecture_style"):
        lines.append(f"Architecture Style: {structured['architecture_style']}")
    if structured.get("summary"):
        lines.append(f"Summary: {structured['summary']}")
    if structured.get("architecture_notes"):
        lines.append(f"Architecture Notes: {structured['architecture_notes']}")
    if structured.get("key_modules"):
        lines.append("Key Modules: " + ", ".join(structured["key_modules"]))
    if structured.get("core_features"):
        lines.append("Core Features: " + ", ".join(structured["core_features"]))
    if structured.get("risks"):
        lines.append("Risks: " + ", ".join(structured["risks"]))
    if structured.get("issues"):
        lines.append("Known Issues: " + ", ".join(structured["issues"]))
    if structured.get("remaining"):
        lines.append("Open Work: " + ", ".join(structured["remaining"]))
    if structured.get("related_files"):
        lines.append("Relevant Files / Structure: " + ", ".join(structured["related_files"]))

    context = "\n".join(lines).strip()
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS]
    return context


async def build_chat_context(
    session_id: str | None = None,
    chat_mode: str = "code",
) -> Dict[str, Any]:
    """Build isolated chat context for a single mode."""
    if chat_mode not in CHAT_MODES:
        chat_mode = "code"
    if not str(session_id or "").strip():
        raise ValueError("Session ID is required")

    session = None
    if session_id:
        candidate = await _fetch_session_by_id(session_id)
        if candidate and candidate.get("type") == chat_mode and candidate.get("result"):
            session = candidate

    if not session:
        raise ValueError(f"Session '{session_id}' not found for mode '{chat_mode}'")

    if not session or not session.get("result"):
        raise ValueError(f"No stored analysis context found for session '{session_id}'")

    structured = _extract_structured_context(session["result"], chat_mode)
    structured["session_title"] = _trim_text(session.get("title", ""), 160)
    structured["session_preview"] = _trim_text(session.get("preview", ""), 400)
    knowledge_snapshot = await build_knowledge_snapshot(str(session.get("session_id", session_id or "")))
    memory_profile = await get_memory_profile(str(session.get("session_id", session_id or "")))
    project_doc = knowledge_snapshot.get("project")
    module_docs = knowledge_snapshot.get("modules", [])
    function_docs = knowledge_snapshot.get("functions", [])
    workflow_docs = knowledge_snapshot.get("workflows", [])
    if project_doc:
        structured["project_goal"] = _trim_text(project_doc.get("project_goal", structured.get("project_goal", "")), 400)
        structured["architecture_style"] = _trim_text(project_doc.get("architecture_style", structured.get("architecture_style", "")), 300)
        structured["domain"] = _trim_text(project_doc.get("domain", structured.get("domain", "")), 120)
        structured["purpose"] = _trim_text(project_doc.get("purpose", structured.get("purpose", "")), 260)
        structured["target_users"] = _trim_text(project_doc.get("target_users", structured.get("target_users", "")), 180)
        structured["system_type"] = _trim_text(project_doc.get("system_type", structured.get("system_type", "")), 120)
        structured["core_behavior"] = _trim_text(project_doc.get("core_behavior", structured.get("core_behavior", "")), 320)
        structured["key_capabilities"] = _clean_list(project_doc.get("key_capabilities", structured.get("key_capabilities", [])), 8)
        structured["workflow_summary"] = _trim_text(project_doc.get("workflow_summary", structured.get("workflow_summary", "")), 320)
        structured["analysis_focus"] = _clean_list(project_doc.get("analysis_focus", structured.get("analysis_focus", [])), 8)
        structured["domain_confidence"] = _trim_text(project_doc.get("domain_confidence", structured.get("domain_confidence", "")), 40)
        structured["validated_domain"] = _trim_text(project_doc.get("validated_domain", structured.get("validated_domain", "")), 120)
        structured["validated_behavior"] = _trim_text(project_doc.get("validated_behavior", structured.get("validated_behavior", "")), 320)
        structured["verification_confidence"] = _trim_text(project_doc.get("verification_confidence", structured.get("verification_confidence", "")), 40)
        structured["fact_entry_points"] = _clean_list(project_doc.get("fact_entry_points", structured.get("fact_entry_points", [])), 6)
        structured["fact_modules"] = _clean_list(project_doc.get("fact_modules", structured.get("fact_modules", [])), 8)
        structured["fact_actions"] = _clean_list(project_doc.get("fact_actions", structured.get("fact_actions", [])), 8)
        structured["fact_flow"] = _trim_text(project_doc.get("fact_flow", structured.get("fact_flow", "")), 240)
        structured["project_type"] = _trim_text(project_doc.get("project_type", structured.get("project_type", "")), 40)
        structured["project_goal_confidence"] = _trim_text(project_doc.get("project_goal_confidence", structured.get("project_goal_confidence", "")), 20)
        structured["summary"] = _trim_text(project_doc.get("summary", structured.get("summary", "")), 500)
        structured["related_files"] = _clean_list(project_doc.get("structure", []) or structured.get("related_files", []), 10)
    if module_docs:
        structured["key_modules"] = _clean_list(
            [module.get("name", "") or module.get("file_path", "") for module in module_docs] + structured.get("key_modules", []),
            12,
        )
    if function_docs:
        structured["core_features"] = _clean_list(
            [f"Contains {item.get('kind', 'function')} {item.get('name', '')}" for item in function_docs] + structured.get("core_features", []),
            10,
        )
    if workflow_docs:
        structured["remaining"] = _clean_list(
            [step for workflow in workflow_docs for step in workflow.get("steps", [])] + structured.get("remaining", []),
            8,
        )
    if memory_profile:
        structured["memory_focus"] = _trim_text(memory_profile.get("focus", ""), 180)
        structured["modules_viewed"] = _clean_list(memory_profile.get("modules_viewed", []), 8)
        structured["files_viewed"] = _clean_list(memory_profile.get("files_viewed", []), 8)
    context_string = _build_context_string(structured, chat_mode)

    logger.info(
        "Built chat context",
        extra={"extra_data": {
            "chat_mode": chat_mode,
            "context_chars": len(context_string),
            "session_id": session.get("session_id", ""),
        }},
    )

    return {
        "context_string": context_string,
        "structured": structured,
        "source": chat_mode,
        "session_id": str(session.get("session_id", session_id or "")),
    }
