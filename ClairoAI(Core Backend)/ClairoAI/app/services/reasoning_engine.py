"""
Reasoning engine for contextual software explanations.

This layer queries persisted knowledge first, then prepares a refined prompt
for the LLM to format and deepen the answer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.knowledge_store import build_knowledge_snapshot


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


def detect_question_intent(question: str, chat_mode: str) -> str:
    lowered = question.lower()
    if any(token in lowered for token in ("workflow", "flow", "request path", "how does", "login", "authentication")):
        return "workflow"
    if any(token in lowered for token in ("architecture", "design", "pattern", "layer", "microservice", "coupling")):
        return "architecture"
    if any(token in lowered for token in ("bug", "issue", "risk", "debug", "problem", "failure")):
        return "debugging"
    if any(token in lowered for token in ("module", "folder", "file", "component", "service")):
        return "structure"
    return "architecture" if chat_mode == "repo" else "structure"


def _select_relevant_workflows(workflows: List[Dict[str, Any]], question: str) -> List[Dict[str, Any]]:
    lowered = question.lower()
    scored = []
    for workflow in workflows:
        haystack = " ".join(
            [str(workflow.get("name", "")), str(workflow.get("summary", ""))] + [str(step) for step in workflow.get("steps", [])]
        ).lower()
        score = sum(1 for token in lowered.split() if token and token in haystack)
        scored.append((score, workflow))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [item[1] for item in scored if item[0] > 0]
    return (selected or workflows)[:3]


def _select_relevant_modules(modules: List[Dict[str, Any]], question: str) -> List[Dict[str, Any]]:
    lowered = question.lower()
    scored = []
    for module in modules:
        haystack = " ".join([str(module.get("name", "")), str(module.get("file_path", "")), str(module.get("role", "")), str(module.get("summary", ""))]).lower()
        score = sum(1 for token in lowered.split() if token and token in haystack)
        scored.append((score, module))
    scored.sort(key=lambda item: (item[0], item[1].get("importance", 0)), reverse=True)
    selected = [item[1] for item in scored if item[0] > 0]
    return (selected or modules)[:6]


def _find_graph_paths(graph: Dict[str, Any], modules: List[Dict[str, Any]]) -> List[str]:
    edges = graph.get("edges", []) if isinstance(graph, dict) else []
    module_names = {str(module.get("name", "")) for module in modules}
    paths = []
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        relation = str(edge.get("relation", "depends_on"))
        if any(name and name in source for name in module_names) or any(name and name in target for name in module_names):
            paths.append(f"{source} -[{relation}]-> {target}")
    return _dedupe(paths)[:8]


def _build_level_explanations(intent: str, project: Dict[str, Any] | None, workflows: List[Dict[str, Any]], modules: List[Dict[str, Any]], graph_paths: List[str]) -> Dict[str, str]:
    project_goal = str((project or {}).get("project_goal", "")).strip()
    architecture = str((project or {}).get("architecture_style", "")).strip()
    domain = str((project or {}).get("domain", "")).strip()
    purpose = str((project or {}).get("purpose", "")).strip()
    target_users = str((project or {}).get("target_users", "")).strip()
    system_type = str((project or {}).get("system_type", "")).strip()
    summary = str((project or {}).get("summary", "")).strip()
    module_names = _dedupe(module.get("name", "") for module in modules)[:5]
    workflow_names = _dedupe(workflow.get("name", "") for workflow in workflows)[:3]

    short = summary or project_goal or "The analyzed system is organized into focused modules."
    developer = (
        f"The {domain or 'analyzed'} {system_type or 'platform'} centers on {project_goal or purpose or 'the analyzed application flow'}. "
        f"The most relevant modules here are {', '.join(module_names) or 'the stored core modules'}, "
        f"and the key workflow is {', '.join(workflow_names) or 'the primary application path'}."
    )
    architect = (
        f"Architecturally, this looks like {architecture or 'a structured application'}, "
        f"with execution paths that move through {', '.join(module_names[:3]) or 'the main modules'}. "
        f"Observed relationships include {', '.join(graph_paths[:3]) or 'module-to-module dependencies captured in the knowledge graph'}."
    )
    if target_users:
        developer += f" It is oriented toward {target_users}."

    if intent == "debugging":
        developer += " For debugging, trace the workflow steps and dependency edges in order because that shows where state and control change hands."
        architect += " The main risk is usually hidden coupling across service, controller, and data-access boundaries."
    elif intent == "workflow":
        developer += " The workflow steps below show the actual execution order inferred from routes, handlers, and downstream calls."
        architect += " This is useful because it explains not just which modules exist, but why they collaborate in that order."

    return {
        "summary": short,
        "developer": developer,
        "architect": architect,
    }


async def build_reasoning_context(session_id: str, question: str, chat_mode: str) -> Dict[str, Any]:
    snapshot = await build_knowledge_snapshot(session_id)
    intent = detect_question_intent(question, chat_mode)
    project = snapshot.get("project")
    modules = snapshot.get("modules", [])
    workflows = snapshot.get("workflows", [])
    graph = snapshot.get("graph")

    selected_workflows = _select_relevant_workflows(workflows, question)
    selected_modules = _select_relevant_modules(modules, question)
    graph_paths = _find_graph_paths(graph or {}, selected_modules)
    levels = _build_level_explanations(intent, project, selected_workflows, selected_modules, graph_paths)

    context_lines = [
        f"Intent: {intent}",
        f"Project Goal: {str((project or {}).get('project_goal', '')).strip()}",
        f"Domain: {str((project or {}).get('domain', '')).strip()}",
        f"Purpose: {str((project or {}).get('purpose', '')).strip()}",
        f"Target Users: {str((project or {}).get('target_users', '')).strip()}",
        f"System Type: {str((project or {}).get('system_type', '')).strip()}",
        f"Architecture: {str((project or {}).get('architecture_style', '')).strip()}",
        f"Stored Summary: {str((project or {}).get('summary', '')).strip()}",
        f"Relevant Modules: {', '.join(module.get('name', '') for module in selected_modules if module.get('name'))}",
        f"Relevant Workflows: {', '.join(workflow.get('name', '') for workflow in selected_workflows if workflow.get('name'))}",
    ]
    if selected_workflows:
        for workflow in selected_workflows[:3]:
            context_lines.append(
                f"Workflow {workflow.get('name', 'Primary Flow')}: " + " -> ".join(workflow.get("steps", [])[:8])
            )
    if graph_paths:
        context_lines.append("Relationship Paths: " + " | ".join(graph_paths[:6]))

    return {
        "intent": intent,
        "knowledge_snapshot": snapshot,
        "relevant_modules": selected_modules,
        "relevant_workflows": selected_workflows,
        "graph_paths": graph_paths,
        "explanations": levels,
        "context_string": "\n".join(line for line in context_lines if line.strip()),
    }
