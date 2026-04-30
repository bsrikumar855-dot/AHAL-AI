from __future__ import annotations

import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

import requests

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("services.llm.providers")

_PROVIDER_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_DEFAULT_GEMINI_MODEL = "gemma-4-26b-a4b-it"
_GEMINI_MIN_TIMEOUT_SECONDS = 5.0
_GEMINI_MAX_TIMEOUT_SECONDS = 90.0


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, timeout: int | float | None = None) -> str | None:
        """Return raw text on success, otherwise None."""


class OllamaProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.url = self.settings.OLLAMA_URL
        self.model = self.settings.OLLAMA_MODEL

    def generate(self, prompt: str, timeout: int | float | None = None) -> str | None:
        request_timeout = max(1.0, float(timeout or self.settings.LLM_TIMEOUT_SECONDS))
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.settings.OLLAMA_TEMPERATURE,
                "num_predict": self.settings.LLM_MAX_RESPONSE_TOKENS,
            },
        }

        try:
            started = time.monotonic()
            response = requests.post(self.url, json=payload, timeout=request_timeout)
            response.raise_for_status()
            raw = str(response.json().get("response", "")).strip()
            if not raw:
                logger.warning("Ollama returned an empty response")
                return None
            logger.info(
                "Ollama generation succeeded",
                extra={"extra_data": {
                    "provider": "ollama",
                    "response_time_ms": round((time.monotonic() - started) * 1000, 2),
                    "model": self.model,
                }},
            )
            return raw
        except Exception as exc:
            logger.warning(
                "Ollama generation failed",
                extra={"extra_data": {
                    "provider": "ollama",
                    "error": str(exc),
                    "model": self.model,
                }},
            )
            return None


class GeminiProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key = str(self.settings.GEMINI_API_KEY or "").strip()
        self.model = _DEFAULT_GEMINI_MODEL
        self.timeout_seconds = _GEMINI_MAX_TIMEOUT_SECONDS

    def _is_api_key_valid(self) -> bool:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set — cannot call Gemini")
        if self.api_key.lower() == "your_key_here":
            raise ValueError("GEMINI_API_KEY is still set to placeholder 'your_key_here'")
        return True

    def generate(self, prompt: str, timeout: int | float | None = None) -> str | None:
        self._is_api_key_valid()

        effective_timeout = min(_GEMINI_MAX_TIMEOUT_SECONDS, max(_GEMINI_MIN_TIMEOUT_SECONDS, float(timeout or self.timeout_seconds)))
        started = time.monotonic()

        def _call_genai() -> Any:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            logger.info(
                "Gemini initialized",
                extra={"extra_data": {"provider": "gemini", "prompt_length": len(prompt)}},
            )

            try:
                response = client.models.generate_content(
                    model="gemma-4-26b-a4b-it",
                    contents=prompt,
                    config={"temperature": 0, "max_output_tokens": self.settings.LLM_MAX_RESPONSE_TOKENS},
                )
            except Exception as exc:
                raise Exception(f"Gemini API call failed: {str(exc)}") from exc

            text = ""
            try:
                candidates = getattr(response, "candidates", None) or []
                if candidates:
                    first_candidate = candidates[0]
                    content = getattr(first_candidate, "content", None)
                    parts = getattr(content, "parts", None) or []
                    if parts:
                        text = str(getattr(parts[0], "text", "") or "").strip()
            except Exception as exc:
                logger.warning(
                    "Gemini structured text extraction failed",
                    extra={"extra_data": {"provider": "gemini", "error": str(exc)}},
                )

            if not text:
                text = str(getattr(response, "text", "") or "").strip()

            if not text or not text.strip():
                raise Exception("Gemini returned empty response")

            return text.strip()

        future = _PROVIDER_EXECUTOR.submit(_call_genai)
        try:
            text = future.result(timeout=effective_timeout)
            logger.info(
                "Gemini generation succeeded",
                extra={"extra_data": {
                    "provider": "gemini",
                    "response_time_ms": round((time.monotonic() - started) * 1000, 2),
                    "model": self.model,
                }},
            )
            return text
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"Gemini API failed: timed out after {effective_timeout:.1f}s") from exc
