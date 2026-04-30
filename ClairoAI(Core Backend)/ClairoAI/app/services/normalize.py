"""
Output normalization utility.

Normalizes analysis results without inventing missing data.
"""

import re
from typing import Any


_PLACEHOLDER_VALUES = {
    "unknown", "string", "n/a", "none", "null", "undefined",
    "not available", "not specified", "unable to determine",
    "failed to parse",
}
_MAX_PATH_SEGMENTS = 3
_GENERIC_SUMMARY_PHRASES = (
    "structured analysis inferred",
    "inferred from prioritized files",
    "provides source files for project inspection",
    "provides repository files for inspection",
)
_ALLOWED_ARCHITECTURE_PARTS = {"script-based", "component-based", "api-service", "client-server", "monolithic", "static-web", "unknown"}

_FEATURE_GROUP_PATTERNS = [
    (re.compile(r"defines api or web routes in (.+)$", re.IGNORECASE), "api", "REST API for request handling"),
    (re.compile(r"performs file or dataset handling in (.+)$", re.IGNORECASE), "data_io", "File and dataset ingestion"),
    (re.compile(r"implements data or request processing logic in (.+)$", re.IGNORECASE), "processing", "API-driven query handling"),
    (re.compile(r"handles user interaction or presentation logic in (.+)$", re.IGNORECASE), "ui", "Interactive user interface"),
    (re.compile(r"includes retrieval, embedding, or inference-related code in (.+)$", re.IGNORECASE), "ai", "Retrieval or inference workflow"),
    (re.compile(r"defines runtime or dependency setup in (.+)$", re.IGNORECASE), "runtime", "Runtime and dependency configuration"),
]

_RISK_GROUP_PATTERNS = [
    (re.compile(r"limited error handling around external i/o in (.+)$", re.IGNORECASE), "io_error", "External I/O error handling is inconsistent across {sources}"),
    (re.compile(r"incomplete implementation markers remain in (.+)$", re.IGNORECASE), "incomplete", "Incomplete implementation markers remain in {sources}"),
    (re.compile(r"contains environment-specific paths or assumptions in (.+)$", re.IGNORECASE), "env_paths", "Environment-specific paths or assumptions appear across {sources}"),
    (re.compile(r"input validation may be limited in (.+)$", re.IGNORECASE), "validation", "Input validation is inconsistent across {sources}"),
    (re.compile(r"dependency on local models may affect runtime availability in (.+)$", re.IGNORECASE), "local_model", "Local model availability may affect runtime reliability across {sources}"),
    (re.compile(r"sample or test-oriented code may not represent production behavior in (.+)$", re.IGNORECASE), "test_mix", "Test or sample-oriented code may be mixed into analyzed paths: {sources}"),
]


def _clean_str(val: Any, default: str = "") -> str:
    """Coerce value to a clean, trimmed string. Replace placeholders."""
    if val is None:
        return default
    s = str(val).strip()
    if s.lower() in _PLACEHOLDER_VALUES or not s:
        return default
    return s


def _shorten_path(value: str) -> str:
    cleaned = _clean_str(value, "")
    if not cleaned:
        return ""
    normalized = cleaned.replace("\\", "/")
    if "/" not in normalized:
        return cleaned
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return parts[-1] if parts else ""


def _shorten_paths_in_text(value: str) -> str:
    cleaned = _clean_str(value, "")
    if not cleaned:
        return ""

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        shortened = _shorten_path(token)
        return shortened or token

    path_like = re.compile(r"[A-Za-z0-9_.() -]+(?:[\\/][A-Za-z0-9_.() -]+){1,}")
    return path_like.sub(repl, cleaned)


def _clean_summary_text(value: Any) -> str:
    cleaned = _clean_str(value, "")
    lowered = cleaned.lower()
    for phrase in _GENERIC_SUMMARY_PHRASES:
        if phrase in lowered:
            cleaned = ""
            break
    return cleaned


def _normalize_architecture_style(style: Any, goal: Any = "", modules: Any = None) -> str:
    cleaned = _clean_str(style, "")
    lowered = cleaned.lower()
    goal_text = _clean_str(goal, "").lower()
    module_text = " ".join(_clean_list(modules)).lower()
    combined = f"{lowered} {goal_text} {module_text}"

    if cleaned:
        parts = [part.strip() for part in lowered.split("+") if part.strip()]
        if parts and all(part in _ALLOWED_ARCHITECTURE_PARTS for part in parts):
            return " + ".join(parts)

    has_api = any(token in combined for token in ("fastapi", "flask", "django", "express", "api", "router", "route"))
    has_component = any(token in combined for token in ("react", "next", "component", ".tsx", ".jsx", "page.tsx", "layout.tsx"))
    has_client = any(token in combined for token in ("client", "frontend", "browser", "page.tsx", "layout.tsx"))
    has_static_web = any(token in combined for token in ("index.html", ".html", ".css", "static"))
    has_script = any(token in combined for token in ("script", "if __name__", ".sh"))

    if has_api and has_component:
        return "client-server + component-based"
    if has_api and has_client:
        return "client-server"
    if has_api:
        return "api-service"
    if has_component:
        return "component-based"
    if "monolith" in combined or "monolithic" in combined:
        return "monolithic"
    if has_static_web:
        return "static-web"
    if has_script:
        return "script-based"
    return "unknown"


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
                result.append(_shorten_paths_in_text(cleaned))
        return result
    return []


def _clean_insights(val: Any) -> list[dict[str, str]]:
    """Coerce value to a clean List[dict[str, str]] for insights."""
    if val is None:
        return []
    allowed_types = {"architecture", "performance", "scalability", "risk", "dx"}
    cleaned: list[dict[str, str]] = []
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                insight = _clean_str(item.get("insight"), "")
                impact = _clean_str(item.get("impact"), "")
                source = _shorten_path(_clean_str(item.get("source"), ""))
                insight_type = _clean_str(item.get("type"), "").lower()
                if insight_type == "developer_experience":
                    insight_type = "dx"
                if not insight or not impact or not source:
                    continue
                if impact.lower().startswith("source:"):
                    continue
                cleaned.append({
                    "insight": insight,
                    "impact": impact,
                    "source": source,
                    "type": insight_type if insight_type in allowed_types else "architecture",
                })
    return cleaned


def _clean_workflow_steps(val: Any) -> list[str]:
    """Coerce workflow stage content to a clean List[str]."""
    return _clean_list(val)


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_str(value, "")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _first_sentence(value: str) -> str:
    cleaned = _clean_str(value, "")
    if not cleaned:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", cleaned)
    return match.group(1).strip() if match else cleaned


def _strip_forbidden_ai_claims(items: list[str], evidence_text: str = "") -> list[str]:
    evidence = evidence_text.lower()
    has_ai_evidence = any(
        token in evidence
        for token in ("model", "generate_content", "embedding", "vector", "ollama", "gemini", "inference")
    )
    if has_ai_evidence:
        return items
    forbidden = ("ai", "rag", "llm", "embedding", "inference", "model")
    return [item for item in items if not any(token in item.lower() for token in forbidden)]


def _join_sources(sources: list[str]) -> str:
    cleaned = _dedupe_preserve([_shorten_path(source) for source in sources])
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _compact_statement_groups(items: list[str], patterns: list[tuple[re.Pattern[str], str, str]], limit: int) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    passthrough: list[str] = []

    for item in _dedupe_preserve(items):
        matched = False
        for pattern, group_key, template in patterns:
            match = pattern.match(item)
            if not match:
                continue
            matched = True
            group = grouped.setdefault(group_key, {"template": template, "sources": []})
            source = _clean_str(match.group(1), "")
            if source:
                group["sources"].append(source)
            break
        if not matched:
            passthrough.append(item)

    compressed: list[str] = []
    for payload in grouped.values():
        sources = _join_sources(payload.get("sources", []))
        if not sources:
            continue
        compressed.append(str(payload["template"]).format(sources=sources))

    return _dedupe_preserve(compressed + passthrough)[:limit]


def _compact_insights(val: Any, limit: int = 6) -> list[dict[str, str]]:
    insights = _clean_insights(val)
    grouped: dict[str, dict[str, Any]] = {}

    for item in insights:
        insight = _clean_str(item.get("insight"), "")
        impact = _clean_str(item.get("impact"), "")
        source = _clean_str(item.get("source"), "")
        if not insight:
            continue
        key = insight.lower()
        insight_type = _clean_str(item.get("type"), "architecture")
        payload = grouped.setdefault(key, {"insight": insight, "impacts": [], "sources": [], "types": []})
        if impact:
            payload["impacts"].append(impact)
        if source:
            payload["sources"].append(source)
        if insight_type:
            payload["types"].append(insight_type)

    result: list[dict[str, str]] = []
    for payload in grouped.values():
        sources = _join_sources(payload.get("sources", []))
        impacts = _dedupe_preserve(payload.get("impacts", []))
        combined_impact = impacts[0] if impacts else ""
        if len(impacts) > 1 and not combined_impact:
            combined_impact = f"Observed across {sources}" if sources else ""
        elif len(impacts) > 1 and sources:
            combined_impact = f"{combined_impact} Observed across {sources}."
        elif not combined_impact and sources:
            combined_impact = f"Observed across {sources}"
        item = {
            "insight": str(payload["insight"]),
            "impact": combined_impact,
            "type": _dedupe_preserve(payload.get("types", []))[0] if payload.get("types") else "architecture",
        }
        if sources:
            item["source"] = sources
        result.append(item)

    return result[:limit]


def compact_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}

    compacted = dict(result)
    compacted["core_features"] = _compact_statement_groups(
        _clean_list(result.get("core_features")),
        _FEATURE_GROUP_PATTERNS,
        limit=5,
    )
    compacted["risks"] = _compact_statement_groups(
        _clean_list(result.get("risks")),
        _RISK_GROUP_PATTERNS,
        limit=3,
    )
    compacted["insights"] = _compact_insights(result.get("insights"), limit=6)
    compacted["key_modules"] = _dedupe_preserve(_clean_list(result.get("key_modules")))[:8]

    blocks = compacted.get("summary_blocks")
    if not isinstance(blocks, dict):
        blocks = {}
    blocks["issues"] = _compact_statement_groups(
        _clean_list(blocks.get("issues")),
        _RISK_GROUP_PATTERNS,
        limit=3,
    )
    blocks["remaining"] = _dedupe_preserve(_clean_list(blocks.get("remaining")))[:4]
    compacted["summary_blocks"] = blocks
    summary = compacted.get("summary") if isinstance(compacted.get("summary"), dict) else {}
    summary["issues"] = list(compacted["risks"])
    if compacted.get("project_goal"):
        summary["what"] = str(compacted["project_goal"])
    compacted["summary"] = summary
    return compacted


def _clean_system_workflow(val: Any) -> dict[str, list[str]]:
    """Normalize structured workflow fields into list-based stages."""
    workflow = val if isinstance(val, dict) else {}
    return {
        "initialization": _clean_workflow_steps(workflow.get("initialization")),
        "request_flow": _clean_workflow_steps(workflow.get("request_flow")),
        "processing_flow": _clean_workflow_steps(workflow.get("processing_flow")),
        "response_flow": _clean_workflow_steps(workflow.get("response_flow")),
    }


def _workflow_stage_to_text(val: Any, fallback: str = "unknown") -> str:
    if isinstance(val, list):
        cleaned = _dedupe_preserve(_clean_list(val))
        return "; ".join(cleaned) if cleaned else fallback
    cleaned = _clean_str(val, "")
    return cleaned or fallback


def _build_contract_workflow(workflow: Any) -> dict[str, str]:
    workflow_dict = workflow if isinstance(workflow, dict) else {}
    return {
        "initialization": _workflow_stage_to_text(workflow_dict.get("initialization")),
        "data_flow": _workflow_stage_to_text(workflow_dict.get("data_flow") or workflow_dict.get("request_flow")),
        "processing": _workflow_stage_to_text(workflow_dict.get("processing") or workflow_dict.get("processing_flow")),
        "output": _workflow_stage_to_text(workflow_dict.get("output") or workflow_dict.get("response_flow")),
    }


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

    blocks = result.get("summary_blocks")
    summary = result.get("summary")
    if not isinstance(blocks, dict):
        blocks = {}
    if isinstance(summary, dict):
        if not blocks.get("what"):
            blocks["what"] = summary.get("what")
        if not blocks.get("why"):
            blocks["why"] = summary.get("why")
        if not blocks.get("issues"):
            blocks["issues"] = summary.get("issues")

    raw_what = _clean_summary_text(blocks.get("what"))
    raw_why = _clean_summary_text(blocks.get("why"))

    # Top-level string fields
    result["project_goal"] = raw_what or _clean_str(result.get("project_goal"), "")
    result["architecture_style"] = _normalize_architecture_style(
        result.get("architecture_style"),
        raw_what or result.get("project_goal"),
        result.get("key_modules"),
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
    evidence_text = " ".join(_clean_list(result.get("key_modules")) + _clean_list(result.get("core_features")))
    result["key_modules"] = [_shorten_path(item) for item in _clean_list(result.get("key_modules"))]
    result["core_features"] = _strip_forbidden_ai_claims(_clean_list(result.get("core_features")), evidence_text)
    result["risks"] = _clean_list(result.get("risks"))
    result["insights"] = _clean_insights(result.get("insights"))
    result["confidence_reasons"] = _clean_list(result.get("confidence_reasons"))
    try:
        result["confidence_score"] = max(0, min(int(result.get("confidence_score", 0) or 0), 100))
    except (TypeError, ValueError):
        result["confidence_score"] = 0

    workflows = result.get("workflows")
    result["workflows"] = workflows if isinstance(workflows, list) else []
    result["system_workflow"] = _clean_system_workflow(result.get("system_workflow"))
    dependency_graph = result.get("dependency_graph")
    result["dependency_graph"] = dependency_graph if isinstance(dependency_graph, dict) else {}

    # Summary blocks
    blocks["what"] = raw_what
    blocks["why"] = raw_why
    blocks["remaining"] = _clean_list(blocks.get("remaining"))
    blocks["issues"] = _clean_list(blocks.get("issues"))

    if not blocks["what"]:
        blocks["what"] = result["project_goal"] or "Insufficient evidence"
    if not blocks["why"]:
        blocks["why"] = "Insufficient evidence"

    # Strict output contract: LLM semantic summary is the source of truth when present.
    if blocks["what"]:
        result["project_goal"] = _first_sentence(blocks["what"])
    if "ai-powered" in str(result["project_goal"]).lower():
        raise Exception("GENERIC_OUTPUT_BLOCKED")

    result["summary_blocks"] = blocks
    result["summary"] = {
        "what": result["project_goal"],
        "why": blocks["why"],
        "issues": result["risks"],
    }
    result["system_workflow"] = _build_contract_workflow(result.get("system_workflow"))

    return compact_result(result)
