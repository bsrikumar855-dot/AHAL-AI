"""
Code analysis service.

Uses a two-phase pipeline:
1. Static extraction for structure and prompt compression
2. LLM enhancement with full, fast, and partial recovery paths
"""

from __future__ import annotations

import asyncio
import re
import time
from hashlib import sha256
from typing import Any, Dict

from app.core.logging import get_logger
from app.services.llm_handler import call_llm_async
from app.services.normalize import normalize_result
from app.services.task_router import TaskType, validate_analysis_output

logger = get_logger("services.code_analyzer")

_CODE_ANALYSIS_TIMEOUT_SECONDS = 90
_CODE_FAST_TIMEOUT_SECONDS = 45
_CODE_PARTIAL_TIMEOUT_SECONDS = 30
_CODE_CACHE_TTL_SECONDS = 600
_MAX_CODE_LENGTH = 8000
_CODE_ANALYSIS_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}

_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))",
    re.MULTILINE,
)
_DECORATOR_RE = re.compile(r"@(\w+(?:\.\w+)*)", re.MULTILINE)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _detect_language(code: str) -> str:
    if re.search(r"^\s*def\s+|^\s*import\s+|^\s*from\s+\w+\s+import", code, re.MULTILINE):
        return "Python"
    if re.search(r"\b(const|let|var|function)\b.*[=({]", code):
        if re.search(r":\s*(string|number|boolean|interface|type)\b", code):
            return "TypeScript"
        return "JavaScript"
    if re.search(r"\bpackage\s+\w+|public\s+class\s+", code):
        return "Java"
    return ""


def _detect_pattern(code: str, functions: list[str], classes: list[str], imports: list[str]) -> str:
    code_lower = code.lower()
    if "fastapi" in code_lower or "@app.get" in code_lower or "@app.post" in code_lower:
        return "FastAPI endpoint"
    if "flask" in code_lower or "@app.route" in code_lower:
        return "Flask endpoint"
    if "express" in code_lower or "app.listen" in code_lower:
        return "Express.js server"
    if "react" in code_lower or "usestate" in code_lower or "jsx" in code_lower:
        return "React component"
    if "django" in code_lower:
        return "Django view"
    if classes and not functions:
        return "Class definition"
    if functions and not classes:
        return "Single function" if len(functions) == 1 else "Function library"
    if classes and functions:
        return "Class-based module"
    if imports:
        return "Imported module"
    if "if __name__" in code:
        return "Executable script"
    return "Utility script"


def _extract_static_info(code: str) -> Dict[str, Any]:
    functions = _dedupe(_FUNCTION_RE.findall(code))
    classes = _dedupe(_CLASS_RE.findall(code))
    imports = _dedupe([m[0] or m[1] for m in _IMPORT_RE.findall(code)])
    decorators = _dedupe(_DECORATOR_RE.findall(code))
    language = _detect_language(code)
    pattern = _detect_pattern(code, functions, classes, imports)
    return {
        "functions": functions[:10],
        "classes": classes[:10],
        "imports": imports[:10],
        "decorators": decorators[:10],
        "language": language,
        "pattern": pattern,
    }


def _truncate_code(code: str) -> str:
    if len(code) <= _MAX_CODE_LENGTH:
        return code
    half = _MAX_CODE_LENGTH // 2
    return code[:half] + "\n...(truncated)...\n" + code[-half:]


def _build_code_snapshot(code: str, static: Dict[str, Any]) -> str:
    compact_code = " ".join(code.split())
    if len(compact_code) > 900:
        compact_code = compact_code[:897].rstrip() + "..."
    return "\n".join([
        f"Language: {static.get('language', '')}",
        f"Pattern: {static.get('pattern', '')}",
        f"Functions: {', '.join(static.get('functions', [])[:6]) or '(none)'}",
        f"Classes: {', '.join(static.get('classes', [])[:6]) or '(none)'}",
        f"Imports: {', '.join(static.get('imports', [])[:6]) or '(none)'}",
        f"Code snippet: {compact_code}",
    ])


def _label_confidence(text: str, confidence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    prefix = f"[{confidence} confidence] "
    return cleaned if cleaned.startswith(prefix) else prefix + cleaned


def _cache_get(cache_key: str) -> Dict[str, Any] | None:
    return None


def _cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    return None


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


def _internal_input_detected(code: str) -> bool:
    lowered = code.lower()
    return "base_prompt" in lowered or "prompt =" in lowered


def _invalid_input_response() -> Dict[str, Any]:
    return {
        "project_goal": "Invalid input - system prompt detected",
        "architecture_style": "",
        "key_modules": [],
        "core_features": ["Internal system code detected"],
        "risks": ["Wrong input passed to analyzer"],
        "summary_blocks": {
            "what": "System prompt detected instead of user code",
            "why": "Pipeline error - internal prompt leaked as input",
            "remaining": ["Re-submit actual code for analysis"],
            "issues": ["Input validation bypass"],
        },
    }


def _empty_code_result(static: Dict[str, Any] | None = None) -> Dict[str, Any]:
    static = static or {}
    modules = []
    modules.extend(static.get("functions", [])[:4])
    modules.extend(static.get("classes", [])[:4])
    return {
        "project_goal": "",
        "architecture_style": static.get("pattern", ""),
        "key_modules": modules,
        "core_features": [],
        "risks": [],
        "summary_blocks": {
            "what": "",
            "why": "",
            "remaining": [],
            "issues": [],
        },
    }


CODE_PROMPT = """Analyze this {language} code and return ONLY valid JSON.

DETECTED STRUCTURE:
- Language: {language}
- Pattern: {pattern}
- Functions: {functions}
- Classes: {classes}
- Imports: {imports}

CODE:
{code}

OUTPUT (JSON only - no markdown, no explanation):
{{
  "project_goal": "one sentence: what this code does",
  "architecture_style": "specific label (e.g. FastAPI endpoint, utility script, class module)",
  "key_modules": ["REAL function/class names from the code ONLY"],
  "core_features": ["specific implemented behavior - NOT generic"],
  "risks": ["concrete risk: missing validation, no error handling, unsafe ops"],
  "summary_blocks": {{
    "what": "precise description of what the code does",
    "why": "why this code exists",
    "remaining": ["specific improvement needed"],
    "issues": ["specific weakness or problem"]
  }}
}}

RULES:
- key_modules = ONLY real names from the code (functions, classes)
- If no real key_modules exist, return []
- core_features = ACTUAL behavior, not generic phrases
- risks = concrete issues, not vague warnings
- Lists MAY be empty
- Do NOT invent data
- Return JSON ONLY"""

CODE_FAST_PROMPT = """Analyze this code snapshot and return ONLY valid JSON.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what this code does",
  "architecture_style": "best label for this code structure",
  "key_modules": ["real function or class names only"],
  "core_features": ["implemented behaviors"],
  "risks": ["concrete technical risks"],
  "summary_blocks": {{
    "what": "clear explanation of the code",
    "why": "why this code likely exists",
    "remaining": ["practical improvement"],
    "issues": ["important weakness"]
  }}
}}

Return JSON ONLY."""

CODE_GOAL_PROMPT = """Return ONLY valid JSON for the goal and core features of this code.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what this code does",
  "core_features": ["implemented behavior", "second implemented behavior"]
}}"""

CODE_ARCH_PROMPT = """Return ONLY valid JSON for the architecture and key modules of this code.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "architecture_style": "best code structure label",
  "key_modules": ["real function or class names only", "second name"],
  "summary_blocks": {{
    "what": "how the code is structured",
    "why": "what the structure implies"
  }}
}}"""

CODE_RISK_PROMPT = """Return ONLY valid JSON for the risks and next steps of this code.

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


async def _call_code_llm(prompt: str, timeout: int, mode: str, label: str) -> Dict[str, Any] | None:
    try:
        started = time.monotonic()
        parsed = await call_llm_async(
            prompt,
            timeout=timeout,
            simplified_prompt=prompt,
            mode=mode,
        )
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        print(f"[CODE][{label}] LLM latency: {latency_ms}ms")
        return parsed
    except Exception as exc:
        print(f"[CODE][{label}] LLM failure: {exc}")
        logger.warning(f"Code {label} LLM failure: {exc}")
        return None


async def _run_code_llm_enhancement(code: str, static: Dict[str, Any], prompt: str, mode: str) -> Dict[str, Any]:
    snapshot = _build_code_snapshot(code, static)

    full_result = await _call_code_llm(prompt, _CODE_ANALYSIS_TIMEOUT_SECONDS, mode, "full")
    if full_result:
        return _merge_result(_empty_code_result(static), full_result)

    await asyncio.sleep(1.0)
    fast_result = await _call_code_llm(CODE_FAST_PROMPT.format(snapshot=snapshot), _CODE_FAST_TIMEOUT_SECONDS, mode, "fast")
    if fast_result:
        return _merge_result(_empty_code_result(static), fast_result)

    merged = dict(_empty_code_result(static))
    partial_successes = 0
    partial_specs = [
        ("goal", CODE_GOAL_PROMPT.format(snapshot=snapshot)),
        ("architecture", CODE_ARCH_PROMPT.format(snapshot=snapshot)),
        ("risks", CODE_RISK_PROMPT.format(snapshot=snapshot)),
    ]
    for index, (label, partial_prompt) in enumerate(partial_specs, start=1):
        partial = await _call_code_llm(partial_prompt, _CODE_PARTIAL_TIMEOUT_SECONDS, mode, label)
        if partial:
            partial_successes += 1
            merged = _merge_result(merged, partial)
        if index < len(partial_specs):
            await asyncio.sleep(1.0)

    if partial_successes > 0:
        return merged

    raise RuntimeError("LLM_FAILED: Fresh analysis failed")


class CodeAnalyzer:
    def build_quick_result(self, code: str) -> Dict[str, Any]:
        static = _extract_static_info(code)
        base = normalize_result(_empty_code_result(static))
        return validate_analysis_output(base, TaskType.PROJECT_ANALYSIS)

    async def analyze(self, code: str, mode: str = "offline") -> Dict[str, Any]:
        started_total = time.monotonic()

        if _internal_input_detected(code):
            logger.warning("Blocked internal prompt-like input from code analysis")
            return normalize_result(_invalid_input_response())

        static = _extract_static_info(code)
        logger.info("Code static extraction complete", extra={"extra_data": {
            "endpoint": "code",
            "language": static["language"],
            "pattern": static["pattern"],
            "functions": len(static["functions"]),
            "classes": len(static["classes"]),
            "imports": len(static["imports"]),
        }})

        truncated_code = _truncate_code(code)
        if len(truncated_code) != len(code):
            logger.info(f"Code input truncated from {len(code)} to {len(truncated_code)} chars")

        prompt = CODE_PROMPT.format(
            language=static["language"],
            pattern=static["pattern"],
            functions=", ".join(static["functions"][:6]) or "(none)",
            classes=", ".join(static["classes"][:6]) or "(none)",
            imports=", ".join(static["imports"][:6]) or "(none)",
            code=truncated_code,
        )

        llm_started = time.monotonic()
        parsed = await _run_code_llm_enhancement(code=code, static=static, prompt=prompt, mode=mode)
        llm_ms = round((time.monotonic() - llm_started) * 1000, 2)
        total_ms = round((time.monotonic() - started_total) * 1000, 2)

        is_fallback = str(parsed.get("summary_blocks", {}).get("why", "")).startswith("[MEDIUM confidence]")
        logger.info("Code analysis complete", extra={"extra_data": {
            "endpoint": "code",
            "mode": mode,
            "llm_time_ms": llm_ms,
            "total_time_ms": total_ms,
            "fallback": is_fallback,
            "context_size": len(prompt),
        }})

        result = {
            "project_goal": parsed.get("project_goal", ""),
            "architecture_style": parsed.get("architecture_style", ""),
            "key_modules": parsed.get("key_modules", []),
            "core_features": parsed.get("core_features", []),
            "risks": parsed.get("risks", []),
            "summary_blocks": {
                "what": parsed.get("summary_blocks", {}).get("what", ""),
                "why": parsed.get("summary_blocks", {}).get("why", ""),
                "remaining": parsed.get("summary_blocks", {}).get("remaining", []),
                "issues": parsed.get("summary_blocks", {}).get("issues", []),
            },
        }

        normalized = normalize_result(result)
        return validate_analysis_output(normalized, TaskType.PROJECT_ANALYSIS)
