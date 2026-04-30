"""
Shared intelligence synthesis helpers.

This layer combines structural signals, workflow extraction, dependency
mapping, and inferred engineering insights into a single normalized payload.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from app.services.behavior_analysis import analyze_system_behavior
from app.services.graph_builder import build_relationship_graph
from app.services.product_inference import (
    build_project_goal,
    extract_fact_sheet,
    extract_behavior_signals,
    infer_analysis_plan,
    infer_product_profile,
)
from app.services.verification_analysis import validate_analysis
from app.services.workflow_engine import extract_workflows

_ENTRYPOINT_HINTS = ("main", "app", "server", "index", "bootstrap", "startup", "create_app")


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    cleaned_items: List[str] = []
    for item in items:
        cleaned = " ".join(str(item).split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_items.append(cleaned)
    return cleaned_items


def _extract_entry_points(sampled_files: List[Dict[str, str]]) -> List[str]:
    entry_points: List[str] = []
    for file_info in sampled_files[:20]:
        path = str(file_info.get("path", "") or "")
        basename = os.path.basename(path).lower()
        if any(hint in basename for hint in _ENTRYPOINT_HINTS):
            entry_points.append(os.path.basename(path) or path)
    return _dedupe(entry_points)[:6]


def _ensure_step_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return _dedupe(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return []


def generate_inferred_workflow(context: Dict[str, Any] | None = None) -> Dict[str, List[str]]:
    return {
        "initialization": [],
        "request_flow": [],
        "processing_flow": [],
        "response_flow": [],
    }


def generate_basic_insights(context: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    return []


def _build_insights(
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
    workflows: List[Dict[str, Any]],
    graph: Dict[str, Any],
) -> List[Dict[str, str]]:
    return []


def _compute_confidence(
    sampled_files: List[Dict[str, str]],
    workflows: List[Dict[str, Any]],
    graph: Dict[str, Any],
    result: Dict[str, Any],
) -> tuple[int, List[str]]:
    score = 58
    reasons: List[str] = []

    if sampled_files:
        score += min(len(sampled_files), 10)
        reasons.append(f"Sampled {min(len(sampled_files), 10)} prioritized files")
    else:
        reasons.append("Limited file sampling was available")

    graph_edges = len(graph.get("edges", []) or [])
    if graph_edges >= 8:
        score += 10
        reasons.append("Dependency graph contains multiple directed relationships")
    else:
        reasons.append("Dependency graph was inferred from a smaller relationship sample")

    explicit_workflows = [
        workflow for workflow in workflows
        if not workflow.get("message") and (workflow.get("confidence_percent", 0) or 0) >= 75
    ]
    if explicit_workflows:
        score += 12
        reasons.append("Execution flows were grounded in explicit routes or call chains")
    else:
        reasons.append("Some workflow steps were inferred from structure and naming")

    if "[HIGH confidence]" in str(result.get("summary_blocks", {}).get("why", "")):
        score += 8
        reasons.append("Semantic refinement completed through deeper AI passes")
    else:
        reasons.append("Semantic refinement relied partly on inferred logic")

    score = max(45, min(score, 96))
    return score, _dedupe(reasons)[:6]


def enrich_result_with_intelligence(
    *,
    session_type: str,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    sampled_files = sampled_files or []

    # ── Context integrity guard ─────────────────────────────────
    # Detect if the pipeline is accidentally analyzing its own source code.
    from app.services.context_guard import guard_against_self_analysis, filter_external_files

    guard_result = guard_against_self_analysis(sampled_files, threshold=0.4)
    context_type = guard_result["context_type"]

    if context_type == "MIXED_CONTEXT":
        # Filter out internal files and continue with external only
        sampled_files = filter_external_files(sampled_files)

    if context_type == "INTERNAL_ONLY":
        # Log warning but continue — the caller may intentionally want this
        result.setdefault("_context_warning", (
            f"Self-analysis detected: {len(guard_result['internal_files'])} of "
            f"{len(guard_result['internal_files']) + len(guard_result['external_files'])} "
            f"sampled files belong to the AHAL AI platform itself."
        ))

    enriched = dict(result)
    workflows = extract_workflows(
        session_type=session_type,
        sampled_files=sampled_files,
        result=enriched,
    )
    graph = build_relationship_graph(
        session_type=session_type,
        sampled_files=sampled_files,
        workflows=workflows,
    )
    graph["entry_points"] = _extract_entry_points(sampled_files)
    insights = _build_insights(enriched, sampled_files, workflows, graph)
    system_workflow: Dict[str, List[str]] = {
        "initialization": [],
        "request_flow": [],
        "processing_flow": [],
        "response_flow": [],
    }
    for workflow in workflows:
        name = str(workflow.get("name", "")).lower()
        summary = str(workflow.get("summary", "")).strip()
        steps = _dedupe(workflow.get("steps", []))[:5]
        detail = [summary] if summary else steps
        if "initialization" in name and detail:
            system_workflow["initialization"] = _ensure_step_list(detail)
        elif "request" in name and detail:
            system_workflow["request_flow"] = _ensure_step_list(detail)
        elif ("processing" in name or "data" in name) and detail:
            system_workflow["processing_flow"] = _ensure_step_list(detail)
        elif "response" in name and detail:
            system_workflow["response_flow"] = _ensure_step_list(detail)
    confidence_score, confidence_reasons = _compute_confidence(sampled_files, workflows, graph, enriched)
    behavior_signals = extract_behavior_signals(enriched, sampled_files)
    product_profile = infer_product_profile(
        result=enriched,
        sampled_files=sampled_files,
        session_type=session_type,
    )
    analysis_plan = infer_analysis_plan(
        result=enriched,
        sampled_files=sampled_files,
        session_type=session_type,
    )

    enriched["domain"] = str(product_profile.get("domain", "")).strip()
    enriched["purpose"] = str(product_profile.get("purpose", "")).strip()
    enriched["target_users"] = str(product_profile.get("target_users", "")).strip()
    enriched["system_type"] = str(product_profile.get("system_type", "")).strip()
    enriched["analysis_focus"] = list(analysis_plan.get("focus", []))
    enriched["domain_confidence"] = str(analysis_plan.get("confidence", "")).strip()
    behavior_summary = analyze_system_behavior(
        result=enriched,
        product_profile=product_profile,
        workflows=workflows,
        dependency_graph=graph,
        behavior_signals=behavior_signals,
    )
    verification = validate_analysis(
        result=enriched,
        product_profile=product_profile,
        analysis_plan=analysis_plan,
        behavior_summary=behavior_summary,
        sampled_files=sampled_files,
        workflows=workflows,
        dependency_graph=graph,
        behavior_signals=behavior_signals,
    )
    verified_domain = str(verification.get("validated_domain", "")).strip()
    if verified_domain:
        enriched["validated_domain"] = verified_domain
        if verified_domain != str(enriched.get("domain", "")).strip():
            enriched["domain"] = verified_domain
    enriched["validated_behavior"] = str(verification.get("validated_behavior", "")).strip()
    enriched["verification_confidence"] = str(verification.get("confidence", "")).strip()
    enriched["system_type"] = str(behavior_summary.get("system_type", enriched.get("system_type", ""))).strip()
    if verified_domain == "AI verification":
        enriched["system_type"] = "verification and hallucination detection system"
    fact_sheet = extract_fact_sheet(result=enriched, sampled_files=sampled_files)
    enriched["fact_entry_points"] = list(fact_sheet.get("entry_points", []))
    enriched["fact_modules"] = list(fact_sheet.get("modules", []))
    enriched["fact_actions"] = list(fact_sheet.get("actions", []))
    enriched["fact_flow"] = str(fact_sheet.get("flow", "")).strip()
    enriched["project_type"] = str(fact_sheet.get("project_type", "")).strip()
    enriched["project_goal_confidence"] = str(fact_sheet.get("confidence", "")).strip()
    enriched["project_goal"] = build_project_goal(
        {**product_profile, "domain": verified_domain or product_profile.get("domain", ""), "system_type": enriched["system_type"]},
        enriched,
        sampled_files,
    )
    enriched["core_behavior"] = str(behavior_summary.get("core_behavior", "")).strip()
    enriched["key_capabilities"] = list(behavior_summary.get("key_capabilities", []))
    enriched["workflow_summary"] = str(behavior_summary.get("workflow_summary", "")).strip()
    if not system_workflow or isinstance(system_workflow, str):
        system_workflow = generate_inferred_workflow({"result": enriched, "workflows": workflows, "graph": graph})
    else:
        system_workflow = {
            "initialization": _ensure_step_list(system_workflow.get("initialization")),
            "request_flow": _ensure_step_list(system_workflow.get("request_flow")),
            "processing_flow": _ensure_step_list(system_workflow.get("processing_flow")),
            "response_flow": _ensure_step_list(system_workflow.get("response_flow")),
        }
    if not insights or isinstance(insights, str):
        insights = generate_basic_insights({"result": enriched, "workflows": workflows, "graph": graph})
    enriched["system_workflow"] = system_workflow
    enriched["workflows"] = workflows
    enriched["dependency_graph"] = graph
    enriched["insights"] = insights
    enriched["confidence_score"] = confidence_score
    enriched["confidence_reasons"] = confidence_reasons
    return enriched
