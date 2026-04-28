"""
Verification layer for inferred product and behavior analysis.

This pass rejects weak generic conclusions when stronger behavioral evidence is
available and returns a validated interpretation that downstream systems can
trust for chat, summaries, and persistence.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


_GENERIC_DOMAINS = {
    "",
    "unknown",
    "developer tools",
    "software infrastructure",
}

_GENERIC_SYSTEM_TYPES = {
    "",
    "application platform",
    "api platform",
    "code intelligence tool",
    "interactive web platform",
}


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in items:
        cleaned = " ".join(str(item).split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _is_generic_domain(domain: str) -> bool:
    return " ".join(str(domain).strip().lower().split()) in _GENERIC_DOMAINS


def _is_generic_system_type(system_type: str) -> bool:
    return " ".join(str(system_type).strip().lower().split()) in _GENERIC_SYSTEM_TYPES


def _build_behavior_statement(
    *,
    product_profile: Dict[str, Any],
    behavior_summary: Dict[str, Any],
    behavior_signals: Dict[str, bool],
    workflows: List[Dict[str, Any]],
    dependency_graph: Dict[str, Any],
) -> str:
    workflow_steps: List[str] = []
    for workflow in workflows[:2]:
        workflow_steps.extend(_dedupe(workflow.get("steps", []))[:3])
    workflow_steps = _dedupe(workflow_steps)[:6]
    central_nodes = _dedupe(dependency_graph.get("central_nodes", []))[:3]

    if (
        behavior_signals.get("extracts_claims")
        and behavior_signals.get("verifies_information")
    ) or str(product_profile.get("domain", "")).strip().lower() == "ai verification":
        details: List[str] = ["extracts claims"]
        if behavior_signals.get("uses_external_sources"):
            details.append("checks external evidence")
        if behavior_signals.get("scores_truth"):
            details.append("scores reliability")
        if behavior_signals.get("multi_agent"):
            details.append("coordinates multi-agent reasoning")
        return (
            "The system extracts claims, verifies them against evidence, "
            + ", ".join(details[1:])
            + "."
            if len(details) > 1
            else "The system extracts claims and verifies them against evidence."
        )

    if workflow_steps:
        return "Core execution flows through " + " -> ".join(workflow_steps[:5]) + "."

    if central_nodes:
        return (
            "Core behavior is coordinated through "
            + ", ".join(central_nodes)
            + " to deliver the main product workflow."
        )

    core_behavior = " ".join(str(behavior_summary.get("core_behavior", "")).split())
    if core_behavior:
        if core_behavior.endswith("."):
            return core_behavior
        return core_behavior + "."

    purpose = " ".join(str(product_profile.get("purpose", "")).split())
    if purpose:
        return purpose[0].upper() + purpose[1:] + "."

    return "The system routes inputs through its main logic path and returns structured results."


def validate_analysis(
    *,
    result: Dict[str, Any],
    product_profile: Dict[str, Any],
    analysis_plan: Dict[str, Any],
    behavior_summary: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
    workflows: List[Dict[str, Any]],
    dependency_graph: Dict[str, Any],
    behavior_signals: Dict[str, bool],
) -> Dict[str, str]:
    del sampled_files  # Reserved for deeper evidence checks as the layer grows.

    inferred_domain = " ".join(str(product_profile.get("domain", "")).split())
    inferred_system_type = " ".join(str(product_profile.get("system_type", "")).split())
    plan_confidence = " ".join(str(analysis_plan.get("confidence", "")).split()).lower()

    verification_signals = sum(
        1
        for key in ("extracts_claims", "verifies_information", "uses_external_sources", "scores_truth")
        if behavior_signals.get(key)
    )

    if behavior_signals.get("extracts_claims") and behavior_signals.get("verifies_information"):
        validated_domain = "AI verification"
    elif verification_signals >= 3:
        validated_domain = "AI verification"
    elif not _is_generic_domain(inferred_domain):
        validated_domain = inferred_domain
    elif behavior_signals.get("multi_agent") and behavior_signals.get("analysis_intelligence"):
        validated_domain = "AI verification" if behavior_signals.get("scores_truth") else "developer tools"
    else:
        validated_domain = inferred_domain or "developer tools"

    validated_behavior = _build_behavior_statement(
        product_profile=product_profile,
        behavior_summary=behavior_summary,
        behavior_signals=behavior_signals,
        workflows=workflows,
        dependency_graph=dependency_graph,
    )

    if validated_domain == "AI verification":
        confidence = "high" if verification_signals >= 3 or plan_confidence == "high" else "medium"
    elif not _is_generic_domain(inferred_domain) and not _is_generic_system_type(inferred_system_type):
        confidence = "high" if plan_confidence == "high" else "medium"
    elif workflows or dependency_graph.get("edges"):
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "validated_domain": validated_domain,
        "validated_behavior": validated_behavior,
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
    }
