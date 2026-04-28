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

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")

SYSTEM_PROMPT = (
    "You are a strict code analysis engine.\n"
    "You MUST return valid JSON.\n"
    "If data is missing, infer ONLY from visible code.\n"
    "NEVER return empty response.\n\n"
    "Rules:\n"
    "- Output JSON ONLY\n"
    "- No explanations, no markdown, no text outside JSON\n"
    "- No hallucination - use ONLY provided input\n"
    "- Keep answers SHORT and PRECISE\n"
)


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
    return _parse_json_response(text)


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


def generate_response(prompt: str, mode: str = "offline", timeout: int | float | None = None) -> str:
    settings = get_settings()
    selected_mode = _normalize_mode(mode)
    request_timeout = max(60.0, min(float(timeout or settings.LLM_TIMEOUT_SECONDS), 90.0))
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
    print(f"[CHAT LLM] PROMPT: {prompt[:500]}")
    response = generate_response(prompt, mode=mode, timeout=timeout)
    cleaned = str(response or "").strip()
    if not cleaned:
        raise Exception("LLM returned empty response")

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
    effective_timeout = max(60.0, min(requested_timeout, 90.0))
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
                print(f"[CHAT LLM] Attempt {attempt} failed after {latency_ms}ms: {last_error}")
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
        f"LLM failed after 3 attempts: mode={_normalize_mode(mode)}, "
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
    request_timeout = max(60, int(timeout or settings.LLM_TIMEOUT_SECONDS))
    started = time.monotonic()
    last_error: Exception | None = None

    print(f"[LLM] Starting call: mode={selected_mode}, timeout={request_timeout}s, context_size={len(effective_prompt)}")

    for attempt in range(3):
        try:
            raw = generate_response(effective_prompt, mode=selected_mode, timeout=request_timeout)
            if not raw or not str(raw).strip():
                raise Exception("LLM returned empty response")

            parsed = _parse_json_response(raw)
            parsed["_llm_attempts"] = attempt + 1
            parsed["_llm_mode"] = selected_mode
            parsed["_llm_response_time_ms"] = round((time.monotonic() - started) * 1000, 2)
            return parsed
        except Exception as error:
            last_error = error if isinstance(error, Exception) else Exception(str(error))
            print(f"LLM attempt {attempt + 1} failed:", last_error)
            logger.error(
                "LLM attempt failed",
                extra={"extra_data": {
                    "attempt": attempt + 1,
                    "mode": selected_mode,
                    "error": str(last_error),
                }},
            )

    print("LLM ERROR:", last_error)
    raise Exception(f"LLM failed after 3 attempts: {last_error}")


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
    return await asyncio.to_thread(
        call_llm_with_retry,
        prompt,
        timeout=timeout,
        simplified_prompt=simplified_prompt,
        mode=mode,
    )
