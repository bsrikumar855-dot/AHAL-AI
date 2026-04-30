"""
Folder analysis service.
"""

from __future__ import annotations

import os
import asyncio
import json
import time
from hashlib import sha256
from typing import Any, Awaitable, Callable, Dict

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.analysis_service import (
    correct_invalid_analysis_output,
    enforce_truth,
    find_analysis_validation_errors,
    is_bad_output,
    safe_fallback,
)
from app.services.context_builder import build_analysis_context
from app.services.file_handler import FileHandler
from app.services.llm_handler import call_llm_async
from app.services.normalize import compact_result
from app.utils.normalize import normalize_analysis_output

logger = get_logger("services.folder_analyzer")
_VAGUE_TERMS = ("likely", "appears", "suggests", "probably")

_MAX_ANALYSIS_FILES = 8
_MAX_TOTAL_FILES = 50
_MAX_FILE_SIZE_BYTES = 1024 * 1024
_MAX_CHARS_PER_FILE = 450
_MAX_CONTEXT_CHARS = 1800
_FOLDER_ANALYSIS_TIMEOUT_SECONDS = 90
_HARD_ANALYSIS_TIMEOUT_SECONDS = 20
_HARD_LLM_TIMEOUT_SECONDS = 15
_FILE_PROCESSING_TIMEOUT_SECONDS = 5
_MAX_CONTEXT_LINES = 120
_FOLDER_LLM_CACHE_TTL_SECONDS = 600
_FOLDER_LLM_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}
_LOW_SIGNAL_FILENAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-lock.yml", "bun.lockb"}
_HIGH_PRIORITY_FILES = {
    "main.py", "app.py", "server.py", "index.js", "index.ts", "package.json",
    "requirements.txt", "pyproject.toml", "dockerfile", "docker-compose.yml",
    "config.py", "settings.py", ".env", ".env.example",
}

ProgressCallback = Callable[[str], Awaitable[None] | None]


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


async def with_timeout(coro, timeout: int | float = _HARD_ANALYSIS_TIMEOUT_SECONDS, fallback: Any | None = None):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timeout in folder analysis")
        return fallback if fallback is not None else minimal_safe_response()
    except Exception as exc:
        logger.warning("Folder analysis step failed", extra={"extra_data": {"error": str(exc)}})
        return fallback if fallback is not None else minimal_safe_response()

FOLDER_ANALYSIS_PROMPT = """Return strict JSON only.

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
{
  "project_goal": "...",
  "architecture_style": "...",
  "key_modules": ["..."],
  "core_features": ["..."],
  "insights": [
    {"insight": "...", "source": "file path", "impact": "...", "type": "architecture"}
  ],
  "risks": ["..."],
  "summary": {
    "what": "...",
    "why": "...",
    "issues": ["..."]
  },
  "system_workflow": {
    "initialization": "...",
    "data_flow": "...",
    "processing": "...",
    "output": "..."
  }
}

STRUCTURED INPUT:
{context}
"""


def _folder_cache_get(cache_key: str) -> Dict[str, Any] | None:
    cached = _FOLDER_LLM_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _FOLDER_LLM_CACHE.pop(cache_key, None)
        return None
    return dict(payload)


def _folder_cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    _FOLDER_LLM_CACHE[cache_key] = (time.time() + _FOLDER_LLM_CACHE_TTL_SECONDS, dict(payload))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
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
        key_modules: list[str] = []
        for item in parsed["key_modules"]:
            cleaned = _clean_text(item.get("name")) if isinstance(item, dict) else ""
            if cleaned and isinstance(item, dict) and _clean_text(item.get("source")):
                key_modules.append(cleaned)
        parsed["key_modules"] = _dedupe(key_modules)
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


def _detect_arch_hints(file_contents: Dict[str, str]) -> str:
    combined = " ".join(file_contents.values()).lower()
    paths = " ".join(file_contents.keys()).lower()
    hints = []
    if "fastapi" in combined or "from fastapi" in combined:
        hints.append("FastAPI")
    if "flask" in combined:
        hints.append("Flask")
    if "express" in combined:
        hints.append("Express.js")
    if "react" in combined or "jsx" in combined:
        hints.append("React")
    if "django" in combined:
        hints.append("Django")
    if "/api/" in paths or "/routes/" in paths:
        hints.append("API layer detected")
    if "/models/" in paths:
        hints.append("model layer detected")
    if "docker" in paths:
        hints.append("containerized")
    return ", ".join(hints) if hints else "general code repository"


def _score_file(path: str, content: str) -> int:
    normalized = str(path or "").replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    if basename in _LOW_SIGNAL_FILENAMES:
        return -1000
    score = 0

    if basename in _HIGH_PRIORITY_FILES:
        score += 120
    if basename.startswith("main.") or basename.startswith("app.") or basename.startswith("index."):
        score += 90
    if any(token in normalized for token in ("/api/", "/routes/", "/router", "/controllers/", "/services/", "/core/")):
        score += 60
    if any(token in basename for token in ("config", "settings", "routes", "router", "service", "core")):
        score += 50
    if normalized.count("/") <= 2:
        score += 20
    if len(content.splitlines()) > _MAX_CONTEXT_LINES:
        score -= 40
    return score


def _normalize_summary_blocks(summary_blocks: Any, file_count: int) -> Dict[str, Any]:
    payload = summary_blocks if isinstance(summary_blocks, dict) else {}
    return {
        "what": str(payload.get("what", "")).strip() or f"Project archive with {file_count} non-empty text files.",
        "why": str(payload.get("why", "")).strip() or "Provides source files for project inspection.",
        "remaining": _dedupe([str(x) for x in payload.get("remaining", []) if str(x).strip()]),
        "issues": _dedupe([str(x) for x in payload.get("issues", []) if str(x).strip()]),
    }


def _classify_selected_files(file_contents: Dict[str, str]) -> Dict[str, list[str]]:
    classes = {"entry_points": [], "api_layer": [], "service_layer": [], "frontend_layer": [], "data_flow": []}
    for path in sorted(file_contents.keys(), key=lambda value: str(value)):
        normalized = str(path).replace("\\", "/").lower()
        basename = os.path.basename(normalized)
        ext = os.path.splitext(basename)[1]
        
        if basename in ("main.py", "app.py", "index.js"):
            classes["entry_points"].append(path)
        elif "router" in normalized or "/api/" in normalized:
            classes["api_layer"].append(path)
        elif any(t in normalized for t in ("service", "engine", "core")):
            classes["service_layer"].append(path)
        elif ext in (".html", ".jsx", ".tsx", ".css") or "react" in normalized:
            classes["frontend_layer"].append(path)
        elif "data" in normalized or ext in (".csv", ".json", ".sql"):
            classes["data_flow"].append(path)
            
    total_found = sum(len(v) for v in classes.values())
    if total_found == 0:
        for path in file_contents:
            basename = os.path.basename(str(path).replace("\\", "/")).lower()
            if basename in ("main.py", "app.py"):
                classes["entry_points"].append(f"{basename} [core module]")
            elif basename in ("index.html", "index.js"):
                classes["entry_points"].append(f"{basename} [frontend module]")
        if not classes["entry_points"]:
            classes["entry_points"] = ["core module"]
        
    return {key: _dedupe(value)[:10] for key, value in classes.items()}


def _count_ai_product_signals(paths_text: str, content_text: str) -> int:
    signals = 0
    if any(token in paths_text for token in ("ai_engine.py", "rag.py", "inference.py", "retrieval.py", "embedding.py", "embeddings.py", "model.py")):
        signals += 1
    if any(token in content_text for token in ("transformers", "torch", "tensorflow", "openai", "gemini", "langchain", "ollama", "chromadb", "faiss", "sentence-transformers")):
        signals += 1
    if any(token in content_text for token in ("embedding", "retrieval", "retrieve", "inference", "vector", "rerank", "prompt")):
        signals += 1
    return signals


def _infer_project_goal(file_contents: Dict[str, str], arch_hints: str) -> str:
    return "Insufficient evidence to determine project goal"


def _infer_domain(file_contents: Dict[str, str]) -> str:
    joined = " ".join(str(content).lower()[:500] for content in list(file_contents.values())[:8])
    if any(token in joined for token in ("llm", "gemini", "ollama", "embedding", "model", "prompt")):
        return "AI"
    if any(token in joined for token in ("payment", "invoice", "billing", "transaction", "finance", "bank")):
        return "Finance"
    if any(token in joined for token in ("campaign", "seo", "marketing", "lead", "audience", "analytics")):
        return "Marketing"
    if any(token in joined for token in ("patient", "clinic", "medical", "health", "diagnosis")):
        return "Healthcare"
    if any(token in joined for token in ("csv", "dataset", "analytics", "report")):
        return "Data analytics"
    return ""


def _build_semantic_context(file_contents: Dict[str, str], filename: str) -> str:
    from app.services.code_analyzer import calculate_project_scores
    
    files_list = [{"path": path, "content": str(content)[:500]} for path, content in list(file_contents.items())[:8]]
    scores = calculate_project_scores(files_list)
    modules = _classify_selected_files(file_contents)
    
    joined_paths = " ".join(str(path).lower() for path in file_contents.keys())
    joined_content = " ".join(str(content).lower()[:500] for content in list(file_contents.values())[:8])
    
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


def _infer_features(file_contents: Dict[str, str]) -> list[str]:
    features: list[str] = []
    joined = " ".join(str(content or "").lower()[:500] for content in list(file_contents.values())[:8])
    joined_paths = " ".join(str(path).lower() for path in file_contents.keys())
    strong_ai = _count_ai_product_signals(joined_paths, joined) >= 2
    strong_rag = strong_ai and any(token in f"{joined_paths} {joined}" for token in ("rag", "retrieval", "embedding", "vector", "chromadb", "faiss"))
    has_api = False
    has_data_io = False
    has_processing = False
    has_ui = False
    for path, content in list(file_contents.items())[:12]:
        lowered = str(content or "").lower()
        if any(token in lowered for token in ("@app.", "router.", "route(", "fastapi", "flask")):
            has_api = True
        if any(token in lowered for token in ("open(", "read_text(", "write_text(", "json.load", "json.dump", "csv.")):
            has_data_io = True
        if any(token in lowered for token in ("process", "transform", "analyze", "parse", "validate")):
            has_processing = True
        if any(token in lowered for token in ("render(", "button", "form", "input(", "click")):
            has_ui = True
        if any(token in lowered for token in ("model", "predict", "embedding", "llm", "gemini", "ollama")):
            if strong_rag:
                features.append("Knowledge search")
            elif strong_ai:
                features.append("Model-backed response generation")
    if has_api:
        features.append("REST API for request handling")
    if has_data_io:
        if any(token in f"{joined_paths} {joined}" for token in ("repo", "repository", "zip", "archive")):
            features.append("Repository and archive ingestion")
        else:
            features.append("File and dataset ingestion")
    if has_processing:
        features.append("Data processing and request execution")
    if has_ui:
        features.append("Interactive user interface")
    return _dedupe(features)[:5]


def _infer_risks(file_contents: Dict[str, str]) -> list[str]:
    risks: list[str] = []
    for path, content in list(file_contents.items())[:12]:
        lowered = str(content or "").lower()
        if any(token in lowered for token in ("open(", "requests.", "json.load", "csv.")) and "try:" not in lowered:
            risks.append(f"Limited error handling around external I/O in {path}")
        if any(token in lowered for token in ("c:\\", "/users/", "/tmp/", "localhost")):
            risks.append(f"Contains environment-specific paths or assumptions in {path}")
        if any(token in lowered for token in ("input(", "request.", "query_params", "body")) and "validate" not in lowered:
            risks.append(f"Input validation may be limited in {path}")
        if "test" in os.path.basename(str(path)).lower():
            risks.append(f"Sample or test-oriented code may not represent production behavior in {path}")
        if any(token in lowered for token in ("ollama", "gguf", "local model", "model_path", "llama.cpp")):
            risks.append(f"Dependency on local models may affect runtime availability in {path}")
    return _dedupe(risks)[:6]


def _infer_project_type(file_contents: Dict[str, str], arch_hints: str) -> str:
    combined = " ".join(str(content or "").lower()[:500] for content in list(file_contents.values())[:8])
    joined_paths = " ".join(str(path).lower() for path in file_contents.keys())
    hints = arch_hints.lower()
    if _count_ai_product_signals(joined_paths, combined) >= 2:
        return "AI System"
    if any(token in hints for token in ("fastapi", "flask", "django", "express")) and "react" in hints:
        return "Web App"
    if any(token in hints for token in ("fastapi", "flask", "django", "express", "api layer detected")):
        return "API"
    if "react" in hints:
        return "Web App"
    if any(token in combined for token in ("argparse", "click", "command line", "__main__")):
        return "Tooling"
    return "Not enough information"


def _infer_tech_stack(file_contents: Dict[str, str], arch_hints: str) -> list[str]:
    joined = " ".join(str(content or "").lower()[:800] for content in list(file_contents.values())[:8])
    paths = " ".join(str(path).lower() for path in file_contents.keys())
    stack: list[str] = []
    checks = [
        ("Python", any(path.endswith(".py") for path in file_contents)),
        ("JavaScript", any(path.endswith((".js", ".jsx")) for path in file_contents)),
        ("TypeScript", any(path.endswith((".ts", ".tsx")) for path in file_contents)),
        ("FastAPI", "fastapi" in joined or "fastapi" in arch_hints.lower()),
        ("Flask", "flask" in joined or "flask" in arch_hints.lower()),
        ("Django", "django" in joined or "django" in arch_hints.lower()),
        ("React", "react" in joined or "react" in arch_hints.lower()),
        ("Next.js", "next" in joined or "/app/" in paths or "/pages/" in paths),
        ("Docker", "docker" in paths or "dockerfile" in joined),
        ("Gemini", "gemini" in joined),
        ("Ollama", "ollama" in joined),
        ("Pandas", "pandas" in joined or "import pandas" in joined),
    ]
    for name, matched in checks:
        if matched:
            stack.append(name)
    return _dedupe(stack)[:10] or ["Not enough information"]


def _folder_purpose(name: str) -> str:
    lowered = name.lower()
    if lowered in {"root", "."}:
        return "Holds top-level entrypoints, configuration, and project metadata."
    if lowered in {"api", "routes", "router", "controllers"}:
        return "Defines request handlers and API routing."
    if lowered in {"services", "core"}:
        return "Implements core business logic and orchestration."
    if lowered in {"models", "schemas"}:
        return "Stores data models or validation schemas."
    if lowered in {"components", "pages", "app"}:
        return "Contains UI composition or user-facing application flow."
    if lowered in {"utils", "lib", "helpers"}:
        return "Provides shared helpers and reusable utilities."
    if lowered in {"tests", "test"}:
        return "Contains automated tests or validation scenarios."
    if lowered in {"config", "settings"}:
        return "Stores runtime configuration and environment-specific setup."
    if lowered in {"scripts"}:
        return "Contains automation or developer tooling scripts."
    if lowered in {"data", "datasets"}:
        return "Contains input datasets, fixtures, or generated artifacts."
    if lowered in {"docs", "documentation"}:
        return "Contains project documentation and supporting notes."
    return "Contains feature-specific or supporting implementation files."


def _infer_folder_structure(file_contents: Dict[str, str]) -> list[dict[str, str]]:
    folder_counts: dict[str, int] = {}
    for path in file_contents.keys():
        normalized = str(path).replace("\\", "/").strip("/")
        head = normalized.split("/", 1)[0] if "/" in normalized else "root"
        folder_counts[head] = folder_counts.get(head, 0) + 1
    ranked = sorted(folder_counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"name": name, "purpose": _folder_purpose(name)}
        for name, _count in ranked[:8]
    ] or [{"name": "root", "purpose": "Not enough information"}]


def _module_role(path: str, content: str) -> str:
    normalized = str(path).replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    lowered = str(content or "").lower()
    if basename.startswith(("main.", "app.", "server.", "index.")):
        return "Primary entry point that bootstraps the application or main workflow."
    if basename.startswith("readme"):
        return "Project documentation describing usage or setup."
    if any(token in normalized for token in ("/api/", "/routes/", "/router", "/controllers/")):
        return "Defines API routes or request handlers."
    if any(token in normalized for token in ("/services/", "/core/")):
        return "Implements core business logic and processing steps."
    if any(token in normalized for token in ("/models/", "/schemas/")):
        return "Defines data models or validation contracts."
    if basename in {"package.json", "requirements.txt", "pyproject.toml"}:
        return "Declares dependencies and runtime metadata."
    if any(token in basename for token in ("config", "settings")) or basename in {".env", ".env.example"}:
        return "Stores configuration and environment-specific settings."
    if any(token in lowered for token in ("fastapi", "flask", "express", "@app.", "router.")):
        return "Handles application routing and request flow."
    return "Supporting implementation module for the analyzed project."


def _infer_core_module_details(file_contents: Dict[str, str]) -> list[dict[str, str]]:
    ranked = sorted(
        file_contents.items(),
        key=lambda item: (-_score_file(item[0], item[1]), len(item[0]), item[0]),
    )
    modules: list[dict[str, str]] = []
    for path, content in ranked[:8]:
        modules.append({"file": str(path), "role": _module_role(path, content)})
    return modules or [{"file": "Not enough information", "role": "No non-empty source files were available."}]


def _infer_execution_flow(file_contents: Dict[str, str], classified: Dict[str, list[str]]) -> list[str]:
    files = list(file_contents.keys())
    entrypoint = (classified.get("entry_points", []) or files[:1] or ["Not enough information"])[0]
    flow = [f"Start from {entrypoint}."]
    if classified.get("entry_points"):
        flow.append("Input enters through the detected entrypoint or route layer.")
    else:
        flow.append("No explicit entrypoint was found in the sampled files, so startup flow is inferred from visible modules.")
    if classified.get("service_layer"):
        flow.append(f"Core processing continues through {classified['service_layer'][0]}.")
    else:
        flow.append("Core processing modules are not clearly separated in the sampled files.")
    flow.append("The system returns, renders, or persists the processed output based on the visible code paths.")
    return flow[:4]


def _dependency_usage(name: str) -> str:
    lowered = name.lower()
    if lowered == "fastapi":
        return "Provides API routing and request handling."
    if lowered == "flask":
        return "Provides web routing and server request handling."
    if lowered in {"react", "next"}:
        return "Supports UI rendering and frontend application flow."
    if lowered in {"pandas", "numpy"}:
        return "Supports data processing and structured analysis."
    if lowered in {"requests", "httpx"}:
        return "Handles outbound HTTP requests."
    if lowered in {"pydantic"}:
        return "Validates request and response data structures."
    if lowered in {"google-generativeai", "google-genai", "gemini"}:
        return "Connects the application to Gemini-based generation."
    if lowered == "ollama":
        return "Connects the application to local LLM inference."
    return "Detected from dependency manifests or imports in sampled files."


def _extract_manifest_dependencies(file_contents: Dict[str, str]) -> list[str]:
    detected: list[str] = []
    for path in sorted(file_contents.keys(), key=lambda value: str(value)):
        content = file_contents[path]
        basename = os.path.basename(str(path)).lower()
        text = str(content or "")
        if basename == "package.json":
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {}
            for section in ("dependencies", "devDependencies"):
                block = parsed.get(section, {})
                if isinstance(block, dict):
                    detected.extend(str(name).strip() for name in block.keys() if str(name).strip())
        elif basename == "requirements.txt":
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                detected.append(stripped.split("==")[0].split(">=")[0].split("<=")[0].strip())
    return _dedupe(detected)


def _extract_import_dependencies(file_contents: Dict[str, str]) -> list[str]:
    detected: list[str] = []
    for path in sorted(file_contents.keys(), key=lambda value: str(value)):
        content = file_contents[path]
        for raw_line in str(content or "").splitlines():
            line = raw_line.strip()
            if line.startswith("import "):
                detected.append(line.replace("import ", "", 1).split(" as ")[0].split(".")[0].strip())
            elif line.startswith("from "):
                detected.append(line.replace("from ", "", 1).split(" import ")[0].split(".")[0].strip())
    return _dedupe([item for item in detected if item and not item.startswith(".")])[:10]


def _infer_dependencies(file_contents: Dict[str, str]) -> list[dict[str, str]]:
    names = _dedupe(_extract_manifest_dependencies(file_contents) + _extract_import_dependencies(file_contents))[:8]
    if not names:
        return [{"name": "Not enough information", "usage": "No dependency manifest or import statements were found in the sampled files."}]
    return [{"name": name, "usage": _dependency_usage(name)} for name in names]


def _infer_improvements(
    file_contents: Dict[str, str],
    risks: list[str],
    classified: Dict[str, list[str]],
) -> list[str]:
    improvements: list[str] = []
    lowered_all = " ".join(str(content or "").lower() for content in file_contents.values())
    if any("error handling" in risk.lower() for risk in risks):
        improvements.append("Add structured exception handling and logging around file, network, and parsing operations.")
    if any("validation" in risk.lower() for risk in risks):
        improvements.append("Introduce explicit input validation at API, file-ingest, and parsing boundaries.")
    if any("environment-specific" in risk.lower() for risk in risks):
        improvements.append("Move machine-specific paths and localhost assumptions into environment-driven configuration.")
    if "test" not in " ".join(path.lower() for path in file_contents.keys()):
        improvements.append("Add automated tests for the primary execution paths and failure scenarios.")
    if not classified.get("config_files"):
        improvements.append("Introduce clearer runtime configuration files to separate code from deployment settings.")
    if "docker" not in lowered_all:
        improvements.append("Add deployment packaging or environment documentation for more predictable production setup.")
    return _dedupe(improvements)[:5] or ["Not enough information"]


def _build_overview(
    *,
    project_goal: str,
    project_type: str,
    tech_stack: list[str],
) -> str:
    stack_text = ", ".join(item for item in tech_stack if item != "Not enough information") or "Not enough information"
    if project_goal == "Not enough information":
        return f"{project_type} built with {stack_text}. Not enough information to determine the exact business purpose from the sampled files."
    return f"{project_goal} Project type: {project_type}. Main technologies: {stack_text}."


def _require_llm_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(parsed, dict) or not parsed:
        raise Exception("LLM returned empty response")

    overview = str(parsed.get("overview", "")).strip()
    if not overview:
        raise Exception("LLM returned incomplete response")
    return parsed


async def _call_folder_llm(prompt: str, timeout: int, mode: str) -> Dict[str, Any]:
    started = time.monotonic()
    cache_key = sha256(prompt.encode("utf-8")).hexdigest()
    cached = _folder_cache_get(cache_key)
    if cached:
        return cached
    parsed = await with_timeout(
        call_llm_async(
            prompt,
            timeout=min(timeout, _HARD_LLM_TIMEOUT_SECONDS),
            simplified_prompt=prompt,
            mode=mode,
        ),
        timeout=_HARD_LLM_TIMEOUT_SECONDS,
        fallback={},
    )
    if not isinstance(parsed, dict):
        return {}
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    logger.info(
        "Folder LLM call completed",
        extra={"extra_data": {"latency_ms": latency_ms}},
    )
    parsed = _require_llm_result(parsed)
    _folder_cache_set(cache_key, parsed)
    return parsed


class FolderAnalyzer:
    def __init__(self):
        self.file_handler = FileHandler()
        self.settings = get_settings()

    async def prepare_analysis(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[Dict[str, str], Dict[str, str], str, Dict[str, Any]]:
        file_contents = await with_timeout(
            self.file_handler.process_upload(file_bytes, filename),
            timeout=_FILE_PROCESSING_TIMEOUT_SECONDS,
            fallback={},
        )
        file_contents = self._limit_file_contents(file_contents)
        selected_files = self._select_files(file_contents)
        if not selected_files and file_contents:
            selected_files = dict(list(file_contents.items())[:_MAX_ANALYSIS_FILES])

        arch_hints = _detect_arch_hints(selected_files or file_contents)
        minimal_result = self.generate_minimal_analysis(file_contents or selected_files, filename)
        return file_contents, selected_files, arch_hints, minimal_result

    async def analyze(
        self,
        file_bytes: bytes,
        filename: str,
        progress_callback: ProgressCallback | None = None,
        mode: str = "offline",
    ) -> Dict[str, Any]:
        try:
            await self._emit(progress_callback, "upload")
            prepared = await with_timeout(
                self.prepare_analysis(file_bytes, filename),
                timeout=_FILE_PROCESSING_TIMEOUT_SECONDS,
                fallback=None,
            )
            if not prepared:
                return normalize_analysis_output(compact_result(minimal_safe_response()), evidence_text="")
            file_contents, selected_files, arch_hints, minimal_result = prepared
            return await self.analyze_prepared(
                file_contents=file_contents,
                selected_files=selected_files,
                arch_hints=arch_hints,
                minimal_result=minimal_result,
                filename=filename,
                progress_callback=progress_callback,
                mode=mode,
            )
        except Exception as error:
            logger.error(f"Folder analysis failed: {error}")
            return normalize_analysis_output(compact_result(minimal_safe_response()), evidence_text="")

    async def analyze_prepared(
        self,
        *,
        file_contents: Dict[str, str],
        selected_files: Dict[str, str],
        arch_hints: str,
        minimal_result: Dict[str, Any],
        filename: str,
        progress_callback: ProgressCallback | None = None,
        mode: str = "offline",
    ) -> Dict[str, Any]:
        try:
            uploaded_files = self._to_file_list(selected_files or file_contents)
            if not uploaded_files:
                return minimal_result

            await self._emit(progress_callback, "analyze")
            context = await with_timeout(
                asyncio.to_thread(
                    build_analysis_context,
                    uploaded_files,
                    max_chars_per_file=_MAX_CHARS_PER_FILE,
                    max_context_chars=_MAX_CONTEXT_CHARS,
                ),
                timeout=3,
                fallback="",
            )
            if not context.strip():
                return minimal_result

            await self._emit(progress_callback, "insights")
            try:
                prompt = FOLDER_ANALYSIS_PROMPT.format(
                    context=_build_semantic_context(selected_files or file_contents, filename),
                    file_count=len(uploaded_files),
                    arch_hints=arch_hints,
                    filenames=", ".join(os.path.basename(file_info["path"]) for file_info in uploaded_files),
                )
                parsed = await _call_folder_llm(prompt, _FOLDER_ANALYSIS_TIMEOUT_SECONDS, mode)
                result = self._build_result(parsed, uploaded_files, minimal_result)
            except Exception as llm_error:
                logger.warning(f"Folder semantic enrichment failed, using deterministic fallback: {llm_error}")
                result = compact_result(dict(minimal_result))
            return self._validate_modules(result, uploaded_files, minimal_result)
        except Exception as error:
            logger.error(f"Folder analysis failed: {error}")
            return normalize_analysis_output(compact_result(minimal_result or minimal_safe_response()), evidence_text="")

    async def _emit(self, callback: ProgressCallback | None, message: str) -> None:
        if callback is None:
            return
        maybe_awaitable = callback(message)
        if maybe_awaitable is not None:
            await with_timeout(maybe_awaitable, timeout=1, fallback=None)

    def _limit_file_contents(self, file_contents: Dict[str, str]) -> Dict[str, str]:
        limited: Dict[str, str] = {}
        for path, content in list((file_contents or {}).items())[:_MAX_TOTAL_FILES]:
            text = str(content or "")
            if len(text.encode("utf-8", errors="ignore")) > _MAX_FILE_SIZE_BYTES:
                continue
            if text.strip():
                limited[path] = text
        return limited

    def _select_files(self, file_contents: Dict[str, str]) -> Dict[str, str]:
        file_contents = self._limit_file_contents(file_contents)
        non_empty = {
            path: content.strip()
            for path, content in file_contents.items()
            if content
            and content.strip()
            and os.path.basename(str(path).replace("\\", "/").lower()) not in _LOW_SIGNAL_FILENAMES
        }
        if not non_empty:
            return {}
        ranked = sorted(
            non_empty.items(),
            key=lambda item: (-_score_file(item[0], item[1]), len(item[0]), item[0]),
        )
        limit = max(1, min(int(self.settings.SMART_FILE_SAMPLE_LIMIT or _MAX_ANALYSIS_FILES), _MAX_ANALYSIS_FILES))
        selected = ranked[:limit]
        return dict(selected)

    def _to_file_list(self, file_contents: Dict[str, str]) -> list[Dict[str, str]]:
        file_contents = self._limit_file_contents(file_contents)
        files = [
            {"path": str(path), "content": str(content or ""), "line_count": len(str(content or "").splitlines())}
            for path, content in file_contents.items()
            if str(content or "").strip()
        ]
        if not files:
            return []
        return files[:_MAX_ANALYSIS_FILES]

    def _build_result(
        self,
        parsed: Dict[str, Any],
        uploaded_files: list[Dict[str, str]],
        minimal_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = "\n".join(file_info.get("path", "") for file_info in uploaded_files)
        evidence_text = "\n".join(
            f"{file_info.get('path', '')}\n{str(file_info.get('content', '') or '')[:400]}"
            for file_info in uploaded_files[:8]
        )
        parsed = _coerce_grounded_result(parsed)
        overview = _clean_text(parsed.get("overview")) or minimal_result.get("overview", "Not enough information")
        project_type = _clean_text(parsed.get("project_type")) or minimal_result.get("project_type", "Not enough information")
        execution_flow = parsed.get("execution_flow") if isinstance(parsed.get("execution_flow"), list) else minimal_result.get("execution_flow", [])
        issues = _dedupe([str(item).strip() for item in parsed.get("issues", []) if str(item).strip()]) if isinstance(parsed.get("issues"), list) else list(minimal_result.get("issues", []))
        improvements = _dedupe([str(item).strip() for item in parsed.get("improvements", []) if str(item).strip()]) if isinstance(parsed.get("improvements"), list) else list(minimal_result.get("improvements", []))
        project_goal = _clean_text(parsed.get("project_goal")) or _clean_text(minimal_result.get("project_goal")) or "Insufficient evidence to determine project goal"
        summary_blocks = _normalize_summary_blocks({
            "what": project_goal,
            "why": f"Structured from detected modules, folders, dependencies, and visible execution paths. Project type: {project_type}.",
            "remaining": minimal_result.get("summary_blocks", {}).get("remaining", []),
            "issues": issues or minimal_result.get("issues", []),
        }, len(uploaded_files))
        result = {
            "overview": overview,
            "project_type": project_type,
            "tech_stack": list(minimal_result.get("tech_stack", [])),
            "folder_structure": list(minimal_result.get("folder_structure", [])),
            "core_modules": list(minimal_result.get("core_modules", [])),
            "execution_flow": execution_flow[:6] if execution_flow else list(minimal_result.get("execution_flow", [])),
            "dependencies": list(minimal_result.get("dependencies", [])),
            "issues": issues[:5] if issues else list(minimal_result.get("issues", [])),
            "improvements": improvements[:5] if improvements else list(minimal_result.get("improvements", [])),
            "project_goal": project_goal,
            "domain": str(minimal_result.get("domain", "")).strip(),
            "purpose": str(minimal_result.get("purpose", "")).strip(),
            "target_users": str(minimal_result.get("target_users", "")).strip(),
            "architecture_style": minimal_result["architecture_style"],
            "key_modules": list(minimal_result["key_modules"])[:8],
            "core_features": list(minimal_result["core_features"])[:8],
            "risks": list(minimal_result["risks"])[:8],
            "system_workflow": minimal_result.get("system_workflow", {}),
            "dependency_graph": minimal_result.get("dependency_graph", {}),
            "insights": parsed.get("insights", []),
            "summary": parsed.get("summary", {}),
            "summary_blocks": summary_blocks,
        }
        validation_errors = find_analysis_validation_errors(context, result)
        if validation_errors:
            logger.warning("Correcting invalid folder analysis output", extra={"extra_data": {"errors": validation_errors}})
            result = correct_invalid_analysis_output(context, result, validation_errors)
        result = enforce_truth(result)
        if is_bad_output(result):
            result = safe_fallback()
        return normalize_analysis_output(compact_result(result), evidence_text=evidence_text)

    def _validate_modules(
        self,
        result: Dict[str, Any],
        uploaded_files: list[Dict[str, str]],
        minimal_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        valid_names: set[str] = set()
        for file_info in uploaded_files:
            path = file_info["path"]
            valid_names.add(path)
            valid_names.add(os.path.basename(path))
            valid_names.add(os.path.splitext(os.path.basename(path))[0])

        filtered = [module for module in _dedupe(result.get("key_modules", [])) if module in valid_names]
        if filtered:
            result["key_modules"] = filtered
            return normalize_analysis_output(
                compact_result(result),
                evidence_text="\n".join(file_info.get("path", "") for file_info in uploaded_files),
            )
        return normalize_analysis_output(
            compact_result(minimal_result),
            evidence_text="\n".join(file_info.get("path", "") for file_info in uploaded_files),
        )

    def generate_minimal_analysis(self, file_contents: Dict[str, str], filename: str) -> Dict[str, Any]:
        file_contents = self._limit_file_contents(file_contents)
        files = sorted([
            path for path, content in file_contents.items()
            if str(content or "").strip()
        ], key=lambda value: str(value))
        arch_hints = _detect_arch_hints(file_contents) if file_contents else "general code repository"
        classified = _classify_selected_files(file_contents)
        goal = _infer_project_goal(file_contents, arch_hints)
        project_type = _infer_project_type(file_contents, arch_hints)
        tech_stack = _infer_tech_stack(file_contents, arch_hints)
        features = _infer_features(file_contents)
        risks = _infer_risks(file_contents)
        folder_structure = _infer_folder_structure(file_contents)
        core_modules = _infer_core_module_details(file_contents)
        execution_flow = _infer_execution_flow(file_contents, classified)
        dependencies = _infer_dependencies(file_contents)
        improvements = _infer_improvements(file_contents, risks, classified)
        summary = f"Uploaded archive `{filename}` contains {len(files)} non-empty text files." if filename else f"Project archive contains {len(files)} non-empty text files."
        purpose = "Determined from visible entrypoints, core modules, and dependency signals." if files else "Not enough information"
        target_users = "Developers or operators of the analyzed system." if files else "Not enough information"
        overview = _build_overview(project_goal=goal, project_type=project_type, tech_stack=tech_stack)
        evidence_text = "\n".join(
            f"{path}\n{str(file_contents.get(path, '') or '')[:300]}"
            for path in files[:8]
        )
        return normalize_analysis_output(compact_result({
            "overview": overview,
            "project_type": project_type,
            "tech_stack": tech_stack,
            "folder_structure": folder_structure,
            "core_modules": core_modules,
            "execution_flow": execution_flow,
            "dependencies": dependencies,
            "issues": risks[:5],
            "improvements": improvements,
            "project_goal": goal,
            "domain": _infer_domain(file_contents),
            "purpose": purpose,
            "target_users": target_users,
            "architecture_style": arch_hints,
            "key_modules": (classified.get("entry_points", []) + classified.get("config_files", []) + classified.get("core_modules", []) + files)[:8],
            "core_features": features,
            "risks": risks[:5],
            "system_workflow": {
                "initialization": [f"Start from {(classified.get('entry_points', []) or files[:1] or ['application entrypoint'])[0]}"] if files else [],
                "request_flow": ["Route or trigger enters the main application module"] if classified.get("entry_points") else [],
                "processing_flow": ["Core modules process inputs and execute application logic"] if files else [],
                "response_flow": ["Return or persist the processed result"] if files else [],
            },
            "summary_blocks": {
                "what": goal,
                "why": f"Built from visible entrypoints, folder structure, dependency manifests, and implementation signals. {summary}",
                "remaining": ["README.md not found in uploaded files."] if files and not any(os.path.basename(str(path)).lower().startswith("readme") for path in files) else [],
                "issues": risks[:3] or ["Not enough information"] if not files else risks[:3],
            },
        }), evidence_text=evidence_text)
