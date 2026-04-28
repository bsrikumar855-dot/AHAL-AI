"""
LLM handler — production-grade request routing, parsing, retry, and validation.

Responsibilities:
- Route to Gemini (online) or Ollama (offline) based on mode
- Enforce strict JSON output parsing with repair
- Retry once on parse failure with tighter prompt
- Smart static-extraction fallback when LLM is unavailable
- Structured logging for every call
"""

import asyncio
import json
import random
import re
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.llm.providers import GeminiProvider, OllamaProvider

logger = get_logger("services.llm_handler")

_MAX_REQUEST_TIMEOUT_SECONDS = 90
_VALID_LLM_MODES = {"offline", "online", "smart"}
_CHAT_CONCURRENCY_LIMIT = 3
_CHAT_RETRY_ATTEMPTS = 3
_CHAT_RETRY_BASE_DELAY_SECONDS = 1.0
_CHAT_LLM_SEMAPHORE = asyncio.Semaphore(_CHAT_CONCURRENCY_LIMIT)
_LLM_CIRCUIT_BREAKER = {
    "consecutive_failures": 0,
    "opened_until": 0.0,
}
_LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 4
_LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 45.0
_LLM_METRICS = {
    "llm_requests_total": 0,
    "llm_errors_total": 0,
    "llm_latency_ms": [],
}

# ── Regex patterns for static extraction ─────────────────────────
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")
_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import\s+([A-Za-z0-9_,\s\*]+)|import\s+([A-Za-z0-9_\.,\s]+))",
    re.MULTILINE,
)
_FILE_HEADER_RE = re.compile(r"===\s+FILE:\s+([^\n=]+?)\s+===")

# ── System prompt (unified across all endpoints) ─────────────────
SYSTEM_PROMPT = (
    "You are a strict code analysis engine.\n"
    "You MUST return valid JSON.\n"
    "If data is missing, infer ONLY from visible code.\n"
    "NEVER return empty response.\n\n"
    "Rules:\n"
    "- Output JSON ONLY\n"
    "- No explanations, no markdown, no text outside JSON\n"
    "- No hallucination — use ONLY provided input\n"
    "- Keep answers SHORT and PRECISE\n"
    "- NEVER return empty arrays — generate at least 2 items per list\n"
    "- If data is limited, still extract best possible structure\n\n"
)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


# ── JSON extraction and repair ───────────────────────────────────

def _extract_json_candidate(raw: str) -> str | None:
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
    if not cleaned:
        return None

    direct_match = _JSON_BLOCK_RE.search(cleaned)
    if direct_match:
        return direct_match.group(0).strip()

    start = cleaned.find("{")
    if start == -1:
        return None

    brace_count = 0
    end = None
    for index, char in enumerate(cleaned[start:], start=start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index + 1
                break

    if end is not None:
        return cleaned[start:end].strip()

    return cleaned[start:].strip()


def _repair_json(candidate: str) -> str:
    repaired = candidate.strip()
    open_count = repaired.count("{")
    close_count = repaired.count("}")
    if open_count > close_count:
        repaired += "}" * (open_count - close_count)
    elif close_count > open_count:
        repaired = "{" * (close_count - open_count) + repaired
    return repaired


def _parse_json_response(raw: str) -> dict[str, Any]:
    candidate = _extract_json_candidate(raw)
    if not candidate:
        raise ValueError("No JSON object found in response")

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_repair_json(candidate))

    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON is not an object")

    return parsed


def parse_llm_json(text: str) -> dict[str, Any]:
    """Public structured parser used by the staged analysis pipeline."""
    return _parse_json_response(text)


def get_llm_metrics() -> dict[str, Any]:
    latencies = list(_LLM_METRICS["llm_latency_ms"][-50:])
    average_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    return {
        "llm_requests_total": int(_LLM_METRICS["llm_requests_total"]),
        "llm_errors_total": int(_LLM_METRICS["llm_errors_total"]),
        "llm_latency_avg_ms": average_latency,
    }


# ── Static extraction (smart fallback) ───────────────────────────

def _extract_imports(text: str) -> list[str]:
    imports: list[str] = []
    for module_name, from_names, import_names in _IMPORT_RE.findall(text):
        if module_name:
            imports.append(module_name.strip())
            imports.extend(
                item.strip()
                for item in from_names.split(",")
                if item.strip() and item.strip() != "*"
            )
        elif import_names:
            imports.extend(
                item.strip()
                for item in import_names.split(",")
                if item.strip()
            )
    return _dedupe(imports)


def static_fallback_from_context(context: str, fallback_reason: str = "unknown") -> dict[str, Any]:
    """
    Build a structured result from static regex extraction.
    Used when LLM is completely unavailable.
    """
    functions = _dedupe(_FUNCTION_RE.findall(context))[:8]
    classes = _dedupe(_CLASS_RE.findall(context))[:8]
    imports = _extract_imports(context)[:8]
    files = _dedupe(_FILE_HEADER_RE.findall(context))[:8]

    print(f"[FALLBACK] reason={fallback_reason}, functions={len(functions)}, classes={len(classes)}, files={len(files)}")

    key_modules = files or (functions[:3] + classes[:3]) or ["(no modules detected)"]
    core_features = []
    if functions:
        core_features.append(f"Defines functions: {', '.join(functions[:4])}")
    if classes:
        core_features.append(f"Defines classes: {', '.join(classes[:4])}")
    if imports:
        core_features.append(f"Uses libraries: {', '.join(imports[:4])}")
    if not core_features:
        core_features = ["Static structure analysis", "Detected modules and functions"]

    # Detect framework
    context_lower = context.lower()
    arch = "Code repository"
    if "fastapi" in context_lower:
        arch = "FastAPI backend"
    elif "flask" in context_lower:
        arch = "Flask backend"
    elif "express" in context_lower:
        arch = "Express.js backend"
    elif "react" in context_lower or "jsx" in context_lower:
        arch = "React frontend"
    elif "django" in context_lower:
        arch = "Django backend"

    return {
        "project_goal": "Partial analysis completed from structural and static code signals.",
        "architecture_style": arch,
        "key_modules": key_modules,
        "core_features": core_features,
        "risks": [
            "Some semantic reasoning is inferred from structure and imports",
            "A deeper AI pass would improve runtime-specific coverage",
        ],
        "summary_blocks": {
            "what": f"Detected {len(functions)} functions, {len(classes)} classes across {len(files)} files",
            "why": "Using inferred insights from structural extraction, imports, and symbol detection.",
            "remaining": ["Continue semantic refinement in the background", "Inspect more files for wider execution coverage"],
            "issues": ["Some runtime behavior is inferred from static relationships"],
        },
        "_static_fallback": True,
    }

    return {
        "project_goal": "Static analysis — LLM response unavailable",
        "architecture_style": arch,
        "key_modules": key_modules,
        "core_features": core_features,
        "risks": ["LLM response unavailable — analysis is from static parsing only"],
        "summary_blocks": {
            "what": f"Detected {len(functions)} functions, {len(classes)} classes across {len(files)} files",
            "why": "Provide structural analysis as fallback when LLM is unavailable",
            "remaining": ["Run full analysis when LLM is available"],
            "issues": ["Limited semantic analysis — static extraction only"],
        },
        "_static_fallback": True,
    }


# ── Prompt construction ──────────────────────────────────────────

def _build_prompt(user_prompt: str, max_chars: int = 8000) -> str:
    """Prepend system prompt and cap total length."""
    truncated = user_prompt.strip()
    budget = max_chars - len(SYSTEM_PROMPT)
    if len(truncated) > budget:
        truncated = truncated[:budget]
    return SYSTEM_PROMPT + truncated


def _normalize_mode(mode: str | None) -> str:
    settings = get_settings()

    # ONLINE_ONLY overrides everything
    if settings.ONLINE_ONLY:
        return "online"

    candidate = str(mode or settings.LLM_MODE or "offline").strip().lower()
    if candidate not in _VALID_LLM_MODES:
        logger.warning(
            "Invalid LLM mode provided, defaulting to offline",
            extra={"extra_data": {"mode": candidate}},
        )
        return "offline"
    return candidate


# ── Core LLM call ────────────────────────────────────────────────

def generate_response(prompt: str, mode: str = "offline", timeout: int | float | None = None) -> str:
    """Generate a raw text response from the LLM. Raises on failure — never returns empty."""
    settings = get_settings()
    selected_mode = _normalize_mode(mode)
    request_timeout = max(10.0, min(float(timeout or settings.LLM_TIMEOUT_SECONDS), 90.0))
    started = time.monotonic()
    _LLM_METRICS["llm_requests_total"] += 1
    if (
        selected_mode in {"online", "smart"}
        and _LLM_CIRCUIT_BREAKER["opened_until"] > time.monotonic()
    ):
        cooldown_remaining = round(_LLM_CIRCUIT_BREAKER["opened_until"] - time.monotonic(), 2)
        raise Exception(f"LLM circuit breaker open for {cooldown_remaining}s")

    if selected_mode == "online" or settings.ONLINE_ONLY:
        logger.info(
            "ONLINE MODE — using Gemini only",
            extra={"extra_data": {"mode": "online", "online_only": settings.ONLINE_ONLY}},
        )
        provider = GeminiProvider()
        result = provider.generate(prompt, timeout=request_timeout)

    elif selected_mode == "smart":
        provider = GeminiProvider()
        result = provider.generate(prompt, timeout=request_timeout)
        if not result:
            logger.info("Smart mode fallback → Ollama")
            result = OllamaProvider().generate(prompt, timeout=request_timeout)
    else:
        result = OllamaProvider().generate(prompt, timeout=request_timeout)

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)

    if not result:
        _LLM_METRICS["llm_errors_total"] += 1
        _LLM_CIRCUIT_BREAKER["consecutive_failures"] += 1
        if _LLM_CIRCUIT_BREAKER["consecutive_failures"] >= _LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            _LLM_CIRCUIT_BREAKER["opened_until"] = time.monotonic() + _LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS
        raise Exception(
            f"LLM FAILED: Empty response from provider "
            f"(mode={selected_mode}, online_only={settings.ONLINE_ONLY}, elapsed={elapsed_ms}ms)"
        )
    _LLM_CIRCUIT_BREAKER["consecutive_failures"] = 0
    _LLM_CIRCUIT_BREAKER["opened_until"] = 0.0
    _LLM_METRICS["llm_latency_ms"].append(elapsed_ms)
    if len(_LLM_METRICS["llm_latency_ms"]) > 200:
        _LLM_METRICS["llm_latency_ms"] = _LLM_METRICS["llm_latency_ms"][-200:]

    logger.info(
        "LLM raw generation completed",
        extra={"extra_data": {"mode": selected_mode, "response_time_ms": elapsed_ms, "success": True}},
    )
    return result


def generate_chat_response(prompt: str, mode: str = "online", timeout: int | float | None = None) -> str:
    """
    Generate a raw-text chat response.

    This path intentionally avoids JSON parsing and fallback synthesis.
    It must either return non-empty model text or raise a concrete error.
    """
    started = time.monotonic()
    print(f"[CHAT LLM] PROMPT: {prompt[:500]}")
    response = generate_response(prompt, mode=mode, timeout=timeout)
    cleaned = str(response or "").strip()

    if not cleaned:
        raise ValueError("Empty LLM response")

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    print(f"[CHAT LLM] RESPONSE: {cleaned[:1000]}")
    logger.info(
        "LLM chat response generated",
        extra={"extra_data": {
            "mode": _normalize_mode(mode),
            "response_time_ms": elapsed_ms,
            "response_length": len(cleaned),
        }},
    )
    return cleaned


async def generate_chat_response_async(
    prompt: str,
    mode: str = "online",
    timeout: int | float | None = None,
) -> str:
    settings = get_settings()
    requested_timeout = float(timeout or settings.LLM_TIMEOUT_SECONDS)
    effective_timeout = max(20.0, min(requested_timeout, 90.0))
    last_error: Exception | None = None
    overall_started = time.monotonic()

    async with _CHAT_LLM_SEMAPHORE:
        for attempt in range(1, _CHAT_RETRY_ATTEMPTS + 1):
            attempt_started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(generate_chat_response, prompt, mode, effective_timeout),
                    timeout=effective_timeout + 5.0,
                )
                latency_ms = round((time.monotonic() - attempt_started) * 1000, 2)
                print(f"[CHAT LLM] Attempt {attempt} latency: {latency_ms}ms")
                return response
            except Exception as exc:
                last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
                latency_ms = round((time.monotonic() - attempt_started) * 1000, 2)
                logger.warning(
                    "Chat LLM attempt failed",
                    extra={"extra_data": {
                        "attempt": attempt,
                        "mode": _normalize_mode(mode),
                        "latency_ms": latency_ms,
                        "error": str(last_error),
                    }},
                )
                print(f"[CHAT LLM] Attempt {attempt} failed after {latency_ms}ms: {last_error}")
                if attempt < _CHAT_RETRY_ATTEMPTS:
                    wait_time = (_CHAT_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))) + random.uniform(0.0, 1.0)
                    await asyncio.sleep(wait_time)

    total_ms = round((time.monotonic() - overall_started) * 1000, 2)
    raise Exception(
        f"Chat generation unavailable after {_CHAT_RETRY_ATTEMPTS} attempts "
        f"(mode={_normalize_mode(mode)}, latency_ms={total_ms}, error={last_error})"
    )


# ── Structured call with retry + fallback ────────────────────────

def call_llm(
    prompt: str,
    timeout: int | None = None,
    fallback_context: str | None = None,
    simplified_prompt: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Call the LLM and parse a structured JSON response.

    Strategy:
    1. Call LLM with system prompt prepended
    2. Parse JSON from response
    3. On parse failure → retry once with stricter prompt
    4. On total failure → static extraction fallback (if context provided)
    5. Otherwise → raise Exception
    """
    settings = get_settings()
    overall_timeout = max(10, int(timeout or settings.LLM_TIMEOUT_SECONDS))
    deadline = time.monotonic() + overall_timeout
    selected_mode = _normalize_mode(mode)

    # Build the effective prompt
    effective_prompt = simplified_prompt or _build_prompt(prompt)

    # ── Attempt 1 ────────────────────────────────────────────────
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Exception(f"LLM FAILED: timeout before starting (budget={overall_timeout}s)")

    request_timeout = max(10.0, min(float(remaining), 60.0))
    started = time.monotonic()
    attempt = 0
    last_error = None
    max_attempts = 3  # 2 retries

    print(f"[LLM] Starting call: mode={selected_mode}, timeout={overall_timeout}s, context_size={len(effective_prompt)}")

    for attempt in range(1, max_attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 5:
            print(f"[LLM] Not enough time for attempt {attempt} (remaining={remaining:.1f}s)")
            break

        try:
            raw = generate_response(effective_prompt, mode=selected_mode, timeout=min(remaining, 60.0))
            print(f"[LLM] Attempt {attempt}: response_length={len(raw)}")

            parsed = _parse_json_response(raw)
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)

            parsed["_llm_attempts"] = attempt
            parsed["_llm_mode"] = selected_mode
            parsed["_llm_response_time_ms"] = elapsed_ms

            logger.info(
                "LLM structured response parsed",
                extra={"extra_data": {
                    "attempt": attempt,
                    "mode": selected_mode,
                    "response_time_ms": elapsed_ms,
                    "response_length": len(raw),
                    "fallback": False,
                }},
            )
            return parsed

        except ValueError as parse_err:
            last_error = parse_err
            print(f"[LLM] Attempt {attempt} JSON parse failed: {parse_err}")
            logger.warning(
                f"LLM JSON parse failed (attempt {attempt}): {parse_err}",
                extra={"extra_data": {"attempt": attempt}},
            )
            # On retry, prepend stricter instruction
            effective_prompt = (
                "CRITICAL: Your previous response was not valid JSON. "
                "You MUST return ONLY a raw JSON object. "
                "No markdown, no explanation, no text outside the JSON. "
                "NEVER return empty response.\n\n"
                + effective_prompt
            )
            continue

        except Exception as gen_err:
            last_error = gen_err
            _LLM_METRICS["llm_errors_total"] += 1
            print(f"[LLM] Attempt {attempt} generation failed: {gen_err}")
            logger.error(f"LLM generation failed (attempt {attempt}): {gen_err}")
            # Retry generation failures too (API timeout, etc.)
            continue

    # ── Fallback: static extraction ──────────────────────────────
    if fallback_context:
        fallback_reason = str(last_error)
        print(f"[LLM] All {attempt} attempts failed, using static fallback. Reason: {fallback_reason}")
        logger.warning(
            f"LLM failed after {attempt} attempt(s), using static fallback",
            extra={"extra_data": {"last_error": fallback_reason, "attempts": attempt}},
        )
        return static_fallback_from_context(fallback_context, fallback_reason=fallback_reason)

    raise Exception(f"LLM FAILED after {attempt} attempt(s): {last_error}")


async def call_llm_async(
    prompt: str,
    timeout: int | None = None,
    fallback_context: str | None = None,
    simplified_prompt: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(call_llm, prompt, timeout, fallback_context, simplified_prompt, mode)
