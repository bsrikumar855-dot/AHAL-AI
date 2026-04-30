"""
Strict LLM handler.

Returns only real LLM outputs. If the model fails, the caller receives an
exception and must stop the analysis pipeline.
"""

from __future__ import annotations

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

_VALID_LLM_MODES = {"offline", "online", "smart"}
_CHAT_CONCURRENCY_LIMIT = 3
_CHAT_RETRY_ATTEMPTS = 1
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
_MIN_TIMEOUT_SECONDS = 3.0
_MAX_TIMEOUT_SECONDS = 90.0
_SYNC_RETRY_ATTEMPTS = 1
LLM_TIMEOUT_BACKGROUND = "LLM_TIMEOUT_BACKGROUND"

_JSON_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are a strict code analysis engine.\n"
    "You MUST return valid JSON.\n"
    "If data is missing, infer ONLY from visible code.\n"
    "NEVER return empty response.\n\n"
    "Rules:\n"
    "- Output JSON ONLY\n"
    "- No explanations, no markdown, no text outside JSON\n"
    "- No duplicate outputs and no multiple JSON objects\n"
    "- No hallucination - use ONLY provided input\n"
    "- Keep answers SHORT and PRECISE\n"
)


class LLMBackgroundTimeoutError(Exception):
    """Raised when the LLM call exceeds the safe async wait budget but may still complete elsewhere."""


def _clean_raw_llm_text(raw: str) -> str:
    cleaned = _JSON_FENCE_RE.sub("", str(raw or "")).replace("```", "").strip()
    cleaned = cleaned.replace("\ufeff", "").strip()
    return cleaned


def _extract_json_candidates(raw: str) -> list[str]:
    cleaned = _clean_raw_llm_text(raw)
    if not cleaned:
        return []

    candidates: list[str] = []
    brace_count = 0
    start_index: int | None = None
    for index, char in enumerate(cleaned):
        if char == "{":
            if brace_count == 0:
                start_index = index
            brace_count += 1
        elif char == "}":
            if brace_count == 0:
                continue
            brace_count -= 1
            if brace_count == 0 and start_index is not None:
                candidates.append(cleaned[start_index:index + 1].strip())
                start_index = None

    if candidates:
        return candidates

    start = cleaned.find("{")
    if start == -1:
        return []

    return [cleaned[start:].strip()]


def _extract_json_candidate(raw: str) -> str | None:
    candidates = _extract_json_candidates(raw)
    return candidates[-1] if candidates else None


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
    cleaned = _clean_raw_llm_text(raw)

    candidates = _extract_json_candidates(cleaned)
    if not candidates:
        logger.error("LLM parsing failed: no JSON candidate found")
        raise ValueError("INVALID_FINAL_RESULT")

    parse_errors: list[str] = []
    for candidate in reversed(candidates):
        attempted_candidates = [candidate]
        repaired = _repair_json(candidate)
        if repaired != candidate:
            attempted_candidates.append(repaired)

        for current in attempted_candidates:
            try:
                parsed = json.loads(current)
                if not isinstance(parsed, dict):
                    parse_errors.append("Parsed JSON was not an object")
                    continue
                return parsed
            except json.JSONDecodeError as exc:
                parse_errors.append(str(exc))

    logger.error(
        "LLM parsing failed",
        extra={"extra_data": {"errors": parse_errors, "candidate_preview": candidates[-1][:500]}},
    )
    raise ValueError("INVALID_FINAL_RESULT")


def parse_llm_json(text: str) -> dict[str, Any]:
    return _parse_json_response(text)


def _looks_like_timeout_error(error: Exception | str | None) -> bool:
    message = str(error or "").lower()
    return "timed out" in message or LLM_TIMEOUT_BACKGROUND.lower() in message


def get_llm_metrics() -> dict[str, Any]:
    latencies = list(_LLM_METRICS["llm_latency_ms"][-50:])
    average_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    return {
        "llm_requests_total": int(_LLM_METRICS["llm_requests_total"]),
        "llm_errors_total": int(_LLM_METRICS["llm_errors_total"]),
        "llm_latency_avg_ms": average_latency,
    }


def _build_prompt(user_prompt: str, max_chars: int = 8000) -> str:
    truncated = user_prompt.strip()
    budget = max_chars - len(SYSTEM_PROMPT)
    if len(truncated) > budget:
        truncated = truncated[:budget]
    return SYSTEM_PROMPT + truncated


def _normalize_mode(mode: str | None) -> str:
    settings = get_settings()

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


def _normalize_timeout(timeout: int | float | None, default_timeout: int | float) -> float:
    candidate = float(timeout or default_timeout)
    return max(_MIN_TIMEOUT_SECONDS, min(candidate, _MAX_TIMEOUT_SECONDS))


def generate_response(prompt: str, mode: str = "offline", timeout: int | float | None = None) -> str:
    settings = get_settings()
    selected_mode = _normalize_mode(mode)
    request_timeout = _normalize_timeout(timeout, settings.LLM_TIMEOUT_SECONDS)
    started = time.monotonic()
    _LLM_METRICS["llm_requests_total"] += 1

    if (
        selected_mode in {"online", "smart"}
        and _LLM_CIRCUIT_BREAKER["opened_until"] > time.monotonic()
    ):
        cooldown_remaining = round(_LLM_CIRCUIT_BREAKER["opened_until"] - time.monotonic(), 2)
        raise Exception(f"LLM circuit breaker open for {cooldown_remaining}s")

    if selected_mode == "online" or settings.ONLINE_ONLY:
        provider = GeminiProvider()
        result = provider.generate(prompt, timeout=request_timeout)
    elif selected_mode == "smart":
        provider = GeminiProvider()
        result = provider.generate(prompt, timeout=request_timeout)
        if not result:
            raise Exception("LLM returned empty response")
    else:
        result = OllamaProvider().generate(prompt, timeout=request_timeout)

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)

    if not result or not str(result).strip():
        _LLM_METRICS["llm_errors_total"] += 1
        _LLM_CIRCUIT_BREAKER["consecutive_failures"] += 1
        if _LLM_CIRCUIT_BREAKER["consecutive_failures"] >= _LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            _LLM_CIRCUIT_BREAKER["opened_until"] = time.monotonic() + _LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS
        raise Exception(
            f"LLM returned empty response (mode={selected_mode}, elapsed={elapsed_ms}ms)"
        )

    _LLM_CIRCUIT_BREAKER["consecutive_failures"] = 0
    _LLM_CIRCUIT_BREAKER["opened_until"] = 0.0
    _LLM_METRICS["llm_latency_ms"].append(elapsed_ms)
    if len(_LLM_METRICS["llm_latency_ms"]) > 200:
        _LLM_METRICS["llm_latency_ms"] = _LLM_METRICS["llm_latency_ms"][-200:]

    return str(result)


def generate_chat_response(prompt: str, mode: str = "online", timeout: int | float | None = None) -> str:
    started = time.monotonic()
    response = generate_response(prompt, mode=mode, timeout=timeout)
    cleaned = str(response or "").strip()
    if not cleaned:
        raise Exception("LLM returned empty response")

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
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
    effective_timeout = _normalize_timeout(timeout, settings.LLM_TIMEOUT_SECONDS)
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
                logger.info(
                    "Chat LLM attempt succeeded",
                    extra={"extra_data": {
                        "attempt": attempt,
                        "mode": _normalize_mode(mode),
                        "latency_ms": latency_ms,
                    }},
                )
                return response
            except Exception as exc:
                last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
                latency_ms = round((time.monotonic() - attempt_started) * 1000, 2)
                logger.error(
                    "Chat LLM attempt failed",
                    extra={"extra_data": {
                        "attempt": attempt,
                        "mode": _normalize_mode(mode),
                        "latency_ms": latency_ms,
                        "error": str(last_error),
                    }},
                )
                if attempt < _CHAT_RETRY_ATTEMPTS:
                    wait_time = (_CHAT_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))) + random.uniform(0.0, 1.0)
                    await asyncio.sleep(wait_time)

    raise Exception(
        f"LLM failed after {_CHAT_RETRY_ATTEMPTS} attempt(s): mode={_normalize_mode(mode)}, "
        f"latency_ms={round((time.monotonic() - overall_started) * 1000, 2)}, error={last_error}"
    )


def call_llm_with_retry(
    prompt: str,
    *,
    timeout: int | None = None,
    simplified_prompt: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    selected_mode = _normalize_mode(mode)
    effective_prompt = simplified_prompt or _build_prompt(prompt)
    request_timeout = int(_normalize_timeout(timeout, settings.LLM_TIMEOUT_SECONDS))
    started = time.monotonic()
    last_error: Exception | None = None

    max_attempts = max(1, int(settings.LLM_MAX_RETRIES or _SYNC_RETRY_ATTEMPTS))
    for attempt in range(max_attempts):
        try:
            logger.info(
                "LLM start",
                extra={"extra_data": {"attempt": attempt + 1, "mode": selected_mode}},
            )
            raw = generate_response(effective_prompt, mode=selected_mode, timeout=request_timeout)
            if not raw or not str(raw).strip():
                raise Exception("LLM returned empty response")

            try:
                parsed = _parse_json_response(raw)
            except Exception:
                raise Exception("INVALID_FINAL_RESULT")
            parsed["_llm_attempts"] = attempt + 1
            parsed["_llm_mode"] = selected_mode
            parsed["_llm_response_time_ms"] = round((time.monotonic() - started) * 1000, 2)
            logger.info(
                "LLM success",
                extra={"extra_data": {"attempt": attempt + 1, "mode": selected_mode}},
            )
            return parsed
        except Exception as error:
            last_error = error if isinstance(error, Exception) else Exception(str(error))
            logger.error(
                "LLM attempt failed",
                extra={"extra_data": {
                    "attempt": attempt + 1,
                    "mode": selected_mode,
                    "error": str(last_error),
                }},
            )
            if attempt < max_attempts - 1:
                backoff_seconds = _CHAT_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                time.sleep(backoff_seconds)

    if _looks_like_timeout_error(last_error):
        raise LLMBackgroundTimeoutError(LLM_TIMEOUT_BACKGROUND)
    raise Exception(f"LLM failed after {max_attempts} attempt(s): {last_error}")


def call_llm(
    prompt: str,
    timeout: int | None = None,
    fallback_context: str | None = None,
    simplified_prompt: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    _ = fallback_context
    return call_llm_with_retry(
        prompt,
        timeout=timeout,
        simplified_prompt=simplified_prompt,
        mode=mode,
    )


async def call_llm_async(
    prompt: str,
    timeout: int | None = None,
    fallback_context: str | None = None,
    simplified_prompt: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    _ = fallback_context
    settings = get_settings()
    effective_timeout = _normalize_timeout(timeout, settings.LLM_TIMEOUT_SECONDS)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                call_llm_with_retry,
                prompt,
                timeout=int(effective_timeout),
                simplified_prompt=simplified_prompt,
                mode=mode,
            ),
            timeout=effective_timeout + 5.0,
        )
    except asyncio.TimeoutError as exc:
        raise LLMBackgroundTimeoutError(LLM_TIMEOUT_BACKGROUND) from exc
