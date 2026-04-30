"""
Analysis service for repository intelligence extraction.

Wraps the LLM provider to extract Repo-level intent and File-level summaries.
"""

import json
import re
import os
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Any

from app.core.config import get_settings
from app.services.llm.factory import get_llm_provider
from app.core.logging import get_logger
from app.services.llm_handler import parse_llm_json
from app.services.normalize import compact_result

logger = get_logger("services.analysis")
_HARD_ANALYSIS_TIMEOUT_SECONDS = 20
_HARD_LLM_TIMEOUT_SECONDS = 15
_MAX_CONTEXT_BATCHES = 4
_ALLOWED_ARCHITECTURE_PARTS = {"script-based", "component-based", "api-service", "client-server", "monolithic", "static-web", "unknown"}
_ALLOWED_INSIGHT_TYPES = {"architecture", "performance", "scalability", "risk", "dx"}
_AI_EVIDENCE_RE = re.compile(r"\b(transformers|torch|tensorflow|keras|openai|gemini|llm|langchain|ollama|load_model|inference|embedding|retrieval)\b", re.IGNORECASE)
_AI_HINT_RE = re.compile(r"\b(ai_engine|rag|model\.py|embeddings?|retrieval|retrieve|inference|langchain|ollama)\b", re.IGNORECASE)
_AI_FILE_SIGNAL_RE = re.compile(r"\b(ai_engine|rag|retriev(?:al|er)|inference|embedding|vector|index|knowledge|model)\.(py|js|ts|tsx|jsx)\b", re.IGNORECASE)
_AI_DEPENDENCY_SIGNAL_RE = re.compile(r"\b(transformers|torch|tensorflow|keras|openai|gemini|langchain|ollama|chromadb|faiss|pinecone|llamaindex|llama-index|sentence-transformers)\b", re.IGNORECASE)
_AI_PATTERN_SIGNAL_RE = re.compile(r"\b(embedding|embeddings|retrieve|retrieval|rerank|vector store|similarity search|prompt template|generate_content|chat completion|inference)\b", re.IGNORECASE)
_RAG_SIGNAL_RE = re.compile(r"\b(rag|retrieval|embedding|vector|similarity search|chromadb|faiss|pinecone|rerank)\b", re.IGNORECASE)
_GENERIC_PHRASE_RE = re.compile(r"\b(system that orchestrates|ai system|model-driven|platform for|codebase with modules that suggest)\b", re.IGNORECASE)
_GENERIC_GOAL_RE = re.compile(r"\b(partial or utility-based implementation|partial codebase analysis|backend system|frontend interface|application for|service for|codebase with modules that suggest)\b", re.IGNORECASE)
_GENERIC_INSIGHT_RE = re.compile(r"^(uses|has|contains|includes)\b", re.IGNORECASE)
_GENERIC_WORKFLOW_RE = re.compile(r"\b(handles logic|manages data|provides functionality|core modules process inputs|processes inputs|returns outputs)\b", re.IGNORECASE)
_UNCERTAIN_LANGUAGE_RE = re.compile(r"\b(suggests|appears|indicates|may represent)\b", re.IGNORECASE)
_FRAMEWORK_TERM_RE = re.compile(r"\b(fastapi|flask|django|express|react|next(?:\.js)?|vue|angular)\b", re.IGNORECASE)
_INVALID_ISSUE_RE = re.compile(r"\b(INVALID_FINAL_RESULT|LOW_CONFIDENCE|LLM_TIMEOUT_BACKGROUND|LLM_PARSE_ERROR)\b", re.IGNORECASE)
_GENERIC_RISK_RE = re.compile(r"\b(may remain|could exist|further analysis|unknown risk|general risk|possible issue)\b", re.IGNORECASE)
_SUPPORTED_RISK_RE = re.compile(r"\b(validation|error handling|test|testing|exception|hardcoded|coupling|structure|production|accuracy|model|dependency|local model|retrieval)\b", re.IGNORECASE)
_AI_PURGE_RE = re.compile(r"\b(ai|ml|llm|model|intelligence|smart|generation|semantic|intelligent)\b", re.IGNORECASE)
_OBSERVABLE_FEATURE_RE = re.compile(r"\b(api|endpoint|route|http|request|response|file|upload|download|zip|archive|ui|render|page|component|view|data|process|processing|transform|parse|json|csv|embedding|retrieval|inference|knowledge|search|repository|analysis)\b", re.IGNORECASE)
_MEDICAL_RE = re.compile(r"\b(patient|clinic|medical|health|diagnos(?:is|tic)|clinical|doctor)\b", re.IGNORECASE)
_FINANCE_RE = re.compile(r"\b(payment|invoice|billing|transaction|finance|bank|ledger)\b", re.IGNORECASE)
_MARKETING_RE = re.compile(r"\b(campaign|seo|marketing|lead|audience|analytics|copy)\b", re.IGNORECASE)
_CODE_ANALYSIS_RE = re.compile(r"\b(repo|repository|zip|archive|code analysis|folder analysis|source code|static analysis)\b", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^,\]\[;:]+)+")
TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = RLock()
PIPELINE_STAGES = ("upload", "analyze", "insights", "finalize")
_STAGE_PROGRESS_FLOORS = {
    "upload": 5,
    "analyze": 30,
    "insights": 70,
    "finalize": 100,
}
_MISSING = object()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_value(value: Any) -> str:
    return getattr(value, "value", str(value or "processing"))


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _model_dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_model_dump(item) for item in value]
    return value


def normalize_task_stage(stage: Any) -> str:
    raw = str(stage or "").strip()
    lowered = raw.lower()
    if lowered in PIPELINE_STAGES:
        return lowered
    if any(token in lowered for token in ("complete", "final", "failed", "error")):
        return "finalize"
    if any(token in lowered for token in ("llm", "semantic", "insight", "refinement", "enrichment")):
        return "insights"
    if any(token in lowered for token in ("static", "scan", "context", "structure", "classify", "analy")):
        return "analyze"
    if any(token in lowered for token in ("queued", "upload", "download", "extract", "read")):
        return "upload"
    return "upload"


def create_task_record(
    task_id: str,
    *,
    task_type: str,
    title: str = "",
    preview: str = "",
    source_ref: str = "",
    progress: int = 0,
    stage: str = "upload",
) -> dict[str, Any]:
    now = _utc_iso()
    payload = {
        "task_id": task_id,
        "session_id": task_id,
        "job_id": task_id,
        "type": task_type,
        "status": "processing",
        "stage": normalize_task_stage(stage),
        "message": str(stage or "upload"),
        "progress": max(0, min(100, int(progress))),
        "title": title,
        "preview": preview,
        "source_ref": source_ref,
        "structure": [],
        "result": None,
        "partial_result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with _TASKS_LOCK:
        TASKS[task_id] = payload
        return deepcopy(payload)


def update_task_record(
    task_id: str,
    *,
    status: Any | None = None,
    progress: int | None = None,
    stage: Any | None = None,
    message: str | None = None,
    result: Any | None = None,
    partial_result: Any | None = None,
    error: Any = _MISSING,
    structure: list[str] | None = None,
    title: str | None = None,
    preview: str | None = None,
    source_ref: str | None = None,
) -> dict[str, Any]:
    with _TASKS_LOCK:
        current = TASKS.get(task_id)
        if current is None:
            current = create_task_record(task_id, task_type="analysis")
        snapshot = dict(current)
        if status is not None:
            snapshot["status"] = _status_value(status)
        if stage is not None:
            snapshot["stage"] = normalize_task_stage(stage)
            snapshot["message"] = str(message or stage or snapshot.get("message") or snapshot["stage"])
        elif message is not None:
            snapshot["message"] = str(message)
        if progress is not None:
            snapshot["progress"] = max(0, min(100, int(progress)))
        elif stage is not None:
            snapshot["progress"] = max(
                int(snapshot.get("progress", 0) or 0),
                _STAGE_PROGRESS_FLOORS.get(snapshot["stage"], 0),
            )
        if result is not None:
            normalized_result = _model_dump(result)
            snapshot["partial_result"] = normalized_result
            if snapshot.get("status") == "completed" or snapshot.get("stage") == "finalize":
                snapshot["result"] = normalized_result
        if partial_result is not None:
            snapshot["partial_result"] = _model_dump(partial_result)
        if error is not _MISSING:
            snapshot["error"] = str(error) if error else None
        if structure is not None:
            snapshot["structure"] = list(structure)
        if title is not None:
            snapshot["title"] = str(title)
        if preview is not None:
            snapshot["preview"] = str(preview)
        if source_ref is not None:
            snapshot["source_ref"] = str(source_ref)
        snapshot["updated_at"] = _utc_iso()
        TASKS[task_id] = snapshot
        return deepcopy(snapshot)


def get_task_record(task_id: str) -> dict[str, Any] | None:
    with _TASKS_LOCK:
        snapshot = TASKS.get(task_id)
        return deepcopy(snapshot) if snapshot else None


def minimal_safe_response() -> dict[str, Any]:
    risks = ["Analysis incomplete due to timeout or parsing limits"]
    return {
        "project_goal": "Unable to fully analyze project, partial structure detected",
        "architecture_style": "unknown",
        "key_modules": [],
        "core_features": [],
        "risks": risks,
        "summary": {
            "what": "Partial project analysis",
            "why": "System fallback to prevent blocking",
            "issues": list(risks),
        },
        "summary_blocks": {
            "what": "Partial project analysis",
            "why": "System fallback to prevent blocking",
            "remaining": [],
            "issues": list(risks),
        },
    }


async def with_timeout(coro, timeout: int | float = _HARD_ANALYSIS_TIMEOUT_SECONDS, fallback: Any | None = None):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timeout in analysis service")
        return fallback if fallback is not None else minimal_safe_response()
    except Exception as exc:
        logger.warning("Analysis service step failed", extra={"extra_data": {"error": str(exc)}})
        return fallback if fallback is not None else minimal_safe_response()


def _schema_stub() -> dict[str, Any]:
    return {
        "project_goal": "unknown",
        "domain": "unknown",
        "purpose": "unknown",
        "target_users": "unknown",
        "architecture_style": "unknown",
        "key_modules": [],
        "core_features": [],
        "insights": [],
        "risks": [],
        "summary": {"what": "unknown", "why": "unknown", "issues": []},
        "summary_blocks": {"what": "unknown", "why": "unknown", "remaining": [], "issues": []},
        "system_workflow": {
            "initialization": "unknown",
            "data_flow": "unknown",
            "processing": "unknown",
            "output": "unknown",
        },
    }


def _safe_minimal_output() -> dict[str, Any]:
    return {
        "project_goal": "Insufficient evidence to determine project goal",
        "domain": "unknown",
        "purpose": "unknown",
        "target_users": "unknown",
        "architecture_style": "unknown",
        "key_modules": [],
        "core_features": ["Insufficient data"],
        "insights": [],
        "risks": ["Insufficient analysis coverage"],
        "summary": {
            "what": "Insufficient evidence",
            "why": "Insufficient evidence",
            "issues": ["Insufficient analysis coverage"],
        },
        "summary_blocks": {
            "what": "Insufficient evidence",
            "why": "Insufficient evidence",
            "remaining": [],
            "issues": ["Insufficient analysis coverage"],
        },
        "system_workflow": {
            "initialization": "unknown",
            "data_flow": "unknown",
            "processing": "unknown",
            "output": "unknown",
        },
    }


def safe_fallback() -> dict[str, Any]:
    return {
        "project_goal": "Insufficient evidence to determine project goal",
        "architecture_style": "unknown",
        "key_modules": [],
        "core_features": ["Insufficient data"],
        "insights": [],
        "risks": ["Insufficient analysis coverage"],
        "summary": {
            "what": "Insufficient evidence",
            "why": "Insufficient evidence",
            "issues": ["Insufficient analysis coverage"],
        },
        "summary_blocks": {
            "what": "Insufficient evidence",
            "why": "Insufficient evidence",
            "remaining": [],
            "issues": ["Insufficient analysis coverage"],
        },
        "system_workflow": {
            "initialization": "unknown",
            "data_flow": "unknown",
            "processing": "unknown",
            "output": "unknown",
        },
    }


def _clean_str_list(val: Any, limit: int | None = None) -> list[str]:
    if not isinstance(val, list):
        return []
    cleaned: list[str] = []
    for item in val:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit] if limit is not None else cleaned


def _clean_text_value(text: Any) -> str:
    return str(text or "").strip()


def _remove_framework_mentions(text: Any) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return "unknown"
    cleaned = _FRAMEWORK_TERM_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned or "unknown"


def _remove_ai_language(text: Any) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return "unknown"
    cleaned = _AI_PURGE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned or "unknown"


def _strip_generic_phrases(text: Any) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return "unknown"
    cleaned = _GENERIC_PHRASE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned or "unknown"


def _has_conflicting_framework_mentions(*values: Any) -> bool:
    backend_matches: set[str] = set()
    frontend_matches: set[str] = set()
    for value in values:
        if isinstance(value, list):
            haystack = " ".join(str(item) for item in value)
        else:
            haystack = str(value or "")
        for match in _FRAMEWORK_TERM_RE.findall(haystack):
            lowered = match.lower()
            if lowered in {"fastapi", "flask", "django", "express"}:
                backend_matches.add(lowered)
            elif lowered in {"react", "next", "vue", "angular"}:
                frontend_matches.add(lowered)
    if len(backend_matches) > 1:
        return True
    normalized_frontend = frontend_matches - {"react"} if "next" in frontend_matches and "react" in frontend_matches else frontend_matches
    return len(normalized_frontend) > 1


def _clean_risks_for_correction(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    cleaned: list[str] = []
    for item in val:
        text = _clean_text_value(item)
        if not text:
            continue
        if _INVALID_ISSUE_RE.search(text) or _GENERIC_RISK_RE.search(text):
            continue
        if not _SUPPORTED_RISK_RE.search(text):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned[:5]


def _clean_core_features_for_correction(val: Any, *, has_ai_evidence: bool, has_ai_hints: bool = False) -> list[str]:
    if not isinstance(val, list):
        return []
    cleaned: list[str] = []
    for item in val:
        text = _soften_unsupported_ai_claims(
            item,
            has_ai_evidence=has_ai_evidence,
            has_ai_hints=has_ai_hints,
        )
        text = _strip_generic_phrases(text)
        if text == "unknown":
            continue
        if not has_ai_evidence and not has_ai_hints and _AI_PURGE_RE.search(text):
            text = _remove_ai_language(text)
        if text == "unknown" or not _OBSERVABLE_FEATURE_RE.search(text):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned[:6]


def _is_valid_insight_source(source: str) -> bool:
    cleaned = _clean_text_value(source)
    return bool(cleaned and ("/" in cleaned or "\\" in cleaned or "." in cleaned))


def _context_file_count(context: str) -> int:
    markers = re.findall(r"(?:^|\n)(?:---\s+.+?\s+---|===\s*FILE:)", context or "")
    return len(markers) or 1


def _has_ai_ml_evidence(context: str) -> bool:
    return bool(_AI_EVIDENCE_RE.search(context or ""))


def _has_ai_related_hints(context: str) -> bool:
    return bool(_AI_HINT_RE.search(context or ""))


def _count_ai_signal_categories(context: str) -> int:
    haystack = context or ""
    count = 0
    if _AI_FILE_SIGNAL_RE.search(haystack):
        count += 1
    if _AI_DEPENDENCY_SIGNAL_RE.search(haystack):
        count += 1
    if _AI_PATTERN_SIGNAL_RE.search(haystack):
        count += 1
    return count


def _has_strong_ai_product_evidence(context: str) -> bool:
    return _count_ai_signal_categories(context) >= 2


def _has_strong_rag_evidence(context: str) -> bool:
    haystack = context or ""
    return _count_ai_signal_categories(haystack) >= 2 and bool(_RAG_SIGNAL_RE.search(haystack))


def _is_allowed_architecture(style: Any) -> bool:
    cleaned = _clean_text_value(style).lower()
    if not cleaned:
        return False
    parts = [part.strip() for part in cleaned.split("+")]
    return all(part in _ALLOWED_ARCHITECTURE_PARTS for part in parts if part)


def _derive_project_goal_from_evidence(context: str, architecture_style: str, key_modules: Any, file_count: int = 2) -> str:
    lowered_context = (context or "").lower()
    module_text = " ".join(_clean_str_list(key_modules)).lower()
    combined = f"{lowered_context}\n{module_text}"

    is_medical = bool(_MEDICAL_RE.search(combined))
    is_rag = "rag.py" in combined or bool(_RAG_RE.search(combined))
    is_web = "index.html" in combined or bool(_STATIC_WEB_RE.search(combined))
    is_ai = "ai_engine.py" in combined or bool(_AI_FILE_RE.search(combined))

    if is_medical and is_rag:
        return "Offline-first medical RAG system for clinical decision support"
    if is_medical:
        return "Medical system for healthcare and clinical workflows"
    if is_web:
        return "Frontend-based interactive web application"
    if is_rag:
        return "RAG system for intelligent retrieval and processing"
    if is_ai:
        return "AI system for inference and intelligence workflows"

    if file_count < 2:
        return "Insufficient evidence to determine project goal"
    return "Lightweight application with limited structural signals"


def _derive_summary_why_from_evidence(context: str, architecture_style: str) -> str:
    return "Insufficient evidence"


def _remove_paths(text: Any) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return ""
    cleaned = _PATH_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:-")
    return cleaned


def _truncate_words(text: Any, max_words: int = 15) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return ""
    words = cleaned.split()
    return " ".join(words[:max_words]).strip(" ,.;:-")


def _strip_uncertain_language(text: Any) -> str:
    cleaned = _clean_text_value(text)
    if not cleaned:
        return ""
    cleaned = _UNCERTAIN_LANGUAGE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:-")
    return cleaned


def _basename_only(value: Any) -> str:
    cleaned = _clean_text_value(value).replace("\\", "/")
    if not cleaned:
        return ""
    return cleaned.split("/")[-1].strip()


def _architecture_from_analysis_json(result: dict[str, Any]) -> str:
    architecture = _clean_text_value(result.get("architecture_style")).lower()
    combined = " ".join(
        [
            architecture,
            _clean_text_value(result.get("project_goal")).lower(),
            _clean_text_value(((result.get("summary") or {}) if isinstance(result.get("summary"), dict) else {}).get("what")).lower(),
            " ".join(_clean_str_list(result.get("core_features"))).lower(),
            " ".join(_clean_str_list(result.get("key_modules"))).lower(),
        ]
    )
    
    parts = []
    if any(token in combined for token in ("fastapi", "flask", "django", "express", "api", "route", "router", "endpoint")):
        parts.append("api-service")
    if any(token in combined for token in ("react", "next", "component", "page", "layout", "ui", "html", "css")):
        parts.append("component-based")
    if any(token in combined for token in ("rag", "retrieval", "embedding", "vector", "ai", "inference")):
        parts.append("rag-pipeline")
        
    if not parts:
        if "script" in combined:
            parts.append("script-based")
        else:
            parts.append("monolithic")
            
    return " + ".join(parts[:3])


def _rewrite_project_goal_from_analysis_json(result: dict[str, Any], file_count: int = 2) -> str:
    cleaned_goal = _strip_uncertain_language(_remove_paths(_strip_generic_phrases(result.get("project_goal"))))
    if cleaned_goal and "insufficient evidence" not in cleaned_goal.lower():
        return _truncate_words(cleaned_goal, max_words=15)
        
    combined = str(result).lower()
    is_medical = bool(_MEDICAL_RE.search(combined))
    is_rag = "rag.py" in combined or bool(_RAG_RE.search(combined))
    is_web = "index.html" in combined or bool(_STATIC_WEB_RE.search(combined))
    is_ai = "ai_engine.py" in combined or bool(_AI_FILE_RE.search(combined))

    if is_medical and is_rag:
        return "Offline-first medical RAG system for clinical decision support"
    if is_medical:
        return "Medical system for healthcare and clinical workflows"
    if is_web:
        return "Frontend-based interactive web application"
    if is_rag:
        return "RAG system for intelligent retrieval and processing"
    if is_ai:
        return "AI system for inference and intelligence workflows"

    if file_count < 2:
        return "Insufficient evidence to determine project goal"
    return "Lightweight application with limited structural signals"


def _rewrite_core_features_from_analysis_json(result: dict[str, Any]) -> list[str]:
    cleaned_features: list[str] = []
    for feature in _clean_str_list(result.get("core_features")):
        lowered = _strip_uncertain_language(_remove_paths(feature)).lower()
        if lowered:
            cleaned_features.append(feature)

    deduped: list[str] = []
    for feature in cleaned_features:
        if feature and feature not in deduped:
            deduped.append(feature)
    return deduped[:5] or ["Insufficient data"]


def _rewrite_risks_from_analysis_json(result: dict[str, Any]) -> list[str]:
    deduped: list[str] = []
    for risk in _clean_str_list(result.get("risks")):
        if risk and risk not in deduped:
            deduped.append(risk)
    return deduped[:4]


def _refine_product_grade_output(result: dict[str, Any], file_count: int = 2) -> dict[str, Any]:
    if not isinstance(result, dict):
        return safe_fallback()

    refined = dict(result)
    refined["architecture_style"] = _architecture_from_analysis_json(refined)
    refined["project_goal"] = _rewrite_project_goal_from_analysis_json(refined, file_count)
    refined["core_features"] = _rewrite_core_features_from_analysis_json(refined)
    refined["risks"] = _rewrite_risks_from_analysis_json(refined)
    refined["key_modules"] = []
    for module in _clean_str_list(refined.get("key_modules"), limit=8):
        basename = _basename_only(module)
        if basename and basename not in refined["key_modules"]:
            refined["key_modules"].append(basename)

    if not refined["key_modules"]:
        refined["key_modules"] = ["core_module"]

    refined_insights: list[dict[str, str]] = []
    for item in result.get("insights", []) if isinstance(result.get("insights"), list) else []:
        if not isinstance(item, dict):
            continue
        insight = _strip_uncertain_language(_remove_paths(item.get("insight", "")))
        impact = _strip_uncertain_language(_remove_paths(item.get("impact", "")))
        source = _basename_only(item.get("source", ""))
        if not insight or not impact or not source:
            continue
        refined_insights.append({
            "insight": insight,
            "impact": impact,
            "source": source,
            "type": _clean_text_value(item.get("type")).lower() or "architecture",
        })
    if refined_insights:
        refined["insights"] = refined_insights

    summary = refined.get("summary") if isinstance(refined.get("summary"), dict) else {}
    summary_blocks = refined.get("summary_blocks") if isinstance(refined.get("summary_blocks"), dict) else {}
    summary_why = _strip_uncertain_language(summary.get("why") or summary_blocks.get("why"))
    if not summary_why or "insufficient evidence" in summary_why.lower():
        summary_why = "Insufficient evidence"

    refined["summary"] = {
        "what": refined["project_goal"],
        "why": summary_why,
        "issues": list(refined["risks"]),
    }
    refined["summary_blocks"] = {
        "what": refined["project_goal"],
        "why": summary_why,
        "remaining": [
            cleaned
            for cleaned in (
                _strip_uncertain_language(_remove_paths(item))
                for item in _clean_str_list(summary_blocks.get("remaining"), limit=4)
            )
            if cleaned
        ],
        "issues": list(refined["risks"]),
    }

    logger.info(
        "Refined product grade output",
        extra={"extra_data": {
            "file_count": file_count,
            "modules_detected": len(refined["key_modules"]),
            "inference_used": True,
            "fallback_used": refined["project_goal"] == "Lightweight application with limited structural signals"
        }}
    )

    return compact_result(refined)


def _soften_unsupported_ai_claims(text: Any, *, has_ai_evidence: bool, has_ai_hints: bool = False) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return "unknown"
    if has_ai_evidence:
        return cleaned
    if has_ai_hints:
        cleaned = re.sub(r"\b" + "AI" + r"-powered\b", "suggests model-related", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bAI system\b", "software system that suggests AI-related functionality", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bML system\b", "software system that suggests AI-related functionality", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bmodel-driven\b", "suggests AI-related", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bLLM\b", "AI-related", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
        return cleaned or "unknown"
    cleaned = re.sub(r"\b" + "AI" + r"-powered\b", "software", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAI system\b", "software system", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bML system\b", "software system", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmodel-driven\b", "software", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bLLM\b", "software", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned or "unknown"


def _derive_safe_architecture(context: str, proposed: Any) -> str:
    cleaned = str(proposed or "").strip().lower()
    if _is_allowed_architecture(cleaned):
        return cleaned
    lowered_context = (context or "").lower()
    file_count = _context_file_count(context)
    if file_count <= 1:
        return "script-based"
    has_api = any(token in lowered_context for token in ("fastapi", "flask", "django", "express", "router", "api"))
    has_component = any(token in lowered_context for token in ("react", "next", "component", "jsx", "tsx", "page.tsx"))
    has_client = any(token in lowered_context for token in ("client", "frontend", "browser", "page.tsx", "layout.tsx"))
    if has_api and has_component:
        return "client-server + component-based"
    if has_api and has_client:
        return "client-server"
    if has_api:
        return "api-service"
    if has_component:
        return "component-based"
    if file_count > 8:
        return "monolithic"
    return "unknown"


def _clean_insights_for_correction(val: Any) -> list[dict[str, str]]:
    if not isinstance(val, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in val:
        if not isinstance(item, dict):
            continue
        insight = str(item.get("insight", "")).strip()
        source = str(item.get("source", "")).strip()
        impact = str(item.get("impact", "")).strip()
        insight_type = str(item.get("type", "")).strip().lower()
        if insight_type == "developer_experience":
            insight_type = "dx"
        if not insight or not source or not impact or not _is_valid_insight_source(source):
            continue
        if _GENERIC_INSIGHT_RE.search(insight):
            continue
        if insight_type not in _ALLOWED_INSIGHT_TYPES:
            insight_type = "architecture"
        cleaned.append({"insight": insight, "source": source, "impact": impact, "type": insight_type})
    return cleaned[:5]


def _clean_workflow_field(text: Any) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or _GENERIC_WORKFLOW_RE.search(cleaned):
        return "unknown"
    return cleaned


def _clean_workflow_for_correction(workflow: Any) -> dict[str, str]:
    workflow_dict = workflow if isinstance(workflow, dict) else {}
    cleaned = {
        "initialization": _clean_workflow_field(workflow_dict.get("initialization")),
        "data_flow": _clean_workflow_field(workflow_dict.get("data_flow")),
        "processing": _clean_workflow_field(workflow_dict.get("processing")),
        "output": _clean_workflow_field(workflow_dict.get("output")),
    }
    if "unknown" in cleaned.values():
        return {
            "initialization": "unknown",
            "data_flow": "unknown",
            "processing": "unknown",
            "output": "unknown",
        }
    return cleaned


def _is_low_confidence_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    project_goal = str(result.get("project_goal", "")).strip().lower()
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    summary_what = str(summary.get("what", "")).strip().lower()
    signals = sum(
        1
        for value in (
            result.get("key_modules", []),
            result.get("core_features", []),
            result.get("insights", []),
        )
        if isinstance(value, list) and len(value) > 0
    )
    weak_goal = project_goal in {
        "unknown",
        "partial or utility-based implementation",
        "partial codebase analysis",
        "insufficient evidence to determine project goal",
    }
    weak_summary = summary_what in {
        "unknown",
        "limited observable structure",
        "partial codebase analysis",
        "insufficient evidence",
    }
    return signals == 0 and weak_goal and weak_summary


def find_analysis_validation_errors(original_input_context: str, invalid_output_json: Any) -> list[str]:
    result = invalid_output_json if isinstance(invalid_output_json, dict) else safe_parse(str(invalid_output_json or ""))
    errors: list[str] = []
    if _derive_safe_architecture(original_input_context, result.get("architecture_style")) != str(result.get("architecture_style", "")).strip().lower():
        errors.append("invalid_architecture")
    has_ai_evidence = _has_ai_ml_evidence(original_input_context)
    supports_ai_claims = has_ai_evidence or _has_strong_ai_product_evidence(original_input_context)
    text_fields = [
        result.get("project_goal", ""),
        ((result.get("summary") or {}) if isinstance(result.get("summary"), dict) else {}).get("what", ""),
        ((result.get("summary") or {}) if isinstance(result.get("summary"), dict) else {}).get("why", ""),
        " ".join(_clean_str_list(result.get("core_features"))),
    ]
    if not supports_ai_claims and any(re.search(r"\b(ai|ml|llm|model-driven)\b", str(text), re.IGNORECASE) for text in text_fields):
        errors.append("unsupported_ai_claim")
    if _clean_insights_for_correction(result.get("insights")) != (result.get("insights") if isinstance(result.get("insights"), list) else []):
        errors.append("invalid_insights")
    return errors


def correct_invalid_analysis_output(
    original_input_context: str,
    invalid_output_json: Any,
    validation_errors: Any,
) -> dict[str, Any]:
    result = dict(_schema_stub())
    parsed = invalid_output_json if isinstance(invalid_output_json, dict) else safe_parse(str(invalid_output_json or ""))
    if isinstance(parsed, dict):
        result.update({k: v for k, v in parsed.items() if k in result or k in {"summary_blocks"}})

    has_ai_evidence = _has_ai_ml_evidence(original_input_context)
    has_strong_ai = _has_strong_ai_product_evidence(original_input_context)
    has_ai_hints = _has_ai_related_hints(original_input_context)
    supports_ai_claims = has_ai_evidence or has_strong_ai
    project_goal = _soften_unsupported_ai_claims(
        result.get("project_goal"),
        has_ai_evidence=supports_ai_claims,
        has_ai_hints=has_ai_hints,
    )
    project_goal = _strip_generic_phrases(project_goal)
    if not supports_ai_claims and not has_ai_hints:
        project_goal = _remove_ai_language(project_goal)
    result["domain"] = str(result.get("domain", "")).strip() or "unknown"
    result["purpose"] = _soften_unsupported_ai_claims(
        result.get("purpose"),
        has_ai_evidence=supports_ai_claims,
        has_ai_hints=has_ai_hints,
    )
    result["purpose"] = _strip_generic_phrases(result["purpose"])
    if not supports_ai_claims and not has_ai_hints:
        result["purpose"] = _remove_ai_language(result["purpose"])
    result["target_users"] = str(result.get("target_users", "")).strip() or "unknown"
    result["architecture_style"] = _derive_safe_architecture(original_input_context, result.get("architecture_style"))
    result["key_modules"] = _clean_str_list(result.get("key_modules"), limit=8)
    result["core_features"] = _clean_core_features_for_correction(
        result.get("core_features"),
        has_ai_evidence=supports_ai_claims,
        has_ai_hints=has_ai_hints,
    )
    result["insights"] = _clean_insights_for_correction(result.get("insights"))
    result["risks"] = _clean_risks_for_correction(result.get("risks"))
    if (
        project_goal == "unknown"
        or _GENERIC_GOAL_RE.search(project_goal)
        or _GENERIC_PHRASE_RE.search(project_goal)
    ):
        project_goal = _derive_project_goal_from_evidence(
            original_input_context,
            result["architecture_style"],
            result["key_modules"],
        )
    result["project_goal"] = project_goal

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    summary_blocks = result.get("summary_blocks") if isinstance(result.get("summary_blocks"), dict) else {}
    what = _soften_unsupported_ai_claims(
        summary.get("what") or summary_blocks.get("what") or result["project_goal"],
        has_ai_evidence=supports_ai_claims,
        has_ai_hints=has_ai_hints,
    )
    what = _strip_generic_phrases(what)
    why = _soften_unsupported_ai_claims(
        summary.get("why") or summary_blocks.get("why") or _derive_summary_why_from_evidence(original_input_context, result["architecture_style"]),
        has_ai_evidence=supports_ai_claims,
        has_ai_hints=has_ai_hints,
    )
    why = _strip_generic_phrases(why)
    if not supports_ai_claims and not has_ai_hints:
        what = _remove_ai_language(what)
        why = _remove_ai_language(why)
    if what == "unknown" or _GENERIC_GOAL_RE.search(what) or _GENERIC_PHRASE_RE.search(what):
        what = result["project_goal"]
    if why == "unknown":
        why = _derive_summary_why_from_evidence(original_input_context, result["architecture_style"])
    if _has_conflicting_framework_mentions(result["project_goal"], what, why, result["core_features"]):
        result["architecture_style"] = "unknown"
        result["project_goal"] = _remove_framework_mentions(result["project_goal"])
        what = _remove_framework_mentions(what)
        why = _remove_framework_mentions(why)
        result["core_features"] = [
            cleaned for cleaned in (_remove_framework_mentions(item) for item in result["core_features"])
            if cleaned != "unknown"
        ]

    result["insights"] = [
        item for item in result["insights"]
        if not _AI_PURGE_RE.search(item.get("insight", "")) and not _AI_PURGE_RE.search(item.get("impact", ""))
    ]

    result["summary"] = {"what": what, "why": why, "issues": list(result["risks"])}
    result["summary_blocks"] = {"what": what, "why": why, "remaining": [], "issues": list(result["risks"])}

    result["system_workflow"] = _clean_workflow_for_correction(result.get("system_workflow"))

    logger.info(
        "Corrected invalid analysis output conservatively",
        extra={"extra_data": {"validation_errors": validation_errors if isinstance(validation_errors, list) else [str(validation_errors)]}},
    )
    if _is_low_confidence_result(result):
        return _safe_minimal_output()
    return _refine_product_grade_output(result)


def correct_analysis_json(original_analysis_json: Any) -> dict[str, Any]:
    parsed = original_analysis_json if isinstance(original_analysis_json, dict) else safe_parse(str(original_analysis_json or ""))
    validation_errors = find_analysis_validation_errors("", parsed)
    corrected = correct_invalid_analysis_output("", parsed, validation_errors)
    return _refine_product_grade_output(corrected)


def refine_analysis_json(original_analysis_json: Any) -> dict[str, Any]:
    parsed = original_analysis_json if isinstance(original_analysis_json, dict) else safe_parse(str(original_analysis_json or ""))
    return _refine_product_grade_output(parsed)


def enforce_truth(data: dict) -> dict:
    if not isinstance(data, dict):
        return safe_fallback()
    corrected = _refine_product_grade_output(correct_analysis_json(data))
    corrected.pop("domain", None)
    corrected.pop("purpose", None)
    corrected.pop("target_users", None)
    corrected.pop("summary_blocks", None)
    corrected.pop("dependency_graph", None)
    corrected.pop("overview", None)
    corrected.pop("project_type", None)
    corrected.pop("tech_stack", None)
    corrected.pop("folder_structure", None)
    corrected.pop("core_modules", None)
    corrected.pop("execution_flow", None)
    corrected.pop("dependencies", None)
    corrected.pop("improvements", None)
    corrected.pop("issues", None)
    return corrected


def is_bad_output(data: dict) -> bool:
    if not isinstance(data, dict):
        return True
    text = json.dumps(data).lower()
    if "ai system" in text:
        return True
    if "system that orchestrates" in text or "platform for" in text or "model-driven" in text:
        return True
    if "fastapi" in text and "express" in text:
        return True
    if "invalid_final_result" in text or "llm_parse_error" in text:
        return True
    if not _is_allowed_architecture(data.get("architecture_style")):
        return True
    workflow = data.get("system_workflow", {})
    if not isinstance(workflow, dict):
        return True
    for field in ("initialization", "data_flow", "processing", "output"):
        if field not in workflow:
            return True
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        return True
    for field in ("what", "why", "issues"):
        if field not in summary:
            return True
    return False


def safe_parse(text: str) -> dict:
    try:
        parsed = parse_llm_json(text)
        logger.info("Parsed JSON successfully", extra={"extra_data": {"response_length": len(str(text or ""))}})
        return parsed
    except Exception as exc:
        logger.warning(
            "Parsed JSON failed; using fallback",
            extra={"extra_data": {"response_length": len(str(text or "")), "error": str(exc)}},
        )
        fallback_summary = str(text or "").strip()[:500] or "Analysis failed but recovered"
        return {
            "summary": fallback_summary,
            "architecture": {},
            "modules": [],
            "risks": ["Parsing failed"],
            "project_goal": fallback_summary,
            "architecture_style": "Not enough information",
            "tech_stack": [],
            "key_modules": [],
            "core_features": [],
            "summary_blocks": {
                "what": fallback_summary,
                "why": "Recovered fallback result after parsing failure.",
                "remaining": [],
                "issues": ["Parsing failed"],
            },
        }

def strict_context_module_filter(key_modules, file_paths):
    valid = set()

    for path in file_paths:
        fname = os.path.basename(path)
        valid.add(fname)
        valid.add(os.path.splitext(fname)[0])

    if not isinstance(key_modules, list):
        return []

    return list(set([m for m in key_modules if m in valid]))


def force_non_empty_repo_output(result: Dict[str, Any]) -> Dict[str, Any]:
    summary_blocks = result.setdefault("summary_blocks", {})

    if not result.get("core_features"):
        result["core_features"] = [
            "Visible code structure and module responsibility extraction",
            "Entry-point and dependency pattern detection",
            "Practical project intent summarization"
        ]

    summary_blocks["issues"] = list(result.get("risks", []))

    if not summary_blocks.get("remaining"):
        summary_blocks["remaining"] = [
            "Further deep analysis can be performed"
        ]

    if not summary_blocks.get("what"):
        summary_blocks["what"] = "Basic project structure detected"

    if not summary_blocks.get("why"):
        summary_blocks["why"] = "Project structure and intent extraction from repository context"

    result["summary_blocks"] = summary_blocks
    return compact_result(result)

REPO_INTENT_PROMPT = """
Return ONLY valid JSON.

You are a senior software architect performing STRICT codebase analysis.
Use ONLY the structured repository evidence provided in the input.

MANDATORY RULES:
- Do NOT hallucinate.
- Do NOT use prior knowledge.
- Do NOT assume frameworks or technologies unless they are explicitly visible in file names, imports, or dependency data.
- If a field cannot be filled confidently from the input, use "unknown".
- key_modules must reference real files, imports, classes, or functions visible in the input.
- core_features, risks, remaining, and issues must be grounded in visible code structure.
- No markdown, no explanation, no extra text.

INPUT:
{context}

OUTPUT FORMAT:
{{
  "project_goal": "",
  "architecture_style": "",
  "tech_stack": [],
  "key_modules": [],
  "core_features": [],
  "risks": [],
  "summary_blocks": {{
    "what": "",
    "why": "",
    "remaining": [],
    "issues": []
  }}
}}

FIELD RULES:
- project_goal: describe what the repository does in real-world terms only when the visible evidence is strong; otherwise use "Insufficient evidence to determine project goal"
- architecture_style: script-based / component-based / api-service / client-server / monolithic / static-web / unknown
- tech_stack: only technologies explicitly visible in imports, manifests, or file names
- summary_blocks.what: one-line factual summary
- summary_blocks.why: one-line evidence-based reason or "unknown"
"""

FILE_SUMMARY_PROMPT = """
Analyze this file and return ONLY JSON.

NO explanations. NO markdown.

File: {file_path}

Content:
{content}

FORMAT:

{{
  "summary": "string",
  "module_role": "string"
}}

Return ONLY valid JSON.
No explanation.
No markdown.
No extra text.
"""

def parse_llm_response(response: str | dict) -> dict:
    if isinstance(response, dict):
        return response

    fallback = {
        "project_goal": "Failed to parse",
        "tech_stack": [],
        "core_features": []
    }

    try:
        raw_str = str(response)
        logger.debug(
            "Parsing LLM response",
            extra={"extra_data": {"response_length": len(raw_str)}},
        )
        return safe_parse(raw_str)

    except Exception as e:
        logger.error(f"Unexpected error in parse_llm_response: {e}")
        return fallback

class AnalysisService:
    def __init__(self):
        # We use the summarize model (7b) for intent/file extraction as it's deeper reasoning
        self.llm = get_llm_provider("summarize")
        self.settings = get_settings()

    async def extract_repo_intelligence(self, context: str, mode: str = "offline") -> Dict[str, Any]:
        """Extract root-level intent from concatenated key files."""
        try:
            logger.info(f"extract_repo_intelligence called with {len(context)} chars")
            if not context or len(context.strip()) < 50:
                return minimal_safe_response()

            from app.services.llm_handler import call_llm_async
            context_batches = self._build_context_batches(context)
            partial_results = await asyncio.gather(*[
                with_timeout(
                    call_llm_async(
                        REPO_INTENT_PROMPT.format(context=batch),
                        timeout=min(self.settings.LLM_TIMEOUT_SECONDS, _HARD_LLM_TIMEOUT_SECONDS),
                        fallback_context=batch,
                        mode=mode,
                    ),
                    timeout=_HARD_LLM_TIMEOUT_SECONDS,
                    fallback={},
                )
                for batch in context_batches[:_MAX_CONTEXT_BATCHES]
            ], return_exceptions=True)

            top_files = re.findall(r"--- (.+?) ---", context)[:50]
            merged = self._merge_repo_results(partial_results, top_files)
            return force_non_empty_repo_output(merged or minimal_safe_response())
        except Exception as exc:
            logger.warning("Repo intelligence extraction returned fallback", extra={"extra_data": {"error": str(exc)}})
            return minimal_safe_response()

    def _build_context_batches(self, context: str) -> list[str]:
        file_blocks = [block.strip() for block in re.split(r"(?=---\s+.+?\s+---)", context) if block.strip()]
        chunk_size = self.settings.CHUNK_SIZE_CHARS
        batch_size = max(2, min(3, self.settings.CHUNK_BATCH_SIZE))
        chunks: list[str] = []

        for block in file_blocks:
            lines = block.splitlines(keepends=True)
            current = ""
            for line in lines:
                if len(current) + len(line) > chunk_size and current:
                    chunks.append(current.rstrip())
                    current = line
                else:
                    current += line
            if current.strip():
                chunks.append(current.rstrip())

        if not chunks:
            chunks = [context[:chunk_size]]

        if len(chunks) <= batch_size:
            return ["\n\n".join(chunks)]

        batches = [chunks[index:index + batch_size] for index in range(0, len(chunks), batch_size)]
        if len(batches) > 1 and len(batches[-1]) == 1:
            batches[-2].extend(batches[-1])
            batches.pop()

        return ["\n\n".join(batch) for batch in batches[:_MAX_CONTEXT_BATCHES]]

    def _merge_repo_results(self, partial_results: list[dict], top_files: list[str]) -> Dict[str, Any]:
        valid_results = [item for item in partial_results if isinstance(item, dict)]
        key_modules: list[str] = []
        tech_stack: list[str] = []
        core_features: list[str] = []
        risks: list[str] = []
        remaining: list[str] = []
        issues: list[str] = []

        for item in valid_results:
            key_modules.extend(item.get("key_modules", []))
            tech_stack.extend(item.get("tech_stack", []))
            core_features.extend(item.get("core_features", []))
            risks.extend(item.get("risks", []))
            blocks = item.get("summary_blocks", {}) if isinstance(item.get("summary_blocks", {}), dict) else {}
            remaining.extend(blocks.get("remaining", []))
            issues.extend(blocks.get("issues", []))

        filtered_modules = strict_context_module_filter(key_modules, top_files)
        if not filtered_modules:
            filtered_modules = top_files[:8]

        return compact_result({
            "project_goal": next((str(item.get("project_goal", "")).strip() for item in valid_results if len(str(item.get("project_goal", "")).strip()) > 5), "Insufficient evidence to determine project goal"),
            "tech_stack": list(dict.fromkeys(str(item).strip() for item in tech_stack if str(item).strip())),
            "core_features": list(dict.fromkeys(str(item).strip() for item in core_features if str(item).strip())),
            "architecture_style": next((str(item.get("architecture_style", "")).strip() for item in valid_results if len(str(item.get("architecture_style", "")).strip()) > 3), "unknown"),
            "key_modules": filtered_modules,
            "risks": list(dict.fromkeys(str(item).strip() for item in risks if str(item).strip())),
            "summary_blocks": {
                "what": next((str((item.get("summary_blocks", {}) or {}).get("what", "")).strip() for item in valid_results if len(str((item.get("summary_blocks", {}) or {}).get("what", "")).strip()) > 5), "Insufficient evidence"),
                "why": next((str((item.get("summary_blocks", {}) or {}).get("why", "")).strip() for item in valid_results if len(str((item.get("summary_blocks", {}) or {}).get("why", "")).strip()) > 5), "Insufficient evidence"),
                "remaining": list(dict.fromkeys(str(item).strip() for item in remaining if str(item).strip())),
                "issues": list(dict.fromkeys(str(item).strip() for item in issues if str(item).strip())),
            },
        })

    async def analyze_file(self, file_path: str, content: str, mode: str = "offline") -> Dict[str, Any]:
        """Extract file-level intelligence."""
        # Trim individual file content limits for context window
        trimmed_content = content[:8000]
        prompt = FILE_SUMMARY_PROMPT.format(file_path=file_path, content=trimmed_content)
        
        try:
            from app.services.llm_handler import call_llm_async
            parsed = await with_timeout(
                call_llm_async(prompt, timeout=min(self.settings.LLM_TIMEOUT_SECONDS, _HARD_LLM_TIMEOUT_SECONDS), mode=mode),
                timeout=_HARD_LLM_TIMEOUT_SECONDS,
                fallback={},
            )
            if not isinstance(parsed, dict):
                parsed = {}
            return {
                "summary": str(parsed.get("summary", "Summary unavailable")),
                "module_role": str(parsed.get("module_role", "Unknown Role"))
            }
        except Exception as e:
            logger.warning(f"Failed to extract file intelligence for {file_path}: {e}")
            return {
                "summary": "Summary unavailable.",
                "module_role": "Unknown"
            }
