"""
Analysis service for repository intelligence extraction.

Wraps the LLM provider to extract Repo-level intent and File-level summaries.
"""

import json
import re
import os
from typing import Dict, Any

from app.core.config import get_settings
from app.services.llm.factory import get_llm_provider
from app.core.logging import get_logger

logger = get_logger("services.analysis")

def strict_context_module_filter(key_modules, file_paths):
    valid = set()

    for path in file_paths:
        fname = os.path.basename(path)
        valid.add(fname)
        valid.add(os.path.splitext(fname)[0])

    if not isinstance(key_modules, list):
        return []

    return list(set([m for m in key_modules if m in valid]))


def force_non_empty_repo_output(result: Dict[str, Any]) -> Dict[str, Any]:
    summary_blocks = result.setdefault("summary_blocks", {})

    if not result.get("core_features"):
        result["core_features"] = [
            "Code structure analysis",
            "Module interaction detection",
            "Project intent extraction"
        ]

    if not summary_blocks.get("issues"):
        summary_blocks["issues"] = [
            "No explicit issues detected, review recommended"
        ]

    if not summary_blocks.get("remaining"):
        summary_blocks["remaining"] = [
            "Further deep analysis can be performed"
        ]

    if not summary_blocks.get("what"):
        summary_blocks["what"] = "Basic project structure detected"

    if not summary_blocks.get("why"):
        summary_blocks["why"] = "Project structure and intent extraction from repository context"

    result["summary_blocks"] = summary_blocks
    return result

REPO_INTENT_PROMPT = """
DO NOT copy example text. Generate real values only from the input.

Analyze the provided code, project files, or repository context.
Extract accurate, concrete, and technically meaningful intelligence.

OBJECTIVE:
- project_goal → exact purpose of the system (1 precise sentence)
- architecture_style → real system type (e.g., FastAPI backend, CLI tool, microservices)
- tech_stack → actual languages, frameworks, and tools used
- key_modules → ONLY real file names found in the input (e.g., router.py, main.py, config.py). Extract from import statements, file path headers, or --- filename --- markers. Do NOT return generic names like "module", "component", or "service"
- core_features → actual implemented capabilities
- risks → real technical risks, security issues, or architectural problems

Also generate:
- what → high-level explanation of the system
- why → purpose or motivation
- remaining → missing or incomplete parts
- issues → concrete technical flaws

RULES:
- key_modules MUST be extracted ONLY from:
  - file names (e.g. main.py, auth_service.py)
  - import statements (import X, from X import Y)
  - class names
  - function names
- DO NOT invent names.
- If no real modules found → return empty list []
- DO NOT generate generic AI words like: 'summarizer', 'rag', 'query', 'engine', 'system', 'module' unless they literally exist in the code.
- core_features MUST NOT be empty.
- issues MUST NOT be empty.
- remaining MUST NOT be empty.
- Generate at least 3 items for each list.
- Prefer SPECIFIC details over generic statements
- If partial data, make a grounded technical inference
- NEVER output "string", "", null, or placeholder descriptions
- DO NOT repeat or copy schema text
- Every field must contain meaningful content

EXAMPLE:
Input:
--- app/main.py ---
from auth_service import login

Output:
{{
  "project_goal": "...",
  "architecture_style": "...",
  "tech_stack": [],
  "key_modules": ["main.py", "auth_service", "login"],
  "core_features": [],
  "risks": [],
  "summary_blocks": {{...}}
}}

INPUT:
{context}

OUTPUT FORMAT (STRICT JSON ONLY):

{{
  "project_goal": "",
  "architecture_style": "",
  "tech_stack": [],
  "key_modules": [],
  "core_features": [],
  "risks": [],
  "summary_blocks": {{
    "what": "",
    "why": "",
    "remaining": [],
    "issues": []
  }}
}}

Return ONLY valid JSON.
No explanation.
No markdown.
No extra text.
"""

FILE_SUMMARY_PROMPT = """
Analyze this file and return ONLY JSON.

NO explanations. NO markdown.

File: {file_path}

Content:
{content}

FORMAT:

{{
  "summary": "string",
  "module_role": "string"
}}

Return ONLY valid JSON.
No explanation.
No markdown.
No extra text.
"""

def parse_llm_response(response: str | dict) -> dict:
    if isinstance(response, dict):
        return response

    fallback = {
        "project_goal": "Failed to parse",
        "tech_stack": [],
        "core_features": []
    }

    try:
        raw_str = str(response)
        logger.debug(f"Raw LLM response (first 200 chars): {raw_str[:200]}")
        
        cleaned = re.sub(r"```json", "", raw_str, flags=re.IGNORECASE)
        cleaned = re.sub(r"```", "", cleaned).strip()

        start_idx = cleaned.find('{')
        if start_idx == -1:
            logger.warning("No unescaped '{' found in response.")
            return fallback

        brace_count = 0
        end_idx = -1

        for i in range(start_idx, len(cleaned)):
            if cleaned[i] == '{':
                brace_count += 1
            elif cleaned[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break

        if end_idx == -1:
            logger.warning("Unbalanced braces in JSON response.")
            return fallback

        json_str = cleaned[start_idx:end_idx + 1]

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                logger.debug("Successfully parsed JSON block with bracket balancing.")
                return parsed
            else:
                logger.warning("Extracted JSON is not a dictionary.")
        except json.JSONDecodeError as e:
            logger.warning(f"Bracket-extracted string failed JSON decoding: {e}")

        logger.warning("Failed to extract valid JSON dict.")
        return fallback

    except Exception as e:
        logger.error(f"Unexpected error in parse_llm_response: {e}")
        return fallback

class AnalysisService:
    def __init__(self):
        # We use the summarize model (7b) for intent/file extraction as it's deeper reasoning
        self.llm = get_llm_provider("summarize")
        self.settings = get_settings()

    async def extract_repo_intelligence(self, context: str, mode: str = "offline") -> Dict[str, Any]:
        """Extract root-level intent from concatenated key files."""
        logger.info(f"extract_repo_intelligence called with {len(context)} chars")
        if not context or len(context.strip()) < 50:
            return {
                "project_goal": "Insufficient data to analyze repository",
                "tech_stack": [],
                "core_features": [],
                "architecture_style": "Unknown",
                "key_modules": [],
                "risks": [],
                "summary_blocks": {"what": "", "why": "", "remaining": [], "issues": []},
            }

        from app.services.llm_handler import call_llm
        context_batches = self._build_context_batches(context)
        partial_results = [
            call_llm(
                REPO_INTENT_PROMPT.format(context=batch),
                timeout=self.settings.LLM_TIMEOUT_SECONDS,
                fallback_context=batch,
                mode=mode,
            )
            for batch in context_batches
        ]

        top_files = re.findall(r"--- (.+?) ---", context)
        merged = self._merge_repo_results(partial_results, top_files)
        return force_non_empty_repo_output(merged)

    def _build_context_batches(self, context: str) -> list[str]:
        file_blocks = [block.strip() for block in re.split(r"(?=---\s+.+?\s+---)", context) if block.strip()]
        chunk_size = self.settings.CHUNK_SIZE_CHARS
        batch_size = max(2, min(3, self.settings.CHUNK_BATCH_SIZE))
        chunks: list[str] = []

        for block in file_blocks:
            lines = block.splitlines(keepends=True)
            current = ""
            for line in lines:
                if len(current) + len(line) > chunk_size and current:
                    chunks.append(current.rstrip())
                    current = line
                else:
                    current += line
            if current.strip():
                chunks.append(current.rstrip())

        if not chunks:
            chunks = [context[:chunk_size]]

        if len(chunks) <= batch_size:
            return ["\n\n".join(chunks)]

        batches = [chunks[index:index + batch_size] for index in range(0, len(chunks), batch_size)]
        if len(batches) > 1 and len(batches[-1]) == 1:
            batches[-2].extend(batches[-1])
            batches.pop()

        return ["\n\n".join(batch) for batch in batches]

    def _merge_repo_results(self, partial_results: list[dict], top_files: list[str]) -> Dict[str, Any]:
        valid_results = [item for item in partial_results if isinstance(item, dict)]
        key_modules: list[str] = []
        tech_stack: list[str] = []
        core_features: list[str] = []
        risks: list[str] = []
        remaining: list[str] = []
        issues: list[str] = []

        for item in valid_results:
            key_modules.extend(item.get("key_modules", []))
            tech_stack.extend(item.get("tech_stack", []))
            core_features.extend(item.get("core_features", []))
            risks.extend(item.get("risks", []))
            blocks = item.get("summary_blocks", {}) if isinstance(item.get("summary_blocks", {}), dict) else {}
            remaining.extend(blocks.get("remaining", []))
            issues.extend(blocks.get("issues", []))

        filtered_modules = strict_context_module_filter(key_modules, top_files)
        if not filtered_modules:
            filtered_modules = top_files[:8]

        return {
            "project_goal": next((str(item.get("project_goal", "")).strip() for item in valid_results if len(str(item.get("project_goal", "")).strip()) > 5), "Backend system for analyzing uploaded code projects"),
            "tech_stack": list(dict.fromkeys(str(item).strip() for item in tech_stack if str(item).strip())),
            "core_features": list(dict.fromkeys(str(item).strip() for item in core_features if str(item).strip())),
            "architecture_style": next((str(item.get("architecture_style", "")).strip() for item in valid_results if len(str(item.get("architecture_style", "")).strip()) > 5), "Backend service"),
            "key_modules": filtered_modules,
            "risks": list(dict.fromkeys(str(item).strip() for item in risks if str(item).strip())),
            "summary_blocks": {
                "what": next((str((item.get("summary_blocks", {}) or {}).get("what", "")).strip() for item in valid_results if len(str((item.get("summary_blocks", {}) or {}).get("what", "")).strip()) > 5), "Repository structure analyzed from prioritized files"),
                "why": next((str((item.get("summary_blocks", {}) or {}).get("why", "")).strip() for item in valid_results if len(str((item.get("summary_blocks", {}) or {}).get("why", "")).strip()) > 5), "Project structure and intent extraction from repository context"),
                "remaining": list(dict.fromkeys(str(item).strip() for item in remaining if str(item).strip())),
                "issues": list(dict.fromkeys(str(item).strip() for item in issues if str(item).strip())),
            },
        }

    async def analyze_file(self, file_path: str, content: str, mode: str = "offline") -> Dict[str, Any]:
        """Extract file-level intelligence."""
        # Trim individual file content limits for context window
        trimmed_content = content[:8000]
        prompt = FILE_SUMMARY_PROMPT.format(file_path=file_path, content=trimmed_content)
        
        try:
            from app.services.llm_handler import call_llm
            parsed = call_llm(prompt, mode=mode)
            return {
                "summary": str(parsed.get("summary", "Summary unavailable")),
                "module_role": str(parsed.get("module_role", "Unknown Role"))
            }
        except Exception as e:
            logger.warning(f"Failed to extract file intelligence for {file_path}: {e}")
            return {
                "summary": "AI extraction failed.",
                "module_role": "Unknown"
            }
