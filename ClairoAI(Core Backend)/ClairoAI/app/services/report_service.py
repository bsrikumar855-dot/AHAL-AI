"""
Premium project report generator.

Builds a polished Markdown report from analyzed session data so the output can
be exported directly into presentation-ready PDF documents.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _clean_list(values: Any, limit: int | None = None) -> list[str]:
    if not isinstance(values, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if limit and len(cleaned) >= limit:
            break
    return cleaned


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        cleaned = _clean_text(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if _clean_text(item))


def _render_numbered(items: list[str]) -> str:
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1) if _clean_text(item))


def _render_callout(title: str, body: str) -> str:
    return "\n".join(
        [
            f"> **{title}**",
            f"> {body}",
        ]
    )


def _short_paragraph(text: str, fallback: str, max_sentences: int = 2) -> str:
    source = _clean_text(text) or fallback
    parts = [part.strip() for part in source.replace("!", ".").split(".") if part.strip()]
    if not parts:
        return fallback
    return ". ".join(parts[:max_sentences]).rstrip(".") + "."


def _infer_tech_stack(result: Dict[str, Any], knowledge_snapshot: Dict[str, Any]) -> dict[str, list[str]]:
    project = knowledge_snapshot.get("project") if isinstance(knowledge_snapshot.get("project"), dict) else {}
    tech_stack = _clean_list(result.get("tech_stack", []), limit=12)
    tech_stack += _clean_list(project.get("tech_stack", []), limit=12)
    merged = _dedupe(tech_stack)

    backend = [item for item in merged if any(token in item.lower() for token in ("fastapi", "flask", "django", "express", "node", "python", "api"))]
    frontend = [item for item in merged if any(token in item.lower() for token in ("react", "next", "vue", "frontend", "typescript", "javascript", "ui"))]
    database = [item for item in merged if any(token in item.lower() for token in ("mongo", "postgres", "mysql", "redis", "sqlite", "database", "storage"))]
    ai_layer = [item for item in merged if any(token in item.lower() for token in ("gemini", "openai", "ollama", "llm", "ai", "agent", "reasoning"))]

    return {
        "backend": backend[:4] or ["FastAPI / Python service layer"],
        "frontend": frontend[:4] or ["React / interactive UI layer"],
        "database": database[:4] or ["MongoDB / persistent storage layer"],
        "ai": ai_layer[:4] or ["LLM reasoning plus structured extraction and synthesis"],
    }


def _infer_module_responsibility(name: str, role: str = "", summary: str = "") -> str:
    lowered = f"{name} {role} {summary}".lower()
    if any(token in lowered for token in ("main", "app", "server", "entry")):
        return "entry point, API routing, and system orchestration"
    if any(token in lowered for token in ("analy", "parser", "workflow", "graph", "intelligence")):
        return "extracts structure, dependencies, and execution logic"
    if any(token in lowered for token in ("orchestr", "manager", "pipeline", "job")):
        return "coordinates AI reasoning and the analysis pipeline"
    if any(token in lowered for token in ("db", "mongo", "repo", "storage", "session")):
        return "handles persistence and session storage"
    if any(token in lowered for token in ("config", "settings", "env")):
        return "manages system configuration and environment"
    if any(token in lowered for token in ("security", "auth", "guard", "validate")):
        return "ensures safe input handling and validation"
    if any(token in lowered for token in ("chat", "prompt", "context")):
        return "grounds assistant responses with contextual system knowledge"
    if any(token in lowered for token in ("report", "export")):
        return "turns analysis output into polished documentation and summaries"
    if summary:
        return summary
    return "supports a core stage of the product intelligence workflow"


def _infer_core_modules(result: Dict[str, Any], knowledge_snapshot: Dict[str, Any]) -> list[str]:
    module_docs = knowledge_snapshot.get("modules") if isinstance(knowledge_snapshot.get("modules"), list) else []
    rendered: list[str] = []
    for module in module_docs[:8]:
        if not isinstance(module, dict):
            continue
        name = _clean_text(module.get("name") or module.get("file_path"))
        if not name:
            continue
        rendered.append(f"{name} -> {_infer_module_responsibility(name, _clean_text(module.get('role')), _clean_text(module.get('summary')))}")

    if rendered:
        return rendered

    key_modules = _clean_list(result.get("key_modules", []), limit=8)
    if key_modules:
        return [f"{module} -> {_infer_module_responsibility(module)}" for module in key_modules]

    return [
        "main.py -> entry point, API routing, and system orchestration",
        "analyzer.py -> extracts structure, dependencies, and execution logic",
        "orchestrator.py -> coordinates AI reasoning and the analysis pipeline",
        "db.py -> handles persistence and session storage",
        "config.py -> manages system configuration and environment",
        "security.py -> ensures safe input handling and validation",
    ]


def _infer_product_features(result: Dict[str, Any]) -> list[str]:
    features = _clean_list(result.get("core_features", []), limit=8)
    rewritten: list[str] = []
    for feature in features:
        lowered = feature.lower()
        if any(token in lowered for token in ("workflow", "execution")):
            rewritten.append("Automated workflow and execution path detection")
        elif any(token in lowered for token in ("depend", "graph", "relationship")):
            rewritten.append("Dependency graph and module relationship mapping")
        elif any(token in lowered for token in ("summary", "insight", "reason")):
            rewritten.append("AI-powered insight generation for complex systems")
        elif any(token in lowered for token in ("module", "architect", "structure")):
            rewritten.append("Intelligent codebase understanding and architecture extraction")
        elif any(token in lowered for token in ("chat", "assistant", "context")):
            rewritten.append("Context-aware guidance for faster technical decisions")
        else:
            rewritten.append(feature)

    if rewritten:
        return _dedupe(rewritten)[:8]

    return [
        "Intelligent codebase understanding and architecture extraction",
        "Automated workflow and execution path detection",
        "AI-powered insight generation for complex systems",
        "Dependency graph and module relationship mapping",
        "Structured summaries for faster developer decision-making",
    ]


def _infer_overview(result: Dict[str, Any], knowledge_snapshot: Dict[str, Any]) -> str:
    project_goal = _clean_text(result.get("project_goal"))
    validated_behavior = _clean_text(result.get("validated_behavior"))
    purpose = _clean_text(result.get("purpose"))
    project = knowledge_snapshot.get("project") if isinstance(knowledge_snapshot.get("project"), dict) else {}
    fallback = (
        "AHAL AI solves the high cost of understanding unfamiliar codebases by turning raw software structure into decision-ready intelligence. "
        "It combines structural analysis, execution mapping, and AI reasoning to help teams move faster with clearer architectural insight."
    )
    return _short_paragraph(project_goal or validated_behavior or purpose or _clean_text(project.get("summary")), fallback)


def _infer_risks(result: Dict[str, Any]) -> list[str]:
    risks = _clean_list(result.get("risks", []), limit=8)
    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks"), dict) else {}
    issues = _clean_list(summary_blocks.get("issues", []), limit=6)
    merged = _dedupe(risks + issues)
    if merged:
        return merged[:8]
    return [
        "Partial inference can surface when the full repository context is not available during analysis",
        "Deep reasoning quality still depends on AI accuracy and the strength of extracted structural signals",
        "Large repositories may require multi-pass analysis to maintain both speed and insight quality",
    ]


def _infer_future_scope(result: Dict[str, Any]) -> list[str]:
    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks"), dict) else {}
    remaining = _clean_list(summary_blocks.get("remaining", []), limit=8)
    if remaining:
        return remaining
    return [
        "Full-repository deep analysis engine",
        "Real-time dependency graph visualization",
        "Multi-agent reasoning system",
        "Security and vulnerability scanning",
        "IDE integration for live insights",
    ]


def build_project_report(
    result: Dict[str, Any],
    session_type: str = "code",
    knowledge_snapshot: Dict[str, Any] | None = None,
) -> str:
    del session_type
    knowledge_snapshot = knowledge_snapshot or {}
    tech_stack = _infer_tech_stack(result, knowledge_snapshot)
    modules = _infer_core_modules(result, knowledge_snapshot)
    features = _infer_product_features(result)
    overview = _infer_overview(result, knowledge_snapshot)
    risks = _infer_risks(result)
    future_scope = _infer_future_scope(result)
    confidence_reasons = _clean_list(result.get("confidence_reasons", []), limit=3)

    architecture_paragraph = (
        "The platform uses a layered architecture composed of four coordinated stages: Ingestion Layer, Analysis Engine, Intelligence Layer, and Output Layer. "
        "This structure keeps parsing, reasoning, storage, and delivery clearly separated for scale and reliability."
    )

    final_summary = (
        "AHAL AI matters because it transforms raw code into structured intelligence that reduces complexity and speeds up engineering decisions. "
        "Its power comes from combining architectural analysis, execution awareness, and AI reasoning in one scalable platform built for modern software teams."
    )

    key_insight = (
        "This system transforms raw code into structured intelligence, enabling faster engineering decisions and reducing complexity in large-scale software systems."
    )
    if confidence_reasons:
        key_insight += " " + "Strength is reinforced by " + ", ".join(confidence_reasons) + "."

    return "\n".join(
        [
            "# AHAL AI — Intelligent Code Understanding Platform",
            "",
            "### Team Ragnarok",
            "",
            "---",
            "",
            "## [Overview]",
            "",
            overview,
            "",
            "## [Technology Stack]",
            "",
            "**Backend**",
            _render_bullets(tech_stack["backend"]),
            "",
            "**Frontend**",
            _render_bullets(tech_stack["frontend"]),
            "",
            "**Database**",
            _render_bullets(tech_stack["database"]),
            "",
            "**AI Layer**",
            _render_bullets(tech_stack["ai"]),
            "",
            "## [Architecture]",
            "",
            architecture_paragraph,
            "",
            "**System Flow**",
            _render_numbered(
                [
                    "Input ingestion",
                    "Code parsing",
                    "Dependency and workflow mapping",
                    "AI reasoning",
                    "Output generation",
                ]
            ),
            "",
            "## [Core Modules]",
            "",
            _render_bullets(modules),
            "",
            "## [Core Features]",
            "",
            _render_bullets(features),
            "",
            "## [Execution Workflow]",
            "",
            _render_numbered(
                [
                    "User submits code, a folder, or a repository",
                    "The system parses project structure and identifies core modules",
                    "Execution flow and dependencies are mapped into a coherent system view",
                    "The AI engine analyzes behavior, architecture, and product intent",
                    "Insights are generated and returned as structured output",
                ]
            ),
            "",
            "## [Data Flow]",
            "",
            "Input -> Parsing -> Analysis -> AI Reasoning -> Output",
            "",
            "## [Risks & Limitations]",
            "",
            _render_bullets(risks),
            "",
            "## [Improvements & Future Scope]",
            "",
            _render_bullets(future_scope),
            "",
            "## [Final Summary]",
            "",
            final_summary,
            "",
            _render_callout("Key Insight", key_insight),
        ]
    )
