import json
import re

from app.core.logging import get_logger

logger = get_logger("services.llm_wrapper")

class LLMWrapper:
    """Wrapper to handle LLM unreliability, retries, and strict JSON parsing."""
    def __init__(self, llm_callable):
        self.llm_callable = llm_callable

    async def generate(self, prompt: str) -> dict:
        fallback = {
             "project_goal": "LLM failed to generate structured output",
             "architecture_style": "unknown",
             "key_modules": [],
             "core_features": [],
             "risks": ["LLM parsing failure"],
             "summary_blocks": {
                 "what": "Analysis failed due to model limitations",
                 "why": "Model returned invalid or incomplete JSON",
                 "remaining": [],
                 "issues": ["error message"]
             }
         }

        for attempt in range(3):
            try:
                # Call the underlying LLM function
                response = await self.llm_callable(prompt)
                text = str(response)
                
                # Clean Markdown blocks
                text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
                text = re.sub(r"```", "", text)
                
                # Extract JSON bracket match
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return parsed
                logger.warning(
                    "LLMWrapper parsing failed",
                    extra={"extra_data": {"attempt": attempt + 1, "response_length": len(text)}},
                )
            except Exception as e:
                logger.warning(
                    "LLMWrapper attempt failed",
                    extra={"extra_data": {"attempt": attempt + 1, "error": str(e)}},
                )

        # All retries failed
        logger.warning("LLMWrapper returning fallback after exhausted attempts")
        return fallback
