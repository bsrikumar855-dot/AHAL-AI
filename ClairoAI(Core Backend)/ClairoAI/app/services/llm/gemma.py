"""
Gemma LLM provider via Ollama HTTP API.

Uses gemma:7b for all tasks with deterministic (temperature=0) settings.
Handles prompt construction, JSON parsing of responses, timeouts, and retries.
"""

import json
import os
import re
from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.exceptions import LLMError
from app.services.llm.base import BaseLLMProvider

logger = get_logger("llm.gemma")

# ── Prompt Templates ─────────────────────────────────────────────

SUMMARIZE_PROMPT = """
Analyze the code changes and return ONLY JSON.

NO explanations. NO markdown.

INPUT:
{input_text}

FORMAT:

{{
  "what_done": {{"text": "string", "confidence": 0.0}},
  "why_done": {{"text": "string", "confidence": 0.0}},
  "what_remains": {{"text": "string", "confidence": 0.0}},
  "potential_issues": {{"text": "string", "confidence": 0.0}}
}}

Confidence: 0.0 = guessing, 1.0 = certain.

RETURN ONLY JSON:
"""

ANSWER_PROMPT = """
Answer the question using ONLY the context below.

NO explanations. NO markdown.

CONTEXT:
{context}

QUESTION:
{question}

FORMAT:

{{
  "answer": "string",
  "confidence": 0.0
}}

If context is insufficient, set answer to "Not enough information".

RETURN ONLY JSON:
"""


class GemmaProvider(BaseLLMProvider):
    """
    Ollama-based Gemma provider.

    Calls the Ollama /api/generate endpoint with the configured
    Gemma model. Parses structured JSON from the response.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.settings = get_settings()
        self.base_url = self.settings.OLLAMA_BASE_URL
        self.timeout = max(self.settings.LLM_TIMEOUT_SECONDS, 60)
        self.max_retries = self.settings.LLM_MAX_RETRIES

    async def _call_ollama(self, prompt: str) -> str:
        """
        Send a prompt to Ollama and return the generated text.
        Handles retries and timeout errors.
        """
        from app.core.config import get_settings
        settings = get_settings()
        model = "gemma:7b"
        logger.info(f"Using LLM model: {model}")

        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": settings.OLLAMA_TEMPERATURE,
                "num_predict": 2048,
            },
        }

        last_error = None
        for attempt in range(1 + self.max_retries):
            try:
                logger.info(
                    f"LLM call attempt {attempt + 1}",
                    extra={"extra_data": {"model": model, "url": url}},
                )
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()

                data = response.json()
                generated = data.get("response", "").strip()

                if not generated:
                    raise LLMError("LLM returned empty response")

                logger.info(
                    "LLM call succeeded",
                    extra={"extra_data": {
                        "model": model,
                        "response_length": len(generated),
                    }},
                )
                return generated


            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"LLM timeout (attempt {attempt + 1})")
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"LLM HTTP error: {e.response.status_code}")
            except Exception as e:
                last_error = e
                logger.warning(f"LLM call error: {e}")

        raise LLMError(f"LLM call failed after {1 + self.max_retries} attempts: {last_error}")

    def _parse_json_response(self, raw: str) -> dict:
        """
        Extract and parse JSON from the LLM response.
        Handles cases where the model wraps JSON in markdown fences.
        """
        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences if present
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find first { ... } block
        brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse LLM JSON response: {raw[:500]}")
        raise LLMError("LLM response could not be parsed as JSON")

    async def summarize(
        self,
        input_text: str,
        prompt_template: Optional[str] = None,
    ) -> dict:
        """Generate a structured summary from code input."""
        try:
            template = prompt_template or SUMMARIZE_PROMPT
            prompt = template.format(input_text=input_text)
            raw_response = await self._call_ollama(prompt)
            parsed = self._parse_json_response(raw_response)

            # Validate expected structure
            expected_keys = {"what_done", "why_done", "what_remains", "potential_issues"}
            for key in expected_keys:
                if key not in parsed:
                    parsed[key] = {"text": "Unable to determine", "confidence": 0.0}
                elif not isinstance(parsed[key], dict):
                    parsed[key] = {"text": str(parsed[key]), "confidence": 0.5}
                else:
                    if "text" not in parsed[key]:
                        parsed[key]["text"] = "Unable to determine"
                    if "confidence" not in parsed[key]:
                        parsed[key]["confidence"] = 0.5
                    # Clamp confidence to [0, 1]
                    parsed[key]["confidence"] = max(0.0, min(1.0, float(parsed[key]["confidence"])))

            return parsed
        except Exception as e:
            logger.warning(f"LLM summarize failed: {e}")
            return {
                "what_done": {"text": "LLM failed", "confidence": 0.0},
                "why_done": {"text": str(e), "confidence": 0.0},
                "what_remains": {"text": "Retry analysis", "confidence": 0.0},
                "potential_issues": {"text": "LLM error", "confidence": 0.0},
            }

    async def answer(self, context: str, question: str) -> dict:
        """Generate a grounded answer from context."""
        try:
            prompt = ANSWER_PROMPT.format(context=context, question=question)
            raw_response = await self._call_ollama(prompt)
            parsed = self._parse_json_response(raw_response)

            # Validate expected structure
            if "answer" not in parsed:
                parsed["answer"] = raw_response
            if "confidence" not in parsed:
                parsed["confidence"] = 0.5
            parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))

            return parsed
        except Exception as e:
            logger.warning(f"LLM answer failed: {e}")
            return {
                "answer": "LLM failed to generate answer",
                "confidence": 0.0,
            }

    async def generate_structured(self, prompt: str) -> dict:
        """Generate a generic structured JSON response based on explicit prompt instructions."""
        try:
            raw_response = await self._call_ollama(prompt)
            return self._parse_json_response(raw_response)
        except Exception as e:
            logger.warning(f"LLM structured generation failed: {e}")
            return {
                "project_goal": "LLM failed",
                "key_modules": [],
                "core_features": [],
                "risks": ["LLM failure"],
                "summary_blocks": {
                    "what": "Analysis failed",
                    "why": str(e),
                    "remaining": [],
                    "issues": ["LLM error"]
                }
            }

    async def health_check(self) -> bool:
        """Check Ollama connectivity by listing available models."""
        try:
            url = f"{self.base_url}/api/tags"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            return False

    def get_model_name(self) -> str:
        return self.model_name
