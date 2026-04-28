"""
Risk Analysis service for repository ingestion.

Scans individual file chunks to detect security, performance, and anti-pattern risks.
"""

from typing import List, Dict, Any

from app.services.llm.factory import get_llm_provider
from app.core.logging import get_logger

logger = get_logger("services.risk_analyzer")

RISK_ANALYSIS_PROMPT = """
Analyze the code and return ONLY JSON.

NO explanations. NO markdown.

FORMAT:

{{
  "security_issues": ["string"],
  "performance_issues": ["string"],
  "anti_patterns": ["string"]
}}

INPUT:
{code}

RETURN ONLY JSON:
"""

class RiskAnalyzer:
    def __init__(self):
        self.llm = get_llm_provider("summarize")

    async def analyze_risks(self, file_path: str, content: str) -> List[Dict[str, str]]:
        """Identify risks in a file."""
        trimmed_content = content[:8000]
        prompt = RISK_ANALYSIS_PROMPT.format(code=trimmed_content)
        
        try:
            from app.services.llm_wrapper import LLMWrapper
            wrapper = LLMWrapper(self.llm.generate_structured)
            parsed = await wrapper.generate(prompt)

            # New schema returns a dict with categorized arrays
            if isinstance(parsed, dict):
                risks = []
                for issue in parsed.get("security_issues", []):
                    if isinstance(issue, str) and issue:
                        risks.append({"type": "security", "description": issue})
                for issue in parsed.get("performance_issues", []):
                    if isinstance(issue, str) and issue:
                        risks.append({"type": "performance", "description": issue})
                for issue in parsed.get("anti_patterns", []):
                    if isinstance(issue, str) and issue:
                        risks.append({"type": "anti-pattern", "description": issue})
                return risks

            # Legacy fallback: list of {type, description} dicts
            elif isinstance(parsed, list):
                valid_risks = []
                for p in parsed:
                    if isinstance(p, dict) and "type" in p and "description" in p:
                        valid_risks.append({
                            "type": str(p["type"]),
                            "description": str(p["description"])
                        })
                return valid_risks

            else:
                logger.warning(f"Unexpected risk JSON format for {file_path}: {parsed}")
                return []
        except Exception as e:
            logger.warning(f"Failed to extract risks for {file_path}: {e}")
            return []

