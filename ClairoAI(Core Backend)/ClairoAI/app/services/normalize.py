"""
Output normalization utility.

Normalizes analysis results without inventing missing data.
"""

from typing import Any


_PLACEHOLDER_VALUES = {
    "unknown", "string", "n/a", "none", "null", "undefined",
    "not available", "not specified", "unable to determine",
    "failed to parse",
}


def _clean_str(val: Any, default: str = "") -> str:
    """Coerce value to a clean, trimmed string. Replace placeholders."""
    if val is None:
        return default
    s = str(val).strip()
    if s.lower() in _PLACEHOLDER_VALUES or not s:
        return default
    return s


def _clean_list(val: Any) -> list[str]:
    """Coerce value to a clean List[str], dropping empty/placeholder items."""
    if val is None:
        return []
    if isinstance(val, str):
        # Single string → list of one (unless placeholder)
        cleaned = _clean_str(val)
        return [cleaned] if cleaned else []
    if isinstance(val, list):
        result = []
        for item in val:
            cleaned = _clean_str(item)
            if cleaned:
                result.append(cleaned)
        return result
    return []


def normalize_result(result: dict) -> dict:
    """
    Final normalization pass on a unified result dict.

    Guarantees:
    - project_goal, architecture_style → non-placeholder strings
    - key_modules, core_features, risks → List[str], no empty items
    - summary_blocks.what, .why → clean strings
    - summary_blocks.remaining, .issues → List[str]
    """
    if not isinstance(result, dict):
        result = {}

    # Top-level string fields
    result["project_goal"] = _clean_str(result.get("project_goal"), "")
    result["architecture_style"] = _clean_str(
        result.get("architecture_style"), ""
    )
    result["domain"] = _clean_str(result.get("domain"), "")
    result["purpose"] = _clean_str(result.get("purpose"), "")
    result["target_users"] = _clean_str(result.get("target_users"), "")
    result["system_type"] = _clean_str(result.get("system_type"), "")
    result["core_behavior"] = _clean_str(result.get("core_behavior"), "")
    result["key_capabilities"] = _clean_list(result.get("key_capabilities"))
    result["workflow_summary"] = _clean_str(result.get("workflow_summary"), "")
    result["analysis_focus"] = _clean_list(result.get("analysis_focus"))
    result["domain_confidence"] = _clean_str(result.get("domain_confidence"), "")
    result["validated_domain"] = _clean_str(result.get("validated_domain"), "")
    result["validated_behavior"] = _clean_str(result.get("validated_behavior"), "")
    result["verification_confidence"] = _clean_str(result.get("verification_confidence"), "")
    result["fact_entry_points"] = _clean_list(result.get("fact_entry_points"))
    result["fact_modules"] = _clean_list(result.get("fact_modules"))
    result["fact_actions"] = _clean_list(result.get("fact_actions"))
    result["fact_flow"] = _clean_str(result.get("fact_flow"), "")
    result["project_type"] = _clean_str(result.get("project_type"), "")
    result["project_goal_confidence"] = _clean_str(result.get("project_goal_confidence"), "")

    # Top-level list fields
    result["key_modules"] = _clean_list(result.get("key_modules"))
    result["core_features"] = _clean_list(result.get("core_features"))
    result["risks"] = _clean_list(result.get("risks"))
    result["insights"] = _clean_list(result.get("insights"))
    result["confidence_reasons"] = _clean_list(result.get("confidence_reasons"))
    try:
        result["confidence_score"] = max(0, min(int(result.get("confidence_score", 0) or 0), 100))
    except (TypeError, ValueError):
        result["confidence_score"] = 0

    workflows = result.get("workflows")
    result["workflows"] = workflows if isinstance(workflows, list) else []
    dependency_graph = result.get("dependency_graph")
    result["dependency_graph"] = dependency_graph if isinstance(dependency_graph, dict) else {}

    # Summary blocks
    blocks = result.get("summary_blocks")
    if not isinstance(blocks, dict):
        blocks = {}

    blocks["what"] = _clean_str(blocks.get("what"), "")
    blocks["why"] = _clean_str(blocks.get("why"), "")
    blocks["remaining"] = _clean_list(blocks.get("remaining"))
    blocks["issues"] = _clean_list(blocks.get("issues"))

    result["summary_blocks"] = blocks

    return result
