"""
Folder analysis service.
"""

from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable, Dict

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.context_builder import build_analysis_context
from app.services.file_handler import FileHandler
from app.services.llm_handler import call_llm_async

logger = get_logger("services.folder_analyzer")

_MAX_ANALYSIS_FILES = 10
_MAX_CHARS_PER_FILE = 1500
_MAX_CONTEXT_CHARS = 8000
_FOLDER_ANALYSIS_TIMEOUT_SECONDS = 90

ProgressCallback = Callable[[str], Awaitable[None] | None]

FOLDER_ANALYSIS_PROMPT = """You MUST return valid JSON.

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
  "architecture_style": "specific label",
  "key_modules": [],
  "core_features": [],
  "risks": [],
  "summary_blocks": {{
    "what": "precise summary of the project",
    "why": "why this project exists",
    "remaining": [],
    "issues": []
  }}
}}

RULES:
- key_modules = ONLY real filenames from the uploaded files
- If no real items exist for a list, return []
- Do NOT invent data
- Return JSON ONLY."""


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


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


def _normalize_summary_blocks(summary_blocks: Any, file_count: int) -> Dict[str, Any]:
    payload = summary_blocks if isinstance(summary_blocks, dict) else {}
    return {
        "what": str(payload.get("what", "")).strip() or f"Project archive with {file_count} non-empty text files.",
        "why": str(payload.get("why", "")).strip() or "Provides source files for project inspection.",
        "remaining": _dedupe([str(x) for x in payload.get("remaining", []) if str(x).strip()]),
        "issues": _dedupe([str(x) for x in payload.get("issues", []) if str(x).strip()]),
    }


def _require_llm_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(parsed, dict) or not parsed:
        raise Exception("LLM returned empty response")

    project_goal = str(parsed.get("project_goal", "")).strip()
    architecture_style = str(parsed.get("architecture_style", "")).strip()
    if not project_goal or not architecture_style:
        raise Exception("LLM returned incomplete response")

    parsed["summary_blocks"] = _normalize_summary_blocks(parsed.get("summary_blocks", {}), 0)
    return parsed


async def _call_folder_llm(prompt: str, timeout: int, mode: str) -> Dict[str, Any]:
    started = time.monotonic()
    parsed = await call_llm_async(
        prompt,
        timeout=timeout,
        simplified_prompt=prompt,
        mode=mode,
    )
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    logger.info(
        "Folder LLM call completed",
        extra={"extra_data": {"latency_ms": latency_ms}},
    )
    return _require_llm_result(parsed)


class FolderAnalyzer:
    def __init__(self):
        self.file_handler = FileHandler()
        self.settings = get_settings()

    async def prepare_analysis(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[Dict[str, str], Dict[str, str], str, Dict[str, Any]]:
        file_contents = await self.file_handler.process_upload(file_bytes, filename)
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
            await self._emit(progress_callback, "Extracting files...")
            file_contents, selected_files, arch_hints, minimal_result = await self.prepare_analysis(file_bytes, filename)

            uploaded_files = self._to_file_list(selected_files or file_contents)
            if not uploaded_files:
                return minimal_result

            await self._emit(progress_callback, "Building context...")
            context = build_analysis_context(
                uploaded_files,
                max_chars_per_file=_MAX_CHARS_PER_FILE,
                max_context_chars=_MAX_CONTEXT_CHARS,
            )
            if not context.strip():
                return minimal_result

            await self._emit(progress_callback, "Calling LLM...")
            prompt = FOLDER_ANALYSIS_PROMPT.format(
                context=context,
                file_count=len(uploaded_files),
                arch_hints=arch_hints,
                filenames=", ".join(os.path.basename(file_info["path"]) for file_info in uploaded_files),
            )
            parsed = await _call_folder_llm(prompt, _FOLDER_ANALYSIS_TIMEOUT_SECONDS, mode)
            result = self._build_result(parsed, uploaded_files, minimal_result)
            return self._validate_modules(result, uploaded_files, minimal_result)
        except Exception as error:
            logger.error(f"Folder analysis failed: {error}")
            file_contents = {}
            try:
                file_contents = await self.file_handler.process_upload(file_bytes, filename)
            except Exception:
                file_contents = {}
            return self.generate_minimal_analysis(file_contents, filename)

    async def _emit(self, callback: ProgressCallback | None, message: str) -> None:
        if callback is None:
            return
        maybe_awaitable = callback(message)
        if maybe_awaitable is not None:
            await maybe_awaitable

    def _select_files(self, file_contents: Dict[str, str]) -> Dict[str, str]:
        non_empty = {
            path: content.strip()
            for path, content in file_contents.items()
            if content and content.strip()
        }
        if not non_empty:
            return {}
        selected = list(non_empty.items())[: min(self.settings.SMART_FILE_SAMPLE_LIMIT, _MAX_ANALYSIS_FILES)]
        return dict(selected)

    def _to_file_list(self, file_contents: Dict[str, str]) -> list[Dict[str, str]]:
        files = [
            {"path": str(path), "content": str(content or "")}
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
        summary_blocks = _normalize_summary_blocks(parsed.get("summary_blocks", {}), len(uploaded_files))
        result = {
            "project_goal": str(parsed.get("project_goal", "")).strip() or minimal_result["project_goal"],
            "architecture_style": str(parsed.get("architecture_style", "")).strip() or minimal_result["architecture_style"],
            "key_modules": _dedupe([str(x) for x in parsed.get("key_modules", []) if str(x).strip()])[:8],
            "core_features": _dedupe([str(x) for x in parsed.get("core_features", []) if str(x).strip()])[:8],
            "risks": _dedupe([str(x) for x in parsed.get("risks", []) if str(x).strip()])[:8],
            "summary_blocks": summary_blocks,
        }

        if not result["summary_blocks"]["what"]:
            result["summary_blocks"]["what"] = minimal_result["summary_blocks"]["what"]
        if not result["summary_blocks"]["why"]:
            result["summary_blocks"]["why"] = minimal_result["summary_blocks"]["why"]
        return result

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
            return result
        return minimal_result

    def generate_minimal_analysis(self, file_contents: Dict[str, str], filename: str) -> Dict[str, Any]:
        files = [
            path for path, content in file_contents.items()
            if str(content or "").strip()
        ]
        arch_hints = _detect_arch_hints(file_contents) if file_contents else "general code repository"
        summary = f"Uploaded archive `{filename}` contains {len(files)} non-empty text files." if filename else f"Project archive contains {len(files)} non-empty text files."
        return {
            "project_goal": "Uploaded project archive for source inspection.",
            "architecture_style": arch_hints,
            "key_modules": files[:8],
            "core_features": [],
            "risks": [],
            "summary_blocks": {
                "what": summary,
                "why": "Provides project files for analysis.",
                "remaining": [],
                "issues": [],
            },
        }
