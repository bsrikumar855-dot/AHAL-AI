"""
Folder analysis service.

Uses a two-phase pipeline:
1. Static extraction and compact structure summarization
2. LLM enhancement with full, fast, and partial recovery paths
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from hashlib import sha256
from typing import Any, Awaitable, Callable, Dict

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.file_handler import FileHandler
from app.services.intelligence_engine import enrich_result_with_intelligence
from app.services.llm_handler import call_llm_async
from app.services.normalize import normalize_result

logger = get_logger("services.folder_analyzer")

_MAX_ANALYSIS_FILES = 10
_MAX_CHARS_PER_FILE = 1500
_MAX_CONTEXT_CHARS = 8000
_FOLDER_ANALYSIS_TIMEOUT_SECONDS = 55
_FOLDER_FAST_TIMEOUT_SECONDS = 25
_FOLDER_PARTIAL_TIMEOUT_SECONDS = 18
_FOLDER_CACHE_TTL_SECONDS = 600
_FOLDER_ANALYSIS_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}

ProgressCallback = Callable[[str], Awaitable[None] | None]

_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _label_confidence(text: str, confidence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    prefix = f"[{confidence} confidence] "
    return cleaned if cleaned.startswith(prefix) else prefix + cleaned


def _cache_get(cache_key: str) -> Dict[str, Any] | None:
    cached = _FOLDER_ANALYSIS_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _FOLDER_ANALYSIS_CACHE.pop(cache_key, None)
        return None
    return dict(payload)


def _cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    _FOLDER_ANALYSIS_CACHE[cache_key] = (time.time() + _FOLDER_CACHE_TTL_SECONDS, dict(payload))
    if len(_FOLDER_ANALYSIS_CACHE) > 128:
        oldest_key = min(_FOLDER_ANALYSIS_CACHE, key=lambda key: _FOLDER_ANALYSIS_CACHE[key][0])
        _FOLDER_ANALYSIS_CACHE.pop(oldest_key, None)


FOLDER_ANALYSIS_PROMPT = """You MUST return valid JSON. If data is missing, infer ONLY from visible code. NEVER return empty response.

Analyze this project's source files and return ONLY valid JSON.

PROJECT FILES:
{context}

DETECTED STRUCTURE:
- File count: {file_count}
- Architecture hints: {arch_hints}
- Key filenames: {filenames}

OUTPUT (JSON only - no markdown, no explanation):
{{
  "project_goal": "one sentence: what this project does",
  "architecture_style": "specific label (microservice, layered, monolith, MVC, etc.)",
  "key_modules": ["REAL filenames from the === FILE: headers === ONLY"],
  "core_features": ["specific implemented capability - NOT generic"],
  "risks": ["concrete risk found in the code"],
  "summary_blocks": {{
    "what": "precise summary of the project",
    "why": "why this project exists",
    "remaining": ["specific improvement needed"],
    "issues": ["specific weakness or problem"]
  }}
}}

RULES:
- key_modules = ONLY real filenames from the === FILE: headers ===
- core_features = derive from actual file roles, not generic
- Detect architecture: microservice, layered, monolith, MVC, serverless
- Every list must have at least 2 items
- NEVER return empty arrays
- Return JSON ONLY"""

FOLDER_FAST_PROMPT = """Analyze this compact project snapshot and return ONLY valid JSON.

PROJECT SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the project appears to do",
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only"],
  "core_features": ["implemented capabilities"],
  "risks": ["concrete technical risks"],
  "summary_blocks": {{
    "what": "clear explanation of the project",
    "why": "why the project likely exists",
    "remaining": ["practical next step"],
    "issues": ["important weakness"]
  }}
}}

Return JSON ONLY."""

FOLDER_GOAL_PROMPT = """Return ONLY valid JSON for the project goal and core features.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the project does",
  "core_features": ["implemented capability", "second implemented capability"]
}}"""

FOLDER_ARCH_PROMPT = """Return ONLY valid JSON for the project architecture and key modules.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only", "second filename"],
  "summary_blocks": {{
    "what": "how the project is structured",
    "why": "what the structure suggests about responsibilities"
  }}
}}"""

FOLDER_RISK_PROMPT = """Return ONLY valid JSON for the project risks and next steps.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "risks": ["concrete risk", "second concrete risk"],
  "summary_blocks": {{
    "remaining": ["practical next step", "second next step"],
    "issues": ["notable weakness", "second weakness"]
  }}
}}"""


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
    if "/services/" in paths:
        hints.append("service layer detected")
    if "/models/" in paths:
        hints.append("model layer detected")
    if "docker" in paths:
        hints.append("containerized")
    return ", ".join(hints) if hints else "general code repository"


def _build_folder_snapshot(selected_files: Dict[str, str], arch_hints: str) -> str:
    lines = [
        f"Architecture hints: {arch_hints}",
        f"Selected files: {', '.join(list(selected_files.keys())[:10])}",
    ]
    for path, content in list(selected_files.items())[:6]:
        snippet = " ".join(content.split())
        if len(snippet) > 260:
            snippet = snippet[:257].rstrip() + "..."
        lines.append(f"{path}: {snippet}")
    return "\n".join(lines)


def force_non_empty_output(result: Dict[str, Any], selected_files: Dict[str, str] | None = None) -> Dict[str, Any]:
    sb = result.setdefault("summary_blocks", {})
    files = selected_files or {}

    if not result.get("key_modules"):
        result["key_modules"] = [os.path.basename(path) for path in list(files.keys())[:5]]

    if not result.get("core_features"):
        features = []
        combined = "\n".join(files.values())
        functions = _dedupe(_FUNCTION_RE.findall(combined))[:4]
        classes = _dedupe(_CLASS_RE.findall(combined))[:4]
        if functions:
            features.append(f"Defines functions: {', '.join(functions[:3])}")
        if classes:
            features.append(f"Defines classes: {', '.join(classes[:3])}")
        result["core_features"] = features or ["Project structure analysis", "Module detection"]

    if not result.get("risks"):
        result["risks"] = [
            "No obvious critical risks were surfaced in the prioritized file sample",
            "A deeper pass across more files would improve dependency coverage",
        ]

    if len(str(result.get("project_goal", "")).strip()) <= 5:
        result["project_goal"] = f"Project with {len(files)} analyzed source files"

    if len(str(result.get("architecture_style", "")).strip()) <= 5:
        result["architecture_style"] = _detect_arch_hints(files) if files else "Software project"

    if not sb.get("what"):
        sb["what"] = _label_confidence(f"Analyzed {len(files)} prioritized source files", "MEDIUM")
    if not sb.get("why"):
        sb["why"] = _label_confidence("Partial analysis completed from project structure, prioritized files, and execution hints. Deeper semantic refinement can extend this view.", "MEDIUM")
    if not sb.get("remaining"):
        sb["remaining"] = ["Analyze additional files for deeper coverage", "Review deployment and configuration paths"]
    if not sb.get("issues"):
        sb["issues"] = ["Review recommended for production readiness", "Some runtime behavior may require deeper AI inspection"]

    result["summary_blocks"] = sb
    return result


def _smart_folder_fallback(selected_files: Dict[str, str], arch_hints: str) -> Dict[str, Any]:
    modules = [os.path.basename(path) for path in list(selected_files.keys())[:6]]
    combined = "\n".join(selected_files.values())
    functions = _dedupe(_FUNCTION_RE.findall(combined))[:4]
    classes = _dedupe(_CLASS_RE.findall(combined))[:4]
    features: list[str] = []
    if functions:
        features.append(f"Core logic is implemented through functions such as {', '.join(functions[:3])}")
    if classes:
        features.append(f"Important domain structure appears in classes such as {', '.join(classes[:3])}")
    if not features:
        features = [
            f"The project is organized around modules like {', '.join(modules[:3])}",
            f"The codebase suggests {arch_hints or 'a structured application layout'}",
        ]

    return {
        "project_goal": f"A structured application workspace centered on modules such as {', '.join(modules[:3])}, designed to support the main workflow inferred from the analyzed project files.",
        "architecture_style": arch_hints or "Structured application",
        "key_modules": modules,
        "core_features": features,
        "risks": [
            "Some reasoning is inferred from prioritized files instead of the full project tree",
            "Cross-file runtime flow may benefit from a deeper AI pass",
        ],
        "summary_blocks": {
            "what": _label_confidence("The project is organized around prioritized source files and appears to separate key responsibilities into focused modules.", "MEDIUM"),
            "why": _label_confidence("Partial analysis completed from project structure, sampled files, and inferred execution paths. Deeper semantic refinement can extend this view.", "MEDIUM"),
            "remaining": ["Inspect additional files for wider dependency coverage", "Validate inferred architecture against environment and deployment files"],
            "issues": ["Some architectural conclusions are inferred from sampled files", "Cross-module execution paths may need deeper verification"],
        },
    }


def _merge_result(base: Dict[str, Any], update: Dict[str, Any] | None) -> Dict[str, Any]:
    if not update:
        return base
    for field in ("project_goal", "architecture_style"):
        value = str(update.get(field, "")).strip()
        if value:
            base[field] = value
    for field in ("key_modules", "core_features", "risks"):
        values = _dedupe([str(item) for item in update.get(field, []) if str(item).strip()])
        if values:
            current = _dedupe([str(item) for item in base.get(field, []) if str(item).strip()])
            base[field] = _dedupe(current + values)

    base_blocks = base.setdefault("summary_blocks", {})
    update_blocks = update.get("summary_blocks", {})
    if isinstance(update_blocks, dict):
        for field in ("what", "why"):
            value = str(update_blocks.get(field, "")).strip()
            if value:
                base_blocks[field] = value
        for field in ("remaining", "issues"):
            values = _dedupe([str(item) for item in update_blocks.get(field, []) if str(item).strip()])
            if values:
                current = _dedupe([str(item) for item in base_blocks.get(field, []) if str(item).strip()])
                base_blocks[field] = _dedupe(current + values)
    base["summary_blocks"] = base_blocks
    return base


async def _call_folder_llm(prompt: str, timeout: int, mode: str, label: str) -> Dict[str, Any] | None:
    try:
        started = time.monotonic()
        parsed = await call_llm_async(
            prompt,
            timeout=timeout,
            simplified_prompt=prompt,
            mode=mode,
        )
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        print(f"[FOLDER][{label}] LLM latency: {latency_ms}ms")
        return parsed
    except Exception as exc:
        print(f"[FOLDER][{label}] LLM failure: {exc}")
        logger.warning(f"Folder {label} LLM failure: {exc}")
        return None


async def _run_folder_llm_enhancement(selected_files: Dict[str, str], context: str, arch_hints: str, mode: str) -> Dict[str, Any]:
    cache_key = sha256(("|".join(selected_files.keys()) + "|" + sha256(context.encode("utf-8")).hexdigest()).encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        print("[FOLDER] Analysis cache hit")
        return cached

    snapshot = _build_folder_snapshot(selected_files, arch_hints)
    base_result = _smart_folder_fallback(selected_files, arch_hints)

    full_prompt = FOLDER_ANALYSIS_PROMPT.format(
        context=context,
        file_count=len(selected_files),
        arch_hints=arch_hints,
        filenames=", ".join(os.path.basename(p) for p in selected_files.keys()),
    )
    print(f"[FOLDER] files_sent={len(selected_files)}, context_size={len(context)}, prompt_size={len(full_prompt)}")
    full_result = await _call_folder_llm(full_prompt, _FOLDER_ANALYSIS_TIMEOUT_SECONDS, mode, "full")
    if full_result:
        merged = _merge_result(base_result, full_result)
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(merged["summary_blocks"].get("why", ""), "HIGH")
        _cache_set(cache_key, merged)
        return merged

    await asyncio.sleep(1.0)
    fast_result = await _call_folder_llm(FOLDER_FAST_PROMPT.format(snapshot=snapshot), _FOLDER_FAST_TIMEOUT_SECONDS, mode, "fast")
    if fast_result:
        merged = _merge_result(base_result, fast_result)
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(
            merged["summary_blocks"].get("why", "") or "Partial analysis completed and refined through targeted AI passes.",
            "HIGH",
        )
        _cache_set(cache_key, merged)
        return merged

    merged = dict(base_result)
    partial_successes = 0
    partial_specs = [
        ("goal", FOLDER_GOAL_PROMPT.format(snapshot=snapshot)),
        ("architecture", FOLDER_ARCH_PROMPT.format(snapshot=snapshot)),
        ("risks", FOLDER_RISK_PROMPT.format(snapshot=snapshot)),
    ]
    for index, (label, partial_prompt) in enumerate(partial_specs, start=1):
        partial = await _call_folder_llm(partial_prompt, _FOLDER_PARTIAL_TIMEOUT_SECONDS, mode, label)
        if partial:
            partial_successes += 1
            merged = _merge_result(merged, partial)
        if index < len(partial_specs):
            await asyncio.sleep(1.0)

    if partial_successes > 0:
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(
            "Partial analysis completed through targeted AI recovery plus structural inference from the project snapshot.",
            "HIGH",
        )
        _cache_set(cache_key, merged)
        return merged

    _cache_set(cache_key, base_result)
    return base_result


class FolderAnalyzer:
    _ENTRYPOINT_FILES = {"main.py", "app.py", "index.js", "index.ts", "server.py"}
    _CONFIG_FILES = {
        "config.py", "settings.py", "requirements.txt", "pyproject.toml",
        "package.json", "dockerfile", "docker-compose.yml",
    }
    _SERVICE_KEYWORDS = {"service", "controller", "handler", "model", "route", "api", "middleware"}
    _LOW_PRIORITY = {"test", "spec", "mock", "fixture", "dist", "build", "__pycache__", ".min."}

    def __init__(self):
        self.file_handler = FileHandler()
        self.settings = get_settings()

    async def prepare_analysis(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[Dict[str, str], Dict[str, str], str, Dict[str, Any]]:
        file_contents = await self.file_handler.process_upload(file_bytes, filename)
        if not file_contents:
            raise Exception("No analyzable files found in upload")

        selected_files = self._select_top_files(file_contents)
        if not selected_files:
            raise Exception("No prioritized files found in upload")

        arch_hints = _detect_arch_hints(selected_files)
        quick_result = normalize_result(force_non_empty_output(_smart_folder_fallback(selected_files, arch_hints), selected_files))
        quick_result = normalize_result(
            enrich_result_with_intelligence(
                session_type="folder",
                result=quick_result,
                sampled_files=[{"path": path, "content": content} for path, content in selected_files.items()],
            )
        )
        return file_contents, selected_files, arch_hints, quick_result

    async def analyze(
        self,
        file_bytes: bytes,
        filename: str,
        progress_callback: ProgressCallback | None = None,
        mode: str = "offline",
    ) -> Dict[str, Any]:
        started_total = time.monotonic()

        await self._emit(progress_callback, "Extracting files...")
        file_contents, selected_files, arch_hints, _quick_result = await self.prepare_analysis(file_bytes, filename)

        await self._emit(progress_callback, "Selecting top files...")
        selected_names = list(selected_files.keys())
        logger.info("Files selected for analysis", extra={"extra_data": {
            "endpoint": "folder",
            "total_files": len(file_contents),
            "selected_files": selected_names,
            "selected_count": len(selected_names),
        }})

        context = self._build_context(selected_files)
        if not context.strip():
            raise Exception("Empty context after file processing")

        logger.info("Context built", extra={"extra_data": {
            "endpoint": "folder",
            "context_size": len(context),
            "arch_hints": arch_hints,
        }})

        await self._emit(progress_callback, "Enhancing analysis with AI...")
        llm_started = time.monotonic()
        parsed = await _run_folder_llm_enhancement(selected_files, context, arch_hints, mode)
        llm_ms = round((time.monotonic() - llm_started) * 1000, 2)
        total_ms = round((time.monotonic() - started_total) * 1000, 2)

        is_fallback = str(parsed.get("summary_blocks", {}).get("why", "")).startswith("[MEDIUM confidence]")
        print(f"[FOLDER] LLM enhancement completed: fallback={is_fallback}, llm_time={llm_ms}ms")
        logger.info("Folder analysis complete", extra={"extra_data": {
            "endpoint": "folder",
            "mode": mode,
            "llm_time_ms": llm_ms,
            "total_time_ms": total_ms,
            "fallback": is_fallback,
            "files_selected": selected_names,
            "context_size": len(context),
        }})

        await self._emit(progress_callback, "Generating output...")
        result = self._build_result(parsed)
        validated = self._validate_modules(result, selected_files)
        normalized = normalize_result(force_non_empty_output(validated, selected_files))
        return normalize_result(
            enrich_result_with_intelligence(
                session_type="folder",
                result=normalized,
                sampled_files=[{"path": path, "content": content} for path, content in selected_files.items()],
            )
        )

    async def _emit(self, callback: ProgressCallback | None, message: str) -> None:
        if callback is None:
            return
        maybe_awaitable = callback(message)
        if maybe_awaitable is not None:
            await maybe_awaitable

    def _score_file(self, rel_path: str, content: str) -> int:
        lowered = rel_path.lower().replace("\\", "/")
        basename = os.path.basename(lowered)
        if any(token in lowered for token in self._LOW_PRIORITY):
            return 0
        if basename in self._ENTRYPOINT_FILES:
            return 400
        if any(keyword in lowered for keyword in self._SERVICE_KEYWORDS):
            return 300
        if basename in self._CONFIG_FILES or lowered.endswith((".yml", ".yaml", ".toml")):
            return 200
        return 100

    def _select_top_files(self, file_contents: Dict[str, str]) -> Dict[str, str]:
        non_empty = {
            path: content.strip()
            for path, content in file_contents.items()
            if content and content.strip()
        }
        ranked = sorted(
            non_empty.items(),
            key=lambda item: self._score_file(item[0], item[1]),
            reverse=True,
        )
        top_limit = min(self.settings.SMART_FILE_SAMPLE_LIMIT, _MAX_ANALYSIS_FILES)
        return {path: content for path, content in ranked[:top_limit]}

    def _truncate_content(self, content: str) -> str:
        if len(content) <= _MAX_CHARS_PER_FILE:
            return content
        head_size = _MAX_CHARS_PER_FILE * 2 // 3
        tail_size = _MAX_CHARS_PER_FILE // 3
        return content[:head_size].rstrip() + "\n...(middle trimmed)...\n" + content[-tail_size:].lstrip()

    def _build_context(self, selected_files: Dict[str, str]) -> str:
        parts = []
        total = 0
        for path, content in selected_files.items():
            truncated = self._truncate_content(content)
            snippet = f"=== FILE: {path} ===\n{truncated}"
            if total + len(snippet) > _MAX_CONTEXT_CHARS:
                remaining = _MAX_CONTEXT_CHARS - total
                if remaining > 200:
                    parts.append(snippet[:remaining])
                break
            parts.append(snippet)
            total += len(snippet)
        return "\n\n".join(parts)

    def _build_result(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        summary_blocks = parsed.get("summary_blocks", {})
        if not isinstance(summary_blocks, dict):
            summary_blocks = {}
        return {
            "project_goal": parsed.get("project_goal", ""),
            "architecture_style": parsed.get("architecture_style", ""),
            "key_modules": parsed.get("key_modules", []),
            "core_features": _dedupe([str(x) for x in parsed.get("core_features", [])])[:8],
            "risks": _dedupe([str(x) for x in parsed.get("risks", [])])[:6],
            "summary_blocks": {
                "what": str(summary_blocks.get("what", "")).strip(),
                "why": str(summary_blocks.get("why", "")).strip(),
                "remaining": _dedupe([str(x) for x in summary_blocks.get("remaining", [])])[:6],
                "issues": _dedupe([str(x) for x in summary_blocks.get("issues", [])])[:6],
            },
        }

    def _validate_modules(self, result: Dict[str, Any], selected_files: Dict[str, str]) -> Dict[str, Any]:
        valid_names: set[str] = set()
        for path in selected_files:
            valid_names.add(path)
            valid_names.add(os.path.basename(path))
            valid_names.add(os.path.splitext(os.path.basename(path))[0])

        filtered = [m for m in _dedupe([str(x) for x in result.get("key_modules", [])]) if m in valid_names]
        if not filtered:
            filtered = [os.path.basename(p) for p in list(selected_files.keys())[:5]]
        result["key_modules"] = filtered
        return result
