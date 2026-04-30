"""
Persistent knowledge storage for analysis sessions.

This module turns session analysis output into reusable project intelligence
that powers chat, reporting, and future retrieval.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List

from app.core.logging import get_logger
from app.db.models import (
    FunctionKnowledgeDocument,
    ModuleKnowledgeDocument,
    ProjectKnowledgeDocument,
    RelationshipGraphDocument,
    SessionStatus,
    SessionType,
    WorkflowKnowledgeDocument,
)
from app.db.repository import (
    FunctionKnowledgeRepository,
    ModuleKnowledgeRepository,
    ProjectKnowledgeRepository,
    RelationshipGraphRepository,
    WorkflowKnowledgeRepository,
)
from app.services.graph_builder import build_relationship_graph
from app.services.intelligence_engine import enrich_result_with_intelligence
from app.services.workflow_engine import detect_design_patterns, extract_workflows

logger = get_logger("services.knowledge_store")

_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)


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


def _extract_functions_from_content(content: str) -> List[tuple[str, str]]:
    function_names = [(name, "function") for name in _FUNCTION_RE.findall(content or "")]
    class_names = [(name, "class") for name in _CLASS_RE.findall(content or "")]
    combined: List[tuple[str, str]] = []
    seen: set[str] = set()
    for name, kind in function_names + class_names:
        if name in seen:
            continue
        seen.add(name)
        combined.append((name, kind))
    return combined[:20]


def _build_structured_summary(
    result: Dict[str, Any],
    workflows: List[Dict[str, Any]],
    graph_model: Dict[str, Any],
) -> tuple[str, str]:
    modules = _dedupe(result.get("key_modules", []))[:4]
    features = _dedupe(result.get("core_features", []))[:3]
    workflow_names = _dedupe(workflow.get("name", "") for workflow in workflows)[:2]
    workflow_steps = []
    for workflow in workflows[:2]:
        steps = workflow.get("steps", [])
        if isinstance(steps, list) and steps:
            workflow_steps.append(" -> ".join(_dedupe(steps)[:4]))
    dependency_pairs: List[str] = []
    for source, targets in list((graph_model.get("dependencies", {}) or {}).items())[:3]:
        if isinstance(targets, list) and targets:
            dependency_pairs.append(f"{source} -> {targets[0]}")
    central_nodes = _dedupe(graph_model.get("central_nodes", []))[:3]

    what_parts = [
        str(result.get("project_goal", "")).strip(),
        f"Key modules include {', '.join(modules)}." if modules else "",
        f"Observed workflows include {', '.join(workflow_names)}." if workflow_names else "Observed workflows align with initialization, request handling, processing, and response delivery.",
        f"Representative execution paths include {' | '.join(workflow_steps)}." if workflow_steps else "",
    ]
    why_parts = [
        str(result.get("architecture_style", "")).strip(),
        f"Core capabilities center on {', '.join(features)}." if features else "",
        f"Dependency relationships such as {', '.join(dependency_pairs)} help explain how responsibilities are split." if dependency_pairs else "Dependency graph is inferred from imports and module structure.",
        f"Central modules appear to be {', '.join(central_nodes)}." if central_nodes else "",
    ]
    what = " ".join(part for part in what_parts if part).strip()
    why = " ".join(part for part in why_parts if part).strip()
    return what, why


def build_workflows_from_result(
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
    session_type: SessionType,
) -> List[Dict[str, Any]]:
    workflows = extract_workflows(
        session_type=session_type.value,
        sampled_files=sampled_files,
        result=result,
    )
    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks", {}), dict) else {}
    if workflows:
        workflows[0]["confidence"] = "high" if "[HIGH confidence]" in str(summary_blocks.get("why", "")) else workflows[0].get("confidence", "medium")
    return workflows[:8]


async def persist_analysis_knowledge(
    *,
    session_id: str,
    session_type: SessionType,
    title: str,
    source_ref: str,
    structure: List[str],
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
    tech_stack: List[str] | None = None,
    status: SessionStatus = SessionStatus.COMPLETED,
) -> None:
    sampled_files = sampled_files or []
    tech_stack = tech_stack or []
    result = enrich_result_with_intelligence(
        session_type=session_type.value,
        result=result,
        sampled_files=sampled_files,
    )
    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks", {}), dict) else {}
    summary_text = str(summary_blocks.get("what", "")).strip()

    module_docs: List[ModuleKnowledgeDocument] = []
    function_docs: List[FunctionKnowledgeDocument] = []
    for index, file_info in enumerate(sampled_files[:20]):
        rel_path = str(file_info.get("path", "")).strip()
        content = str(file_info.get("content", "") or "")
        name = os.path.basename(rel_path) or rel_path or f"module-{index + 1}"
        module_docs.append(
            ModuleKnowledgeDocument(
                session_id=session_id,
                session_type=session_type,
                name=name,
                file_path=rel_path,
                role="priority module" if index < 5 else "supporting module",
                summary=f"Sampled module from {rel_path}" if rel_path else f"Sampled module {name}",
                importance=max(1, 100 - (index * 5)),
            )
        )
        for function_name, kind in _extract_functions_from_content(content):
            function_docs.append(
                FunctionKnowledgeDocument(
                    session_id=session_id,
                    session_type=session_type,
                    module_name=name,
                    name=function_name,
                    kind=kind,
                    signature=function_name,
                    summary=f"Detected {kind} in {name}",
                )
            )

    await ModuleKnowledgeRepository.replace_for_session(session_id, module_docs)
    await FunctionKnowledgeRepository.replace_for_session(session_id, function_docs[:80])

    workflow_models = build_workflows_from_result(result, sampled_files, session_type)
    workflow_docs = [
        WorkflowKnowledgeDocument(
            session_id=session_id,
            session_type=session_type,
            name=item["name"],
            summary=item["summary"],
            steps=item["steps"],
            confidence=item["confidence"],
            confidence_percent=int(item.get("confidence_percent", 0) or 0),
            uncertainty_reasons=list(item.get("uncertainty_reasons", [])),
            entry_point=str(item.get("entry_point", "")),
            modules=list(item.get("modules", [])),
        )
        for item in workflow_models
    ]
    await WorkflowKnowledgeRepository.replace_for_session(session_id, workflow_docs)

    graph_model = build_relationship_graph(
        session_type=session_type.value,
        sampled_files=sampled_files,
        workflows=workflow_models,
    )
    enriched_what, enriched_why = _build_structured_summary(result, workflow_models, graph_model)
    current_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks", {}), dict) else {}
    if enriched_what and not str(current_blocks.get("what", "")).strip():
        result.setdefault("summary_blocks", {})["what"] = enriched_what
        summary_text = enriched_what
    if enriched_why and not str(current_blocks.get("why", "")).strip():
        result.setdefault("summary_blocks", {})["why"] = enriched_why

    project_doc = ProjectKnowledgeDocument(
        session_id=session_id,
        session_type=session_type,
        title=title,
        source_ref=source_ref,
        project_goal=str(result.get("project_goal", "")).strip(),
        architecture_style=str(result.get("architecture_style", "")).strip(),
        domain=str(result.get("domain", "")).strip(),
        purpose=str(result.get("purpose", "")).strip(),
        target_users=str(result.get("target_users", "")).strip(),
        system_type=str(result.get("system_type", "")).strip(),
        core_behavior=str(result.get("core_behavior", "")).strip(),
        key_capabilities=_dedupe(result.get("key_capabilities", []))[:12],
        workflow_summary=str(result.get("workflow_summary", "")).strip(),
        analysis_focus=_dedupe(result.get("analysis_focus", []))[:8],
        domain_confidence=str(result.get("domain_confidence", "")).strip(),
        validated_domain=str(result.get("validated_domain", "")).strip(),
        validated_behavior=str(result.get("validated_behavior", "")).strip(),
        verification_confidence=str(result.get("verification_confidence", "")).strip(),
        fact_entry_points=_dedupe(result.get("fact_entry_points", []))[:8],
        fact_modules=_dedupe(result.get("fact_modules", []))[:8],
        fact_actions=_dedupe(result.get("fact_actions", []))[:8],
        fact_flow=str(result.get("fact_flow", "")).strip(),
        project_type=str(result.get("project_type", "")).strip(),
        project_goal_confidence=str(result.get("project_goal_confidence", "")).strip(),
        summary=summary_text,
        structure=_dedupe(structure)[:30],
        key_modules=_dedupe(result.get("key_modules", []))[:20],
        core_features=_dedupe(result.get("core_features", []))[:20],
        risks=_dedupe(result.get("risks", []))[:20],
        insights=list(result.get("insights", []))[:20] if isinstance(result.get("insights", []), list) else [],
        confidence_score=int(result.get("confidence_score", 0) or 0),
        confidence_reasons=_dedupe(result.get("confidence_reasons", []))[:12],
        tech_stack=_dedupe(tech_stack + [item["name"] for item in detect_design_patterns(
            architecture_style=str(result.get("architecture_style", "")).strip(),
            sampled_files=sampled_files,
        )])[:12],
        status=status,
    )
    await ProjectKnowledgeRepository.upsert(project_doc)

    await RelationshipGraphRepository.upsert(
        RelationshipGraphDocument(
            session_id=session_id,
            session_type=session_type,
            nodes=graph_model.get("nodes", []),
            edges=graph_model.get("edges", []),
            dependencies=graph_model.get("dependencies", {}),
            central_nodes=graph_model.get("central_nodes", []),
            entry_points=graph_model.get("entry_points", []),
            summary=graph_model.get("summary", ""),
            confidence=graph_model.get("confidence", "medium"),
            confidence_percent=int(graph_model.get("confidence_percent", 0) or 0),
            uncertainty_reasons=list(graph_model.get("uncertainty_reasons", [])),
        )
    )

    logger.info(
        "Persisted analysis knowledge",
        extra={"extra_data": {
            "session_id": session_id,
            "session_type": session_type.value,
            "modules": len(module_docs),
            "functions": len(function_docs[:80]),
            "workflows": len(workflow_docs),
            "graph_edges": len(graph_model.get("edges", [])),
        }},
    )


async def build_knowledge_snapshot(session_id: str) -> Dict[str, Any]:
    project = await ProjectKnowledgeRepository.get_by_session_id(session_id)
    modules = await ModuleKnowledgeRepository.list_for_session(session_id, limit=12)
    functions = await FunctionKnowledgeRepository.list_for_session(session_id, limit=20)
    workflows = await WorkflowKnowledgeRepository.list_for_session(session_id, limit=6)
    graph = await RelationshipGraphRepository.get_by_session_id(session_id)

    return {
        "project": project.model_dump() if project else None,
        "modules": [module.model_dump() for module in modules],
        "functions": [function.model_dump() for function in functions],
        "workflows": [workflow.model_dump() for workflow in workflows],
        "graph": graph.model_dump() if graph else None,
    }
