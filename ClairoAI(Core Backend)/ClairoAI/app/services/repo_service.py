"""
Repository analysis service.
"""

from __future__ import annotations

import asyncio
import gc
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List

import requests

from app.core.logging import get_logger
from app.db.models import SessionStatus
from app.db.repository import SessionRepository
from app.services.analysis_service import (
    correct_invalid_analysis_output,
    enforce_truth,
    find_analysis_validation_errors,
    is_bad_output,
    safe_fallback,
    update_task_record,
)
from app.services.graph_builder import build_relationship_graph
from app.services.llm_handler import call_llm_async
from app.services.normalize import compact_result
from app.utils.normalize import normalize_analysis_output

logger = get_logger("services.repo")
_VAGUE_TERMS = ("likely", "appears", "suggests", "probably")

VALID_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".html"}
IGNORE_DIRS = {".git", "node_modules", "venv"}
LOW_SIGNAL_FILENAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-lock.yml", "bun.lockb"}
MAX_FILES = 10
MAX_TOTAL_FILES = 50
MAX_FILE_SIZE_BYTES = 1024 * 1024
MAX_CONTEXT_FILES = 3
MAX_CANDIDATE_FILES = 14
MAX_FILE_READ_CHARS = 2500
MAX_CONTEXT_CHARS = 1800
MAX_CONTEXT_CHARS_PER_FILE = 320
MAX_CONTEXT_LINES_PER_FILE = 120
DOWNLOAD_TIMEOUT = 10
LLM_TIMEOUT = 90
HARD_ANALYSIS_TIMEOUT = 20
HARD_LLM_TIMEOUT = 15
GITHUB_API_TIMEOUT = 15
GITHUB_BRANCH_FALLBACKS = ("main", "master", "dev")
DEPENDENCY_GRAPH_TIMEOUT = 5.0
CLASSIFICATION_TIMEOUT = 2.0
LARGE_REPO_FILE_THRESHOLD = 30
LARGE_REPO_MAX_FILES = 8
LARGE_REPO_MAX_CONTEXT_FILES = 2
_REPO_LLM_CACHE_TTL_SECONDS = 600
_REPO_LLM_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}
_HIGH_PRIORITY_FILES = {
    "main.py", "app.py", "server.py", "index.js", "index.ts", "package.json",
    "requirements.txt", "pyproject.toml", "dockerfile", "docker-compose.yml",
    "config.py", "settings.py", ".env", ".env.example", "readme.md",
}
_GENERIC_REPO_MARKERS = (
    "repository input `",
    "repository snapshot with",
    "repository source snapshot for inspection",
    "software project with prioritized entrypoints",
    "fastapi-based backend service that exposes api endpoints and coordinates application logic",
    "flask-based web service that handles routed requests and application processing",
    "backend api service that organizes request routing and business logic across core modules",
    "frontend interface for a wider product workflow",
)


def minimal_safe_response() -> Dict[str, Any]:
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


async def with_timeout(coro, timeout: int | float = HARD_ANALYSIS_TIMEOUT, fallback: Any | None = None):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timeout in repo analysis")
        return fallback if fallback is not None else minimal_safe_response()
    except Exception as exc:
        logger.warning("Repo analysis step failed", extra={"extra_data": {"error": str(exc)}})
        return fallback if fallback is not None else minimal_safe_response()

REPO_ANALYSIS_PROMPT = """Return valid JSON only.

You are a strict codebase synthesis engine running inside a long-running backend job.
Your only job is to generate a summary based on the exact deterministic structure provided.

Rules:
- Do not hallucinate.
- If something is unclear, say "Not enough information".
- Keep the response deterministic and grounded in the provided snapshot.
- Do not include markdown or explanatory text outside JSON.
- Never expose secrets, environment values, internal paths, raw logs, stack traces, or debug traces.
- You must generate ONLY the project_goal, core_features, and risks based strictly on the provided signals and scores.
- Do not guess architecture; rely solely on the provided inputs.

Analyze the uploaded project structure and return this exact JSON shape:
{{
  "project_goal": "...",
  "architecture_style": "...",
  "key_modules": ["..."],
  "core_features": ["..."],
  "insights": [
    {{"insight": "...", "source": "file path", "impact": "...", "type": "architecture"}}
  ],
  "risks": ["..."],
  "summary": {{
    "what": "...",
    "why": "...",
    "issues": ["..."]
  }},
  "system_workflow": {{
    "initialization": "...",
    "data_flow": "...",
    "processing": "...",
    "output": "..."
  }}
}}

STRUCTURED INPUT:
{context}
"""


def _repo_cache_get(cache_key: str) -> Dict[str, Any] | None:
    cached = _REPO_LLM_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _REPO_LLM_CACHE.pop(cache_key, None)
        return None
    return dict(payload)


def _repo_cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    _REPO_LLM_CACHE[cache_key] = (time.time() + _REPO_LLM_CACHE_TTL_SECONDS, dict(payload))


def _is_windows_lock_error(error: Exception) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) == 32


def _safe_delete(path: str) -> None:
    if not path:
        return
    for attempt in range(1, 4):
        if not os.path.exists(path):
            return
        try:
            logger.info("Deleting temp file", extra={"extra_data": {"path": path, "attempt": attempt}})
            os.remove(path)
            return
        except Exception as exc:
            logger.warning(
                "Temp file delete failed",
                extra={"extra_data": {"path": path, "attempt": attempt, "error": str(exc)}},
            )
            if attempt >= 3 or not _is_windows_lock_error(exc):
                return
            continue


def _safe_rmtree(path: str) -> None:
    if not path:
        return
    for attempt in range(1, 4):
        if not os.path.exists(path):
            return
        try:
            logger.info("Removing temp directory", extra={"extra_data": {"path": path, "attempt": attempt}})
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                return
        except Exception as exc:
            logger.warning(
                "Temp directory cleanup failed",
                extra={"extra_data": {"path": path, "attempt": attempt, "error": str(exc)}},
            )
            if attempt >= 3 or not _is_windows_lock_error(exc):
                return
        continue


def _dedupe(items: list) -> list:
    seen: set = set()
    result = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _contains_vague_language(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in _VAGUE_TERMS)


def _format_grounded_steps(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    steps: list[str] = []
    for item in value:
        if isinstance(item, dict):
            detail = _clean_text(item.get("step") or item.get("detail") or item.get("action"))
            source = _clean_text(item.get("source"))
            if detail and source and not _contains_vague_language(detail):
                steps.append(f"{detail} [{source}]")
    return _dedupe(steps)


def _coerce_grounded_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(parsed.get("key_modules"), list):
        parsed["key_module_details"] = [
            item for item in parsed["key_modules"]
            if isinstance(item, dict)
            and _clean_text(item.get("name"))
            and _clean_text(item.get("role"))
            and _clean_text(item.get("source"))
            and not _contains_vague_language(_clean_text(item.get("role")))
        ]
        names: list[str] = []
        for item in parsed["key_modules"]:
            cleaned = _clean_text(item.get("name")) if isinstance(item, dict) else ""
            if cleaned and isinstance(item, dict) and _clean_text(item.get("source")):
                names.append(cleaned)
        parsed["key_modules"] = _dedupe(names)
    if isinstance(parsed.get("core_features"), list):
        parsed["feature_details"] = [
            {
                "feature": _clean_text(item.get("feature")),
                "evidence": _clean_text(item.get("source") or item.get("evidence")),
                "source": _clean_text(item.get("source") or item.get("evidence")),
            }
            for item in parsed["core_features"]
            if isinstance(item, dict)
            and _clean_text(item.get("feature"))
            and _clean_text(item.get("source") or item.get("evidence"))
            and not _contains_vague_language(_clean_text(item.get("feature")))
        ]
        features: list[str] = []
        for item in parsed["core_features"]:
            cleaned = _clean_text(item.get("feature")) if isinstance(item, dict) else ""
            if cleaned and isinstance(item, dict) and _clean_text(item.get("source") or item.get("evidence")):
                features.append(cleaned)
        parsed["core_features"] = _dedupe(features)
    if isinstance(parsed.get("risks"), list):
        parsed["risk_details"] = [
            item for item in parsed["risks"]
            if isinstance(item, dict)
            and _clean_text(item.get("risk"))
            and _clean_text(item.get("source"))
            and not _contains_vague_language(_clean_text(item.get("risk")))
        ]
        risks: list[str] = []
        for item in parsed["risks"]:
            cleaned = _clean_text(item.get("risk")) if isinstance(item, dict) else ""
            if cleaned and isinstance(item, dict) and _clean_text(item.get("source")):
                risks.append(cleaned)
        parsed["risks"] = _dedupe(risks)
    workflow = parsed.get("system_workflow", {})
    parsed["system_workflow"] = {
        "initialization": _format_grounded_steps(workflow.get("initialization", [])) if isinstance(workflow, dict) else [],
        "request_flow": _format_grounded_steps(workflow.get("request_flow", [])) if isinstance(workflow, dict) else [],
        "processing_flow": _format_grounded_steps(workflow.get("processing_flow", [])) if isinstance(workflow, dict) else [],
        "response_flow": _format_grounded_steps(workflow.get("response_flow", [])) if isinstance(workflow, dict) else [],
    }
    edges = []
    if isinstance(parsed.get("dependency_graph"), list):
        for item in parsed["dependency_graph"]:
            if not isinstance(item, dict):
                continue
            source = _clean_text(item.get("from"))
            target = _clean_text(item.get("to"))
            relation = _clean_text(item.get("type")) or "import"
            if source and target:
                edges.append({"source": source, "target": target, "relation": relation})
    parsed["dependency_graph"] = {"edges": edges} if edges else {}
    if isinstance(parsed.get("insights"), list):
        parsed["insights"] = [
            {
                "insight": _clean_text(item.get("insight")),
                "source": _clean_text(item.get("source")),
                "impact": _clean_text(item.get("impact")),
                "type": ("dx" if _clean_text(item.get("type")).lower() == "developer_experience" else _clean_text(item.get("type")).lower()) or "architecture",
            }
            for item in parsed["insights"]
            if isinstance(item, dict)
            and _clean_text(item.get("insight"))
            and _clean_text(item.get("source"))
            and _clean_text(item.get("impact"))
            and not _contains_vague_language(_clean_text(item.get("insight")))
        ]
    return parsed


@dataclass
class RepoDownloadError(Exception):
    message: str
    suggestion: str = "Failed to download repository. Please check the repo link or branch."
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def _detect_framework(context: str) -> str:
    ctx = context.lower()
    if "fastapi" in ctx:
        return "FastAPI"
    if "flask" in ctx:
        return "Flask"
    if "django" in ctx:
        return "Django"
    if "express" in ctx:
        return "Express.js"
    if "react" in ctx or "jsx" in ctx:
        return "React"
    if "next" in ctx and "next/app" in ctx:
        return "Next.js"
    if "vue" in ctx:
        return "Vue.js"
    return "general"


def _score_repo_file(rel_path: str) -> int:
    normalized = str(rel_path or "").replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    ext = os.path.splitext(basename)[1]
    if basename in LOW_SIGNAL_FILENAMES:
        return -1000
    score = 0

    if basename in _HIGH_PRIORITY_FILES:
        score += 120
    if basename.startswith("main.") or basename.startswith("app.") or basename.startswith("index."):
        score += 90
    if any(token in normalized for token in ("/api/", "/routes/", "/router", "/services/", "/core/", "/config/", "/src/")):
        score += 55
    if any(token in basename for token in ("config", "settings", "routes", "router", "service", "core")):
        score += 45
    if normalized.count("/") <= 2:
        score += 20
    if ext in {".py", ".ts", ".tsx", ".js", ".jsx"}:
        score += 20
    if ext in {".json", ".yml", ".yaml", ".toml", ".md"}:
        score += 15
    return score


def _normalize_summary_blocks(summary_blocks: Any, file_count: int) -> Dict[str, Any]:
    payload = summary_blocks if isinstance(summary_blocks, dict) else {}
    return {
        "what": str(payload.get("what", "")).strip() or f"Repository snapshot with {file_count} non-empty text files.",
        "why": str(payload.get("why", "")).strip() or "Provides repository files for inspection.",
        "remaining": _dedupe([str(x) for x in payload.get("remaining", []) if str(x).strip()]),
        "issues": _dedupe([str(x) for x in payload.get("issues", []) if str(x).strip()]),
    }


def _is_valid_repo_final_result(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks"), dict) else {}
    project_goal = str(result.get("project_goal", "")).strip()
    summary_what = str(summary_blocks.get("what", "")).strip()
    summary_why = str(summary_blocks.get("why", "")).strip()
    if not project_goal or not summary_what or not summary_why:
        return False
    combined = f"{project_goal} {summary_what} {summary_why}".lower()
    return not any(marker in combined for marker in _GENERIC_REPO_MARKERS)


def _count_ai_product_signals(paths_text: str, content_text: str) -> int:
    signals = 0
    if any(token in paths_text for token in ("ai_engine.py", "rag.py", "inference.py", "retrieval.py", "embedding.py", "embeddings.py", "model.py")):
        signals += 1
    if any(token in content_text for token in ("transformers", "torch", "tensorflow", "openai", "gemini", "langchain", "ollama", "chromadb", "faiss", "sentence-transformers")):
        signals += 1
    if any(token in content_text for token in ("embedding", "retrieval", "retrieve", "inference", "vector", "rerank", "prompt")):
        signals += 1
    return signals


def _infer_project_goal(files: List[Dict[str, str]], framework: str) -> str:
    joined_paths = " ".join(str(file_info.get("path", "") or "").lower() for file_info in files)
    joined_content = " ".join(str(file_info.get("content", "") or "").lower()[:600] for file_info in files[:8])
    ai_signals = _count_ai_product_signals(joined_paths, joined_content)
    strong_ai = ai_signals >= 2
    strong_rag = strong_ai and any(token in f"{joined_paths} {joined_content}" for token in ("rag", "retrieval", "embedding", "vector", "chromadb", "faiss"))
    if strong_rag and any(token in joined_content for token in ("patient", "clinic", "medical", "health", "diagnosis", "clinical")):
        return "Medical query and diagnosis API for clinical decision support."
    if strong_rag and any(token in f"{joined_paths} {joined_content}" for token in ("repo", "repository", "code analysis", "source code", "zip", "archive")):
        return "Code and repository analysis service."
    if strong_rag:
        return "Question answering service for structured workflows."
    if strong_ai and any(token in joined_content for token in ("payment", "invoice", "billing", "transaction", "finance", "bank")):
        return "Model-backed finance workflow service for transaction or billing analysis."
    if strong_ai and any(token in joined_content for token in ("campaign", "seo", "marketing", "lead", "audience", "analytics")):
        return "Model-backed marketing analysis and content workflow service."
    if strong_ai and any(token in joined_content for token in ("patient", "clinic", "medical", "health", "diagnosis", "clinical")):
        return "Model-backed medical workflow service for clinical queries or diagnosis support."
    if strong_ai:
        return "Model-backed service with visible inference workflows."
    if any(token in joined_content for token in ("payment", "invoice", "billing", "transaction", "finance", "bank")):
        return "Service that handles finance-related workflows such as payments, billing, or transaction processing."
    if any(token in joined_content for token in ("campaign", "seo", "marketing", "lead", "audience", "analytics")):
        return "Tooling for marketers to generate content, analyze audiences, or manage campaign workflows."
    if any(token in joined_content for token in ("patient", "clinic", "medical", "health", "diagnosis")):
        return "Service for healthcare-facing workflows such as symptom intake, medical records handling, or clinical support."
    if "csv" in joined_content or "dataset" in joined_content:
        return "Data-processing service that ingests structured datasets and turns them into reports or downstream results."
    if framework == "FastAPI":
        return "Backend API for request handling and application workflows."
    if framework == "Flask":
        return "Backend API with routed request handling."
    if framework == "Django":
        return "Server-side web application with centralized request handling."
    if any(token in joined_paths for token in ("/api/", "/routes/", "router", "controller")):
        return "Backend API for routed request and processing workflows."
    if framework == "React":
        return "Frontend application with component-driven user workflows."
    if framework == "Next.js":
        return "Web application with routed frontend workflows."
    return "Insufficient evidence to determine project goal"


def _infer_domain(files: List[Dict[str, str]]) -> str:
    joined_content = " ".join(str(file_info.get("content", "") or "").lower()[:600] for file_info in files[:8])
    if any(token in joined_content for token in ("llm", "gemini", "ollama", "embedding", "model", "prompt")):
        return "AI"
    if any(token in joined_content for token in ("payment", "invoice", "billing", "transaction", "finance", "bank")):
        return "Finance"
    if any(token in joined_content for token in ("campaign", "seo", "marketing", "lead", "audience", "analytics")):
        return "Marketing"
    if any(token in joined_content for token in ("patient", "clinic", "medical", "health", "diagnosis")):
        return "Healthcare"
    if any(token in joined_content for token in ("csv", "dataset", "analytics", "report")):
        return "Data analytics"
    return ""


def _count_ai_product_signals(paths_text: str, content_text: str) -> int:
    signals = 0
    if any(token in paths_text for token in ("ai_engine.py", "rag.py", "inference.py", "retrieval.py", "embedding.py", "embeddings.py", "model.py")):
        signals += 1
    if any(token in content_text for token in ("transformers", "torch", "tensorflow", "openai", "gemini", "langchain", "ollama", "chromadb", "faiss", "sentence-transformers")):
        signals += 1
    if any(token in content_text for token in ("embedding", "retrieval", "retrieve", "inference", "vector", "rerank", "prompt")):
        signals += 1
    return signals


def _build_semantic_context(files: List[Dict[str, str]], repo_url: str) -> str:
    from app.services.code_analyzer import calculate_project_scores
    import json
    
    files_list = [{"path": str(f.get("path", "")), "content": str(f.get("content", ""))[:500]} for f in files[:8]]
    scores = calculate_project_scores(files_list)
    modules = _classify_files(files)
    
    joined_paths = " ".join(str(f.get("path", "")).lower() for f in files)
    joined_content = " ".join(str(f.get("content", "")).lower()[:500] for f in files[:8])
    
    signals = {
        "ai_signal": _count_ai_product_signals(joined_paths, joined_content) >= 1,
        "api_signal": any(token in joined_content for token in ("fastapi", "flask", "express", "router", "@app.", "@router.")),
        "ui_signal": any(token in joined_content for token in ("react", "render", "html", "jsx", "tsx", "component")),
        "data_signal": any(token in joined_content for token in ("pandas", "csv", "sql", "database", "query", "json.load")),
    }
    
    return json.dumps({
        "files": files_list,
        "modules": modules,
        "signals": signals,
        "scores": scores
    }, indent=2)


def _infer_core_features(files: List[Dict[str, str]], framework: str) -> List[str]:
    features: List[str] = []
    joined_paths = " ".join(str(file_info.get("path", "") or "").lower() for file_info in files)
    joined_content = " ".join(str(file_info.get("content", "") or "").lower()[:600] for file_info in files[:8])
    strong_ai = _count_ai_product_signals(joined_paths, joined_content) >= 2
    strong_rag = strong_ai and any(token in f"{joined_paths} {joined_content}" for token in ("rag", "retrieval", "embedding", "vector", "chromadb", "faiss"))
    has_api = False
    has_data_io = False
    has_processing = False
    has_ui = False
    has_runtime = False
    for file_info in files[:12]:
        path = str(file_info.get("path", "") or "")
        content = str(file_info.get("content", "") or "").lower()
        basename = os.path.basename(path).lower()
        if framework in {"FastAPI", "Flask", "Django", "Express.js"} and any(token in content for token in ("@app.", "router.", "route(", "fastapi", "flask")):
            has_api = True
        if any(token in content for token in ("open(", "read_text(", "write_text(", "json.load", "json.dump", "csv.")):
            has_data_io = True
        if any(token in content for token in ("process", "transform", "analyze", "parse", "validate")):
            has_processing = True
        if any(token in content for token in ("input(", "print(", "click", "form", "button", "render(")):
            has_ui = True
        if any(token in content for token in ("model", "predict", "embedding", "llm", "gemini", "ollama")):
            if strong_rag:
                features.append("Knowledge search")
            elif strong_ai:
                features.append("Model-backed response generation")
        if basename in {"dockerfile", "docker-compose.yml", "package.json", "requirements.txt"}:
            has_runtime = True
    if has_api:
        features.append("REST API for request handling")
    if has_data_io:
        if any(token in f"{joined_paths} {joined_content}" for token in ("repo", "repository", "zip", "archive")):
            features.append("Repository and archive ingestion")
        else:
            features.append("File and dataset ingestion")
    if has_processing:
        features.append("Data processing and request execution")
    if has_ui:
        features.append("Interactive user interface")
    if has_runtime:
        features.append("Runtime and dependency configuration")
    return _dedupe(features)[:5]


def _infer_risks(files: List[Dict[str, str]]) -> List[str]:
    risks: List[str] = []
    for file_info in files[:12]:
        path = str(file_info.get("path", "") or "")
        content = str(file_info.get("content", "") or "")
        lowered = content.lower()
        if any(token in lowered for token in ("open(", "requests.", "json.load", "csv.")) and "try:" not in lowered:
            risks.append(f"Limited error handling around external I/O in {path}")
        if any(token in lowered for token in ("todo", "fixme", "pass\n", "pass\r\n")):
            risks.append(f"Incomplete implementation markers remain in {path}")
        if any(token in lowered for token in ("c:\\", "/users/", "/tmp/", "localhost")):
            risks.append(f"Contains environment-specific paths or assumptions in {path}")
        if any(token in lowered for token in ("input(", "request.", "query_params", "body")) and "validate" not in lowered:
            risks.append(f"Input validation may be limited in {path}")
        if "test" in os.path.basename(path).lower():
            risks.append(f"Sample or test-oriented code may not represent production behavior in {path}")
        if any(token in lowered for token in ("ollama", "gguf", "local model", "model_path", "llama.cpp")):
            risks.append(f"Dependency on local models may affect runtime availability in {path}")
    return _dedupe(risks)[:6]


def _infer_workflow(files: List[Dict[str, str]]) -> Dict[str, List[str]]:
    entrypoints = _classify_files(files).get("entry_points", [])
    init_step = entrypoints[0] if entrypoints else (files[0]["path"] if files else "application entrypoint")
    return {
        "initialization": [f"Start from {init_step}"],
        "request_flow": ["Route or trigger enters the main application module"] if entrypoints else [],
        "processing_flow": ["Core modules process inputs and execute application logic"] if files else [],
        "response_flow": ["Return or persist the processed result"] if files else [],
    }


async def _call_repo_llm(prompt: str, timeout: int, label: str) -> Dict[str, Any]:
    started = time.monotonic()
    parsed = await with_timeout(
        call_llm_async(
            prompt,
            timeout=min(timeout, HARD_LLM_TIMEOUT),
            simplified_prompt=prompt,
            mode="online",
        ),
        timeout=HARD_LLM_TIMEOUT,
        fallback={},
    )
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    logger.info(
        "Repo LLM call succeeded",
        extra={"extra_data": {"label": label, "latency_ms": latency_ms}},
    )
    if not isinstance(parsed, dict) or not parsed:
        raise Exception("LLM returned empty response")
    return parsed


async def _run_repo_llm_enhancement(
    repo_url: str,
    branch: str,
    files: List[Dict[str, str]],
    context: str,
    framework: str,
) -> Dict[str, Any]:
    semantic_context = _build_semantic_context(files, repo_url)
    cache_key = sha256(f"{repo_url}|{branch}|{semantic_context}".encode("utf-8")).hexdigest()
    cached = _repo_cache_get(cache_key)
    if cached:
        return cached
    full_prompt = REPO_ANALYSIS_PROMPT.format(
        context=semantic_context
    )
    logger.info(
        "Repo LLM context prepared",
        extra={"extra_data": {
            "files_sent": len(files),
            "semantic_context_size": len(semantic_context),
            "prompt_size": len(full_prompt),
            "branch": branch,
        }},
    )
    parsed = await _call_repo_llm(full_prompt, HARD_LLM_TIMEOUT, "full")
    _repo_cache_set(cache_key, parsed)
    return parsed


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    match = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)/?$", repo_url.strip())
    if not match:
        raise RepoDownloadError(
            message="Invalid GitHub repository URL",
            suggestion="Use a public GitHub repository URL in the format https://github.com/owner/repo",
            status_code=400,
        )

    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _github_api_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AHAL-AI-Repo-Analyzer",
    }


def _repo_zip_url(owner: str, repo: str, branch: str) -> str:
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"


def _detect_default_branch(owner: str, repo: str) -> str | None:
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(api_url, headers=_github_api_headers(), timeout=GITHUB_API_TIMEOUT)

    if response.status_code == 404:
        raise RepoDownloadError(
            message="Repository not found or is private",
            suggestion="Ensure the repo is public or provide access token",
            status_code=404,
        )

    if response.status_code in {401, 403}:
        raise RepoDownloadError(
            message="Repository not accessible or GitHub API access is restricted",
            suggestion="Ensure the repo is public or provide access token",
            status_code=403,
        )

    response.raise_for_status()
    payload = response.json()
    branch = str(payload.get("default_branch", "")).strip()
    return branch or None


def _resolve_branch_candidates(owner: str, repo: str) -> list[str]:
    try:
        detected = _detect_default_branch(owner, repo)
    except RepoDownloadError:
        raise
    except Exception as exc:
        logger.warning(f"Default branch detection failed for {owner}/{repo}: {exc}")
        detected = None

    candidates: list[str] = []
    if detected:
        candidates.append(detected)
    candidates.extend(GITHUB_BRANCH_FALLBACKS)
    return _dedupe(candidates)


def _download_zip(repo_url: str, dest_path: str) -> str:
    owner, repo = _parse_github_repo_url(repo_url)
    branch_candidates = _resolve_branch_candidates(owner, repo)
    last_response: requests.Response | None = None

    for branch in branch_candidates:
        zip_url = _repo_zip_url(owner, repo, branch)
        try:
            logger.info(
                "Downloading repository archive",
                extra={"extra_data": {"repo_url": repo_url, "branch": branch, "zip_path": dest_path}},
            )
            with requests.get(
                zip_url,
                headers=_github_api_headers(),
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
                allow_redirects=True,
            ) as response:
                last_response = response

                if response.status_code == 404:
                    continue
                if response.status_code in {401, 403}:
                    raise RepoDownloadError(
                        message="Repository not found or is private",
                        suggestion="Ensure the repo is public or provide access token",
                        status_code=response.status_code,
                    )

                response.raise_for_status()
                archive_bytes = response.content
            with open(dest_path, "wb") as file_handle:
                file_handle.write(archive_bytes)
            archive_bytes = b""
            gc.collect()

            if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
                raise RepoDownloadError(
                    message="Downloaded repository archive is empty",
                    suggestion="Failed to download repository. Please check the repo link or branch.",
                    status_code=502,
                )

            return branch
        except Exception as exc:
            if _is_windows_lock_error(exc):
                logger.warning(
                    "Repository download hit a transient file lock",
                    extra={"extra_data": {"repo_url": repo_url, "branch": branch, "zip_path": dest_path, "error": str(exc)}},
                )
                continue
            raise

    if last_response and last_response.status_code == 404:
        raise RepoDownloadError(
            message="Failed to download repository. Please check the repo link or branch.",
            suggestion="Ensure the repository exists and the default branch is accessible.",
            status_code=404,
        )

    raise RepoDownloadError(
        message="Failed to download repository. Please check the repo link or branch.",
        suggestion="Ensure the repository exists and is publicly accessible.",
        status_code=400,
    )


def _extract_zip(zip_path: str, extract_dir: str) -> str:
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
        raise RepoDownloadError(
            message="Repository ZIP was not downloaded successfully",
            suggestion="Failed to download repository. Please check the repo link or branch.",
            status_code=400,
        )

    logger.info("Extracting repository archive", extra={"extra_data": {"zip_path": zip_path, "extract_dir": extract_dir}})
    for attempt in range(1, 4):
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_file:
                bad_member = zip_file.testzip()
                if bad_member is not None:
                    raise RepoDownloadError(
                        message=f"Repository ZIP is corrupted near {bad_member}",
                        suggestion="Repository download did not complete.",
                        status_code=400,
                    )
                zip_file.extractall(extract_dir)
            gc.collect()
            break
        except zipfile.BadZipFile as exc:
            raise RepoDownloadError(
                message="Downloaded repository archive is not a valid ZIP file",
                suggestion="Failed to download repository. Please check the repo link or branch.",
                status_code=400,
            ) from exc
        except Exception as exc:
            logger.warning(
                "Repository extraction attempt failed",
                extra={"extra_data": {"zip_path": zip_path, "extract_dir": extract_dir, "attempt": attempt, "error": str(exc)}},
            )
            if attempt >= 3 or not _is_windows_lock_error(exc):
                raise
            continue

    entries = os.listdir(extract_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
        root_dir = os.path.join(extract_dir, entries[0])
    else:
        root_dir = extract_dir

    if not os.path.isdir(root_dir):
        raise RepoDownloadError(
            message="Repository archive extracted without a valid project directory",
            suggestion="Repository download did not complete.",
            status_code=400,
        )

    return root_dir


def _select_files(root_dir: str) -> tuple[List[Dict[str, Any]], int]:
    candidates: List[Dict[str, Any]] = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [directory for directory in dirnames if directory not in IGNORE_DIRS]
        for filename in filenames:
            if filename.lower() in LOW_SIGNAL_FILENAMES:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
            ext = os.path.splitext(filename)[1].lower()

            if ext and ext not in VALID_EXTENSIONS:
                continue
            try:
                if os.path.getsize(full_path) > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue
            candidates.append({
                "path": rel_path,
                "full_path": full_path,
                "score": _score_repo_file(rel_path),
            })

            if len(candidates) >= MAX_TOTAL_FILES:
                break
        if len(candidates) >= MAX_TOTAL_FILES:
            break

    total_candidates = len(candidates)
    max_selected_files = LARGE_REPO_MAX_FILES if total_candidates > LARGE_REPO_FILE_THRESHOLD else MAX_FILES
    ranked_candidates = sorted(
        candidates,
        key=lambda item: (-int(item["score"]), len(str(item["path"])), str(item["path"])),
    )[:MAX_CANDIDATE_FILES]

    selected_files: List[Dict[str, Any]] = []
    for item in ranked_candidates:
        try:
            with open(str(item["full_path"]), "r", encoding="utf-8", errors="ignore") as file_handle:
                content = file_handle.read(MAX_FILE_READ_CHARS)
        except Exception:
            continue

        if "\x00" in content:
            continue

        cleaned = content.strip()
        if not cleaned:
            continue

        path_lower = str(item["path"]).lower()
        basename = os.path.basename(path_lower)
        ext = os.path.splitext(basename)[1]
        
        # Classify Role
        role = "unknown"
        if basename in ("main.py", "app.py", "index.js"):
            role = "entry"
        elif "router" in path_lower or "/api/" in path_lower:
            role = "api"
        elif "engine" in path_lower or "service" in path_lower:
            role = "service"
        elif basename in (".env", "dockerfile", "package.json", "requirements.txt", "config.py"):
            role = "config"
        elif "test" in path_lower:
            role = "test"
        elif ext in (".html", ".jsx", ".tsx") or "react" in path_lower:
            role = "frontend"
        elif "data" in path_lower or ext in (".csv", ".json", ".sql"):
            role = "data"
            
        # Classify Signals
        content_lower = cleaned.lower()
        ai_signal = bool(any(t in path_lower for t in ("ai_engine.py", "rag.py", "inference.py")) or any(t in content_lower for t in ("transformers", "torch", "openai", "gemini", "embedding", "inference")))
        api_signal = bool(any(t in content_lower for t in ("fastapi", "flask", "@app.", "router.", "route(")))
        ui_signal = bool(any(t in content_lower for t in ("react", "render(", "html", "<div", "<button", "ui")))
        data_signal = bool(any(t in content_lower for t in ("json.load", "csv.", "read_text(", "pandas")))

        selected_files.append({
            "path": str(item["path"]),
            "content": cleaned,
            "line_count": len(cleaned.splitlines()),
            "score": int(item["score"]),
            "role": role,
            "signals": {
                "ai_signal": ai_signal,
                "api_signal": api_signal,
                "ui_signal": ui_signal,
                "data_signal": data_signal
            }
        })
        if len(selected_files) >= max_selected_files:
            break

    return selected_files, total_candidates


def _build_context(files: List[Dict[str, str]], *, total_file_count: int | None = None) -> str:
    parts = []
    total = 0
    context_file_limit = LARGE_REPO_MAX_CONTEXT_FILES if (total_file_count or len(files)) > LARGE_REPO_FILE_THRESHOLD else MAX_CONTEXT_FILES
    for file_info in files[:context_file_limit]:
        if int(file_info.get("line_count", 0) or 0) > MAX_CONTEXT_LINES_PER_FILE:
            continue
        content = str(file_info.get("content", "") or "")
        if len(content) > MAX_CONTEXT_CHARS_PER_FILE:
            content = content[:MAX_CONTEXT_CHARS_PER_FILE].rstrip() + "\n...(trimmed)..."
        snippet = f"=== FILE: {file_info['path']} ===\n{content}"
        if total + len(snippet) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total
            if remaining > 200:
                parts.append(snippet[:remaining])
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n".join(parts)


def _build_repo_structure(files: List[Dict[str, str]]) -> List[str]:
    return _dedupe([file["path"] for file in files])[:40]


def _classify_files(files: List[Dict[str, str]]) -> Dict[str, List[str]]:
    classes: Dict[str, List[str]] = {
        "entry_points": [],
        "api_layer": [],
        "service_layer": [],
        "frontend_layer": [],
        "data_flow": [],
    }
    for file_info in files:
        path = str(file_info.get("path", "") or "")
        normalized = path.replace("\\", "/").lower()
        basename = os.path.basename(normalized)
        ext = os.path.splitext(basename)[1]
        
        if basename in ("main.py", "app.py", "server.py", "index.js", "index.ts"):
            classes["entry_points"].append(path)
        elif any(token in normalized for token in ("router", "route", "/api/")):
            classes["api_layer"].append(path)
        elif any(token in normalized for token in ("service", "engine", "core", "logic", "workflow")):
            classes["service_layer"].append(path)
        elif ext in (".html", ".jsx", ".tsx", ".css") or any(token in normalized for token in ("react", "view", "component", "frontend")):
            classes["frontend_layer"].append(path)
        elif any(token in normalized for token in ("data", "db", "database", "sql", "repository", "store")) or ext in (".csv", ".json", ".sql", ".db"):
            classes["data_flow"].append(path)
            
    return {key: _dedupe(value)[:10] for key, value in classes.items()}


def _build_fast_dependency_graph(files: List[Dict[str, str]]) -> Dict[str, Any]:
    graph = build_relationship_graph(
        session_type="repo",
        sampled_files=files,
        workflows=[],
    )
    return {"edges": list(graph.get("edges", []))[:80]}


async def _timed_background_value(coro: asyncio.Future, timeout: float, fallback: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception:
        return fallback


def generate_minimal_analysis(files: List[Dict[str, str]], repo_ref: str) -> Dict[str, Any]:
    paths = [file_info["path"] for file_info in files if str(file_info.get("content", "")).strip()]
    context = _build_context(files) if files else ""
    evidence_text = "\n".join(
        f"{file_info.get('path', '')}\n{str(file_info.get('content', '') or '')[:320]}"
        for file_info in files[:8]
    )
    framework = _detect_framework(context) if context else "general"
    classified = _classify_files(files)
    goal = _infer_project_goal(files, framework)
    features = _infer_core_features(files, framework)
    risks = _infer_risks(files)
    return normalize_analysis_output({
        "project_goal": goal,
        "domain": _infer_domain(files),
        "architecture_style": framework,
        "key_modules": (classified.get("entry_points", []) + classified.get("api_layer", []) + classified.get("service_layer", []) + paths)[:8],
        "core_features": features,
        "risks": risks,
        "system_workflow": _infer_workflow(files),
        "dependency_graph": {},
        "summary_blocks": {
            "what": f"{goal} Repository input `{repo_ref}` produced {len(paths)} prioritized non-empty text files.",
            "why": "Built from entrypoints, config files, core modules, and visible implementation signals.",
            "remaining": ["Deeper semantic review could inspect more modules"] if files else [],
            "issues": risks[:3],
        },
    }, evidence_text=evidence_text)


def _should_skip_dependency_graph(total_file_count: int) -> bool:
    return total_file_count > LARGE_REPO_FILE_THRESHOLD


async def analyze_repo_from_url(repo_url: str) -> Dict[str, Any]:
    temp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix="contextbridge_repo_")
    zip_path = os.path.join(temp_dir, f"repo_{uuid.uuid4().hex}.zip")
    extract_dir = os.path.join(temp_dir, f"extract_{uuid.uuid4().hex}")
    logger.info("Created repository temp paths", extra={"extra_data": {"repo_url": repo_url, "temp_dir": temp_dir, "zip_path": zip_path, "extract_dir": extract_dir}})
    try:
        branch = await with_timeout(
            asyncio.to_thread(_download_zip, repo_url, zip_path),
            timeout=DOWNLOAD_TIMEOUT + 2,
            fallback="",
        )
        root_dir = await with_timeout(
            asyncio.to_thread(_extract_zip, zip_path, extract_dir),
            timeout=5,
            fallback="",
        )
        gc.collect()
        await asyncio.to_thread(_safe_delete, zip_path)
        files, total_file_count = await with_timeout(
            asyncio.to_thread(_select_files, root_dir),
            timeout=5,
            fallback=([], 0),
        )
        if not files or len(files) == 0:
            return {
                "status": "partial",
                "reason": "insufficient files or parsing failure",
                "project_goal": "Unable to infer from available files"
            }
        if len(files) < 3:
            # Mark as weak repo
            pass

        context = await with_timeout(
            asyncio.to_thread(_build_context, files, total_file_count=total_file_count),
            timeout=5,
            fallback="",
        )
        if not context.strip():
            return {
                "status": "partial",
                "reason": "insufficient files or parsing failure",
                "project_goal": "Unable to infer from available files"
            }

        framework = await with_timeout(asyncio.to_thread(_detect_framework, context), timeout=2, fallback="unknown")

        try:
            parsed = await _run_repo_llm_enhancement(
                repo_url=repo_url,
                branch=branch,
                files=files,
                context=context,
                framework=framework,
            )
            parsed = _coerce_grounded_result(parsed)
            summary_blocks = _normalize_summary_blocks(parsed.get("summary_blocks", {}), len(files))
            result = {
                "project_goal": str(parsed.get("project_goal", "")).strip() or "Repository source snapshot for inspection.",
                "architecture_style": str(parsed.get("architecture_style", "")).strip() or framework,
                "key_modules": _dedupe([str(x) for x in parsed.get("key_modules", []) if str(x).strip()]),
                "core_features": _dedupe([str(x) for x in parsed.get("core_features", []) if str(x).strip()]),
                "risks": _dedupe([str(x) for x in parsed.get("risks", []) if str(x).strip()]),
                "system_workflow": parsed.get("system_workflow", {}),
                "dependency_graph": parsed.get("dependency_graph", {}),
                "insights": parsed.get("insights", []),
                "summary": parsed.get("summary", {}),
                "summary_blocks": summary_blocks,
            }
            validation_errors = find_analysis_validation_errors(context, result)
            if validation_errors:
                logger.warning("Correcting invalid repo analysis output", extra={"extra_data": {"errors": validation_errors}})
                result = correct_invalid_analysis_output(context, result, validation_errors)
            result = enforce_truth(result)
            if is_bad_output(result):
                result = safe_fallback()
            valid_names = set()
            for file_info in files:
                valid_names.add(file_info["path"])
                valid_names.add(os.path.basename(file_info["path"]))
                valid_names.add(os.path.splitext(os.path.basename(file_info["path"]))[0])
            result["key_modules"] = [
                module for module in result["key_modules"]
                if module in valid_names
            ]
            if not result["key_modules"]:
                result["key_modules"] = [file_info["path"] for file_info in files[:8]]
            return normalize_analysis_output(compact_result(result), evidence_text=context)
        except Exception:
            return normalize_analysis_output(compact_result(generate_minimal_analysis(files, repo_url)), evidence_text=context)
    finally:
        await asyncio.gather(
            asyncio.to_thread(_safe_delete, zip_path),
            asyncio.to_thread(_safe_rmtree, extract_dir),
            asyncio.to_thread(_safe_rmtree, temp_dir),
            return_exceptions=True,
        )


async def process_repo_analysis_session(session_id: str, repo_url: str) -> None:
    await SessionRepository.update_progress(session_id, 5, "upload")
    update_task_record(session_id, status=SessionStatus.PROCESSING.value, progress=5, stage="upload")

    temp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix=f"contextbridge_repo_{session_id}_")
    zip_path = os.path.join(temp_dir, f"repo_{uuid.uuid4().hex}.zip")
    extract_dir = os.path.join(temp_dir, f"extract_{uuid.uuid4().hex}")
    structure: list[str] = []
    final_result = normalize_analysis_output(compact_result(minimal_safe_response()), evidence_text="")
    logger.info(
        "Created repository temp paths",
        extra={"extra_data": {"session_id": session_id, "repo_url": repo_url, "temp_dir": temp_dir, "zip_path": zip_path, "extract_dir": extract_dir}},
    )
    try:
        await SessionRepository.update_progress(session_id, 12, "upload")
        update_task_record(session_id, status=SessionStatus.PROCESSING.value, progress=12, stage="upload")
        try:
            branch = await with_timeout(
                asyncio.to_thread(_download_zip, repo_url, zip_path),
                timeout=DOWNLOAD_TIMEOUT + 2,
                fallback="",
            )
        except Exception as exc:
            await SessionRepository.update_status(
                session_id=session_id,
                status=SessionStatus.COMPLETED,
                progress=100,
                stage="finalize",
                result=final_result,
            )
            update_task_record(
                session_id,
                status=SessionStatus.COMPLETED.value,
                progress=100,
                stage="finalize",
                result=final_result,
            )
            await SessionRepository.update_fields(
                session_id,
                source_ref=repo_url,
                structure=[],
            )
            return

        await SessionRepository.update_progress(session_id, 22, "upload")
        update_task_record(session_id, status=SessionStatus.PROCESSING.value, progress=22, stage="upload")
        try:
            root_dir = await with_timeout(asyncio.to_thread(_extract_zip, zip_path, extract_dir), timeout=5, fallback="")
            gc.collect()
            await asyncio.to_thread(_safe_delete, zip_path)
        except Exception as exc:
            await SessionRepository.update_status(
                session_id=session_id,
                status=SessionStatus.COMPLETED,
                progress=100,
                stage="finalize",
                result=final_result,
            )
            update_task_record(
                session_id,
                status=SessionStatus.COMPLETED.value,
                progress=100,
                stage="finalize",
                result=final_result,
            )
            await SessionRepository.update_fields(
                session_id,
                source_ref=repo_url,
                structure=[],
            )
            return

        await SessionRepository.update_progress(session_id, 34, "analyze")
        update_task_record(session_id, status=SessionStatus.PROCESSING.value, progress=34, stage="analyze")
        try:
            files, total_file_count = await with_timeout(asyncio.to_thread(_select_files, root_dir), timeout=5, fallback=([], 0))
        except Exception:
            files, total_file_count = [], 0
        structure = _build_repo_structure(files)
        quick_result = normalize_analysis_output(compact_result(generate_minimal_analysis(files, repo_url)), evidence_text="\n".join(
            f"{file_info.get('path', '')}\n{str(file_info.get('content', '') or '')[:320]}"
            for file_info in files[:8]
        ))
        await SessionRepository.update_fields(
            session_id,
            source_ref=repo_url,
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
        )
        await SessionRepository.update_progress(
            session_id,
            42,
            "analyze",
            result=quick_result,
        )
        update_task_record(
            session_id,
            status=SessionStatus.PROCESSING.value,
            progress=42,
            stage="analyze",
            result=quick_result,
            structure=structure,
        )

        final_result = quick_result or final_result
        if files:
            should_skip_graph = _should_skip_dependency_graph(total_file_count)
            context_task = asyncio.create_task(
                asyncio.to_thread(_build_context, files, total_file_count=total_file_count)
            )
            classification_task = asyncio.create_task(
                _timed_background_value(asyncio.to_thread(_classify_files, files), CLASSIFICATION_TIMEOUT, {
                    "entry_points": [],
                    "config_files": [],
                    "core_modules": [],
                })
            )
            dependency_task = asyncio.create_task(asyncio.sleep(0, result={})) if should_skip_graph else asyncio.create_task(
                _timed_background_value(asyncio.to_thread(_build_fast_dependency_graph, files), DEPENDENCY_GRAPH_TIMEOUT, {})
            )
            context = await with_timeout(context_task, timeout=5, fallback="")
            if not context.strip():
                final_result = quick_result or final_result
            else:
                framework = await with_timeout(asyncio.to_thread(_detect_framework, context), timeout=2, fallback="unknown")
                await SessionRepository.update_progress(session_id, 70, "insights", result=final_result)
                update_task_record(
                    session_id,
                    status=SessionStatus.PROCESSING.value,
                    progress=70,
                    stage="insights",
                    result=final_result,
                )
                llm_task = asyncio.create_task(
                    _run_repo_llm_enhancement(repo_url, branch, files, context, framework)
                )
                try:
                    enhanced = await with_timeout(llm_task, timeout=HARD_LLM_TIMEOUT, fallback={})
                    enhanced = _coerce_grounded_result(enhanced)
                    summary_blocks = _normalize_summary_blocks(enhanced.get("summary_blocks", {}), len(files))
                    gathered = await asyncio.gather(classification_task, dependency_task, return_exceptions=True)
                    file_classes = gathered[0] if isinstance(gathered[0], dict) else {"entry_points": [], "config_files": [], "core_modules": []}
                    dependency_graph = gathered[1] if isinstance(gathered[1], dict) else {}
                    final_result = {
                        "project_goal": str(enhanced.get("project_goal", "")).strip() or quick_result.get("project_goal", ""),
                        "domain": str(enhanced.get("domain", "")).strip() or quick_result.get("domain", ""),
                        "purpose": str(enhanced.get("purpose", "")).strip(),
                        "target_users": str(enhanced.get("target_users", "")).strip(),
                        "architecture_style": quick_result.get("architecture_style", framework),
                        "key_modules": list(quick_result.get("key_modules", [])),
                        "core_features": list(quick_result.get("core_features", [])),
                        "risks": list(quick_result.get("risks", [])),
                        "system_workflow": quick_result.get("system_workflow", {}),
                        "dependency_graph": dependency_graph or enhanced.get("dependency_graph", {}),
                        "insights": enhanced.get("insights", []),
                        "summary": enhanced.get("summary", {}),
                        "summary_blocks": {
                            **quick_result.get("summary_blocks", {}),
                            **summary_blocks,
                            "remaining": quick_result.get("summary_blocks", {}).get("remaining", []),
                            "issues": quick_result.get("summary_blocks", {}).get("issues", []),
                        },
                    }
                    validation_errors = find_analysis_validation_errors(context, final_result)
                    if validation_errors:
                        logger.warning("Correcting invalid final repo output", extra={"extra_data": {"errors": validation_errors}})
                        final_result = correct_invalid_analysis_output(context, final_result, validation_errors)
                    final_result = enforce_truth(final_result)
                    if is_bad_output(final_result):
                        final_result = safe_fallback()
                    valid_names = set()
                    for file_info in files:
                        valid_names.add(file_info["path"])
                        valid_names.add(os.path.basename(file_info["path"]))
                        valid_names.add(os.path.splitext(os.path.basename(file_info["path"]))[0])
                    final_result["key_modules"] = [
                        module for module in final_result["key_modules"]
                        if module in valid_names
                    ]
                    if should_skip_graph:
                        final_result.setdefault("summary_blocks", {}).setdefault(
                            "issues",
                            ["Dependency graph was skipped to keep large-repository analysis responsive"],
                        )
                    final_result = normalize_analysis_output(compact_result(final_result), evidence_text=context)
                    if not _is_valid_repo_final_result(final_result):
                        final_result = normalize_analysis_output(safe_fallback(), evidence_text=context)
                except Exception as exc:
                    await asyncio.gather(classification_task, dependency_task, return_exceptions=True)
                    logger.warning("Repo semantic refinement failed", extra={"extra_data": {"session_id": session_id, "error": str(exc)}})
                    final_result = quick_result or final_result

        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="finalize",
            result=final_result,
        )
        update_task_record(
            session_id,
            status=SessionStatus.COMPLETED.value,
            progress=100,
            stage="finalize",
            result=final_result,
            error=None,
        )
        await SessionRepository.update_fields(
            session_id,
            source_ref=repo_url,
            structure=structure,
            summary=final_result.get("summary_blocks", {}).get("what", ""),
            error=None,
        )
    except Exception as exc:
        logger.error(
            "Background repo analysis failed",
            extra={"extra_data": {"session_id": session_id, "error": str(exc)}},
        )
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="finalize",
            result=final_result,
            error=None,
        )
        update_task_record(
            session_id,
            status=SessionStatus.COMPLETED.value,
            progress=100,
            stage="finalize",
            result=final_result,
            error=None,
        )
    finally:
        await asyncio.gather(
            asyncio.to_thread(_safe_delete, zip_path),
            asyncio.to_thread(_safe_rmtree, extract_dir),
            asyncio.to_thread(_safe_rmtree, temp_dir),
            return_exceptions=True,
        )
