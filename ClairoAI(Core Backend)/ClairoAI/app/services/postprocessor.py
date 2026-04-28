"""
Post-processing pipeline for LLM-generated summaries.

Validates, deduplicates, and applies confidence thresholds
to raw LLM output before storage.
"""

from typing import Optional
from difflib import SequenceMatcher

from app.db.models import SummaryContent, ConfidenceField
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("postprocessor")


def validate_summary_structure(raw_summary: dict) -> SummaryContent:
    """
    Validate and normalize the raw LLM summary into a SummaryContent model.

    Ensures all expected fields exist with proper types.
    Assigns default low-confidence values for missing fields.
    """
    fields = ["what_done", "why_done", "what_remains", "potential_issues"]
    validated = {}

    for field in fields:
        if field in raw_summary and isinstance(raw_summary[field], dict):
            text = str(raw_summary[field].get("text", "")).strip()
            confidence = float(raw_summary[field].get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
            validated[field] = ConfidenceField(text=text, confidence=confidence)
        else:
            # Field missing or malformed — flag with zero confidence
            validated[field] = ConfidenceField(
                text="Unable to determine from input",
                confidence=0.0,
            )
            logger.warning(f"Summary field '{field}' was missing or malformed")

    return SummaryContent(**validated)


def check_confidence_flags(summary: SummaryContent) -> bool:
    """
    Check if any field falls below the confidence threshold.

    Returns True if the summary should be flagged for human review.
    """
    settings = get_settings()
    threshold = settings.CONFIDENCE_THRESHOLD

    fields = [
        ("what_done", summary.what_done),
        ("why_done", summary.why_done),
        ("what_remains", summary.what_remains),
        ("potential_issues", summary.potential_issues),
    ]

    flagged = False
    for name, field in fields:
        if field.confidence < threshold:
            logger.info(
                f"Low confidence on '{name}': {field.confidence:.2f} "
                f"(threshold: {threshold})"
            )
            flagged = True

    return flagged


def deduplicate_check(
    new_summary: SummaryContent,
    existing_text: Optional[str] = None,
    similarity_threshold: float = 0.85,
) -> bool:
    """
    Check if the new summary is too similar to existing content.

    Uses SequenceMatcher for fast fuzzy string comparison.
    Returns True if the summary appears to be a duplicate.
    """
    if existing_text is None:
        return False

    new_text = " ".join([
        new_summary.what_done.text,
        new_summary.why_done.text,
        new_summary.what_remains.text,
        new_summary.potential_issues.text,
    ])

    ratio = SequenceMatcher(None, new_text.lower(), existing_text.lower()).ratio()

    if ratio >= similarity_threshold:
        logger.info(f"Duplicate detected: similarity ratio {ratio:.2f}")
        return True

    return False


def validate_against_input(
    summary: SummaryContent,
    original_input: str,
) -> SummaryContent:
    """
    Cross-validate summary claims against the original input.

    This is a lightweight hallucination check: if the summary
    mentions specific identifiers (function names, file paths)
    that don't appear in the input, lower the confidence scores.

    This is not a perfect check — it's a safety net.
    """
    import re

    input_lower = original_input.lower()

    fields = [
        ("what_done", summary.what_done),
        ("why_done", summary.why_done),
        ("what_remains", summary.what_remains),
        ("potential_issues", summary.potential_issues),
    ]

    for name, field in fields:
        # Extract identifiers mentioned in the summary (snake_case, camelCase, paths)
        identifiers = re.findall(
            r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b",
            field.text,
        )

        # Filter to non-common-english words (rough heuristic)
        common_words = {
            "the", "and", "for", "was", "were", "that", "this", "with",
            "from", "are", "has", "had", "not", "but", "been", "can",
            "will", "may", "should", "could", "would", "does", "did",
            "added", "removed", "changed", "updated", "fixed", "new",
            "old", "file", "function", "method", "class", "module",
            "code", "test", "error", "issue", "bug", "feature",
            "implementation", "refactored", "improved", "existing",
            "potential", "issues", "changes", "remaining", "work",
            "needs", "done", "completed", "still", "also", "some",
            "more", "other", "possible", "might", "ensure", "properly",
        }

        specific_identifiers = [
            ident for ident in identifiers
            if ident.lower() not in common_words and len(ident) > 3
        ]

        if specific_identifiers:
            found = sum(
                1 for ident in specific_identifiers
                if ident.lower() in input_lower
            )
            total = len(specific_identifiers)

            if total > 0:
                presence_ratio = found / total
                # If most identifiers aren't in the input, lower confidence
                if presence_ratio < 0.3 and field.confidence > 0.5:
                    adjusted = field.confidence * 0.7
                    logger.warning(
                        f"Hallucination check: '{name}' references identifiers "
                        f"not in input ({found}/{total}). "
                        f"Confidence: {field.confidence:.2f} → {adjusted:.2f}"
                    )
                    field.confidence = round(adjusted, 2)

    return summary


def postprocess_summary(
    raw_summary: dict,
    original_input: str,
) -> tuple[SummaryContent, bool]:
    """
    Full post-processing pipeline for an LLM-generated summary.

    Steps:
        1. Validate and normalize structure
        2. Cross-validate against input (hallucination check)
        3. Check confidence thresholds
        4. Return (processed_summary, flagged_for_review)
    """
    # Step 1: Validate structure
    summary = validate_summary_structure(raw_summary)

    # Step 2: Hallucination check
    summary = validate_against_input(summary, original_input)

    # Step 3: Confidence flags
    flagged = check_confidence_flags(summary)

    logger.info(
        "Post-processing complete",
        extra={"extra_data": {"flagged_for_review": flagged}},
    )

    return summary, flagged
