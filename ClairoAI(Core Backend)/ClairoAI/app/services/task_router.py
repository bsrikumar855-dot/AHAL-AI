"""
Task Router — Strict prompt routing for the analysis pipeline.

Separates PROJECT_ANALYSIS from RAG_SUMMARY at the prompt level
to prevent output contamination between pipelines.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict

from app.core.logging import get_logger

logger = get_logger("task_router")


class TaskType(str, Enum):
    PROJECT_ANALYSIS = "PROJECT_ANALYSIS"
    RAG_SUMMARY = "RAG_SUMMARY"


# ── Project Analysis Prompt (STRICT) ────────────────────────────
# Used ONLY for code/folder/repo analysis.
# Output MUST be structured product intelligence — never RAG.

PRODUCT_ANALYSIS_PROMPT = """You are a Principal AI System Architect analyzing a software project.

Analyze the provided source files and return ONLY valid JSON describing the system as a real-world product.

PROJECT FILES:
{context}

DETECTED STRUCTURE:
- File count: {file_count}
- Architecture hints: {arch_hints}
- Key filenames: {filenames}

OUTPUT (JSON only — no markdown, no explanation):
{{
  "project_goal": "2-3 sentence product-level description of what this system does and why it matters",
  "architecture_style": "specific architecture label (layered, microservices, monolith, MVC, event-driven, serverless, etc.)",
  "key_modules": ["ONLY real filenames from the === FILE: headers ==="],
  "core_features": ["specific implemented capability derived from actual code — NOT generic"],
  "target_users": "specific real-world users this system serves",
  "tech_stack": ["detected languages, frameworks, databases, APIs"],
  "entry_points": ["files that serve as application entry points"],
  "execution_flow": "step-by-step flow from user input to system output based on actual code paths"
}}

STRICT RULES:
- key_modules MUST contain ONLY real filenames from the === FILE: headers ===
- core_features MUST be derived from actual code — never generic
- Lists MAY be empty when the code does not support a claim
- Do NOT invent values to fill arrays
- NEVER include "risks" or "summary_blocks" in output
- Return JSON ONLY"""

PRODUCT_ANALYSIS_FAST_PROMPT = """Analyze this compact project snapshot and return ONLY valid JSON.

PROJECT SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the project does as a product",
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only"],
  "core_features": ["implemented capabilities from code"],
  "target_users": "who uses this system",
  "tech_stack": ["detected technologies"],
  "entry_points": ["entry point files"],
  "execution_flow": "real execution flow"
}}

Return JSON ONLY. No risks. No summary_blocks."""

PRODUCT_GOAL_PROMPT = """Return ONLY valid JSON for the project goal and core features.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the project does as a real product",
  "core_features": ["implemented capability", "second capability"],
  "target_users": "who uses this"
}}"""

PRODUCT_ARCH_PROMPT = """Return ONLY valid JSON for the project architecture.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only", "second filename"],
  "tech_stack": ["language", "framework"],
  "entry_points": ["entry point file"]
}}"""

PRODUCT_FLOW_PROMPT = """Return ONLY valid JSON for the execution flow.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "execution_flow": "step-by-step flow from input to output based on code",
  "core_features": ["capability 1", "capability 2"]
}}"""


# ── RAG Summary Prompt ──────────────────────────────────────────
# Used ONLY for document/knowledge summarization — never for project analysis.

RAG_SUMMARY_PROMPT = """Summarize the following knowledge context and return structured JSON.

CONTEXT:
{context}

OUTPUT:
{{
  "summary": "clear summary of the provided content",
  "key_points": ["important point 1", "important point 2"],
  "topics": ["topic 1", "topic 2"]
}}

Return JSON ONLY."""


# ── Task Detection ──────────────────────────────────────────────

def detect_task_type(
    *,
    session_type: str | None = None,
    has_files: bool = False,
    has_documents: bool = False,
) -> TaskType:
    """
    Determine the correct task type based on input signals.

    PROJECT_ANALYSIS: code/folder/repo sessions with file content.
    RAG_SUMMARY: document/knowledge summarization.
    """
    if session_type in ("code", "folder", "repo"):
        return TaskType.PROJECT_ANALYSIS

    if has_files:
        return TaskType.PROJECT_ANALYSIS

    if has_documents:
        return TaskType.RAG_SUMMARY

    # Default to project analysis for safety
    return TaskType.PROJECT_ANALYSIS


# ── Prompt Selection ────────────────────────────────────────────

def get_analysis_prompt(task_type: TaskType, tier: str = "full") -> str:
    """
    Return the correct prompt template for the given task and tier.

    Args:
        task_type: PROJECT_ANALYSIS or RAG_SUMMARY
        tier: "full", "fast", "goal", "arch", or "flow"
    """
    if task_type == TaskType.RAG_SUMMARY:
        return RAG_SUMMARY_PROMPT

    prompt_map = {
        "full": PRODUCT_ANALYSIS_PROMPT,
        "fast": PRODUCT_ANALYSIS_FAST_PROMPT,
        "goal": PRODUCT_GOAL_PROMPT,
        "arch": PRODUCT_ARCH_PROMPT,
        "flow": PRODUCT_FLOW_PROMPT,
    }
    return prompt_map.get(tier, PRODUCT_ANALYSIS_PROMPT)


# ── Output Validation ──────────────────────────────────────────

_PROJECT_REQUIRED_FIELDS = {"project_goal", "architecture_style", "key_modules", "core_features"}
_PROJECT_FORBIDDEN_FIELDS = {"risks", "summary_blocks", "remaining", "issues"}


def validate_analysis_output(
    result: Dict[str, Any],
    task_type: TaskType,
    strict: bool = False,
) -> Dict[str, Any]:
    """
    Validate and clean the LLM output for the given task type.

    For PROJECT_ANALYSIS:
    - Strips forbidden fields (risks, summary_blocks)
    - Ensures required fields have non-empty values

    Args:
        result: Raw LLM output dict.
        task_type: Expected task type.
        strict: If True, raises ValueError on validation failure.

    Returns:
        Cleaned result dict.
    """
    if task_type != TaskType.PROJECT_ANALYSIS:
        return result

    cleaned = dict(result)

    # Strip forbidden fields
    removed = []
    for field in _PROJECT_FORBIDDEN_FIELDS:
        if field in cleaned:
            del cleaned[field]
            removed.append(field)

    if removed:
        logger.info(f"Stripped forbidden fields from project analysis: {removed}")

    # Validate required fields
    missing = []
    for field in _PROJECT_REQUIRED_FIELDS:
        value = cleaned.get(field)
        if not value or (isinstance(value, str) and len(value.strip()) < 5):
            missing.append(field)

    if missing and strict:
        raise ValueError(
            f"Project analysis missing required fields: {missing}. "
            f"LLM may have used wrong prompt type."
        )

    if missing:
        logger.warning(f"Project analysis has weak required fields: {missing}")

    return cleaned
