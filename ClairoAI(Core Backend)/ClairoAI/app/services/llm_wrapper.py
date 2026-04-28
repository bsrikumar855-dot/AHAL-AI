import json
import re

class LLMWrapper:
    """Wrapper to handle LLM unreliability, retries, and strict JSON parsing."""
    def __init__(self, llm_callable):
        self.llm_callable = llm_callable

    async def generate(self, prompt: str) -> dict:
        fallback = {
             "project_goal": "LLM failed to generate structured output",
             "architecture_style": "Unknown",
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
                print(f"[LLMWrapper] RAW LLM response (attempt {attempt+1}):\n{text[:500]}")
                
                # Clean Markdown blocks
                text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
                text = re.sub(r"```", "", text)
                
                # Extract JSON bracket match
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return parsed
                print(f"[LLMWrapper] Attempt {attempt+1} failed: No valid JSON dictionary found in output")
            except Exception as e:
                print(f"[LLMWrapper] Attempt {attempt+1} failed with error: {e}")

        # All retries failed
        print("[LLMWrapper] All 3 retries failed. Returning safe fallback.")
        return fallback
