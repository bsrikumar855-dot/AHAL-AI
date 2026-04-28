"""
Context Integrity Guard.

Detects when the analysis pipeline is accidentally processing
its OWN source files instead of an externally uploaded project.

This provides a critical safety net against self-referential analysis,
which would produce misleading results and undermine user trust.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from app.core.logging import get_logger

logger = get_logger("context_guard")

# ── Internal system file patterns ────────────────────────────────
# If a significant fraction of sampled files match these patterns,
# the pipeline is analyzing itself rather than an uploaded project.

_INTERNAL_FILENAMES = frozenset({
    "main.py",
    "repo_service.py",
    "code_analyzer.py",
    "folder_analyzer.py",
    "intelligence_engine.py",
    "product_inference.py",
    "workflow_engine.py",
    "graph_builder.py",
    "chat_service.py",
    "reasoning_engine.py",
    "knowledge_store.py",
    "llm_handler.py",
    "context_builder.py",
    "chat_prompt_builder.py",
    "behavior_analysis.py",
    "verification_analysis.py",
    "product_identity.py",
    "context_guard.py",
    "normalize.py",
    "postprocessor.py",
    "preprocessor.py",
    "memory_service.py",
    "risk_analyzer.py",
    "summarizer.py",
    "report_service.py",
    "query_engine.py",
    "llm_wrapper.py",
    "job_manager.py",
    "file_handler.py",
    "analysis_service.py",
})

_INTERNAL_PATH_FRAGMENTS = (
    "clairoai",
    "contextbridge",
    "ahal ai",
    "ahal_ai",
    "app/services/",
    "app/api/v1/",
    "app/core/",
    "app/db/",
)


class SelfAnalysisDetected(Exception):
    """Raised when the pipeline detects it is analyzing its own source code."""

    def __init__(self, matched_files: List[str], match_ratio: float):
        self.matched_files = matched_files
        self.match_ratio = match_ratio
        super().__init__(
            f"Self-analysis detected: {len(matched_files)} internal files "
            f"({match_ratio:.0%} of sample). Pipeline is analyzing its own "
            f"source code instead of the uploaded project."
        )


def classify_context(
    sampled_files: List[Dict[str, str]],
    threshold: float = 0.4,
) -> Dict[str, Any]:
    """
    Classify whether sampled files belong to an external project
    or to the AHAL AI system itself.

    Args:
        sampled_files: List of file dicts with 'path' and 'content' keys.
        threshold: Fraction of internal matches (0.0–1.0) that triggers detection.

    Returns:
        Dict with:
            - context_type: "VALID_PROJECT" | "MIXED_CONTEXT" | "INTERNAL_ONLY"
            - internal_files: list of matched internal file paths
            - external_files: list of external file paths
            - match_ratio: fraction of files that are internal
    """
    if not sampled_files:
        return {
            "context_type": "VALID_PROJECT",
            "internal_files": [],
            "external_files": [],
            "match_ratio": 0.0,
        }

    internal_files: List[str] = []
    external_files: List[str] = []

    for file_info in sampled_files:
        path = str(file_info.get("path", "")).strip()
        if not path:
            continue

        basename = os.path.basename(path).lower()
        path_lower = path.lower().replace("\\", "/")

        is_internal = False

        # Check filename match
        if basename in _INTERNAL_FILENAMES:
            is_internal = True

        # Check path fragment match
        if not is_internal:
            for fragment in _INTERNAL_PATH_FRAGMENTS:
                if fragment in path_lower:
                    is_internal = True
                    break

        if is_internal:
            internal_files.append(path)
        else:
            external_files.append(path)

    total = len(internal_files) + len(external_files)
    match_ratio = len(internal_files) / total if total > 0 else 0.0

    if match_ratio >= 0.9:
        context_type = "INTERNAL_ONLY"
    elif match_ratio >= threshold:
        context_type = "MIXED_CONTEXT"
    else:
        context_type = "VALID_PROJECT"

    return {
        "context_type": context_type,
        "internal_files": internal_files,
        "external_files": external_files,
        "match_ratio": match_ratio,
    }


def guard_against_self_analysis(
    sampled_files: List[Dict[str, str]],
    threshold: float = 0.4,
    raise_on_detection: bool = False,
) -> Dict[str, Any]:
    """
    Run context guard and optionally raise if self-analysis is detected.

    Args:
        sampled_files: List of file dicts.
        threshold: Internal match ratio that triggers guard.
        raise_on_detection: If True, raises SelfAnalysisDetected exception.

    Returns:
        Classification result with context_type and file lists.
        If MIXED_CONTEXT, returns only the filtered external files.
    """
    result = classify_context(sampled_files, threshold)

    if result["context_type"] == "INTERNAL_ONLY":
        logger.warning(
            "SELF-ANALYSIS DETECTED — pipeline is analyzing its own source code",
            extra={"extra_data": {
                "matched_count": len(result["internal_files"]),
                "match_ratio": result["match_ratio"],
                "sample_matches": result["internal_files"][:5],
            }},
        )
        if raise_on_detection:
            raise SelfAnalysisDetected(
                matched_files=result["internal_files"],
                match_ratio=result["match_ratio"],
            )

    elif result["context_type"] == "MIXED_CONTEXT":
        logger.warning(
            "MIXED CONTEXT detected — filtering out internal system files",
            extra={"extra_data": {
                "internal_count": len(result["internal_files"]),
                "external_count": len(result["external_files"]),
                "removed": result["internal_files"][:5],
            }},
        )

    return result


def filter_external_files(
    sampled_files: List[Dict[str, str]],
    threshold: float = 0.4,
) -> List[Dict[str, str]]:
    """
    Return only external (non-internal) files from the sample.

    If all files are internal, returns the original list unchanged
    (to avoid empty results — the caller should check context_type).
    """
    result = classify_context(sampled_files, threshold)

    if result["context_type"] == "VALID_PROJECT":
        return sampled_files

    external_paths = set(result["external_files"])

    if not external_paths:
        # All files are internal — return original to avoid empty pipeline
        return sampled_files

    return [
        f for f in sampled_files
        if str(f.get("path", "")).strip() in external_paths
    ]
