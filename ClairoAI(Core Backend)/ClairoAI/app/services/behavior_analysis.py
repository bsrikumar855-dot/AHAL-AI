"""
Behavior analysis layer.

Transforms structural, workflow, and product signals into a concise
description of what the system actually does.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


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


def analyze_system_behavior(
    *,
    result: Dict[str, Any],
    product_profile: Dict[str, Any],
    workflows: List[Dict[str, Any]],
    dependency_graph: Dict[str, Any],
    behavior_signals: Dict[str, bool],
) -> Dict[str, Any]:
    domain = str(product_profile.get("domain", "")).strip()
    system_type = str(product_profile.get("system_type", "")).strip() or "application platform"
    purpose = str(product_profile.get("purpose", "")).strip()
    modules = _dedupe(result.get("key_modules", []))[:5]
    features = _dedupe(result.get("core_features", []))[:5]
    central_nodes = _dedupe(dependency_graph.get("central_nodes", []))[:4]
    workflow_steps = []
    for workflow in workflows[:2]:
        workflow_steps.extend(_dedupe(workflow.get("steps", []))[:4])
    workflow_steps = _dedupe(workflow_steps)[:8]

    key_capabilities: List[str] = []
    if behavior_signals.get("extracts_claims"):
        key_capabilities.append("Extracts claims or structured assertions from input content")
    if behavior_signals.get("verifies_information"):
        key_capabilities.append("Validates information against evidence or verification logic")
    if behavior_signals.get("uses_external_sources"):
        key_capabilities.append("Pulls in external data or evidence to strengthen decisions")
    if behavior_signals.get("scores_truth"):
        key_capabilities.append("Scores confidence, truthfulness, or risk")
    if behavior_signals.get("multi_agent"):
        key_capabilities.append("Coordinates multiple AI or logic agents across a staged pipeline")

    if not key_capabilities:
        if features:
            key_capabilities.extend(features[:3])
        elif modules:
            key_capabilities.append(f"Coordinates core logic across {', '.join(modules[:3])}")

    if domain.lower() == "ai verification":
        core_behavior = (
            "Processes generated content or claims, verifies them against evidence, and produces trust-aware judgments."
        )
        workflow = (
            "Input is analyzed for claims, evidence is gathered or referenced, verification logic evaluates reliability, and scored findings are returned as explainable output."
        )
        system_type = "AI-powered verification / hallucination detection system"
    elif domain.lower() == "developer tools":
        core_behavior = (
            "Transforms opaque codebases into actionable execution insight by tracing flows, responsibilities, and risk signals."
        )
        workflow = (
            "Inputs are scanned for structural and behavioral signals, execution paths are mapped, architectural relationships are ranked, and insights are returned for engineering decisions."
        )
    else:
        core_behavior = (
            purpose
            or "Coordinates its main workflow through structured logic, execution paths, and dependency-driven decisions."
        )
        workflow = (
            "The system receives an input or trigger, routes it through the primary logic path, executes its core processing steps, and returns a result shaped by the detected workflow."
        )

    if workflow_steps:
        workflow = " -> ".join(workflow_steps[:6])
    elif central_nodes:
        workflow = (
            f"Core execution moves through {', '.join(central_nodes[:3])} before returning the main product output."
        )

    return {
        "system_type": system_type,
        "core_behavior": core_behavior,
        "key_capabilities": _dedupe(key_capabilities)[:6],
        "workflow_summary": workflow,
    }
