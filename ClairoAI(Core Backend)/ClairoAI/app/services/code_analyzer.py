"""
Code analysis service.

Uses a two-phase pipeline:
1. Static extraction for structure and prompt compression
2. LLM enhancement with full, fast, and partial recovery paths
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from hashlib import sha256
from typing import Any, Dict

from app.core.logging import get_logger
from app.services.analysis_service import (
    correct_invalid_analysis_output,
    enforce_truth,
    find_analysis_validation_errors,
    is_bad_output,
    safe_fallback,
)
from app.services.llm_handler import call_llm_async
from app.services.normalize import normalize_result
from app.services.task_router import TaskType, validate_analysis_output
from app.utils.normalize import normalize_analysis_output

logger = get_logger("services.code_analyzer")

_CODE_ANALYSIS_TIMEOUT_SECONDS = 90
_CODE_FAST_TIMEOUT_SECONDS = 45
_CODE_PARTIAL_TIMEOUT_SECONDS = 12
_HARD_ANALYSIS_TIMEOUT_SECONDS = 20
_HARD_LLM_TIMEOUT_SECONDS = 15
_CODE_CACHE_TTL_SECONDS = 600
_MAX_CODE_LENGTH = 8000
_SNIPPET_MAX_LINES = 200
_CODE_ANALYSIS_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}

_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))",
    re.MULTILINE,
)
_DECORATOR_RE = re.compile(r"@(\w+(?:\.\w+)*)", re.MULTILINE)
_JAVA_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?[A-Za-z0-9_<>\[\]]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_JS_FUNCTION_RE = re.compile(
    r"^\s*(?:function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(|(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_][A-Za-z0-9_]*)\s*=>)",
    re.MULTILINE,
)
_EXTENDS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\s+extends\s+([A-Za-z_][A-Za-z0-9_\.]*)")
_VAGUE_TERMS = ("likely", "appears", "suggests", "probably")


def minimal_safe_response() -> Dict[str, Any]:
    risks = ["Analysis incomplete due to timeout or parsing limits"]
    return {
        "project_goal": "Unable to fully analyze project, partial structure detected",
        "architecture_style": "unknown",
        "key_modules": [],
        "core_features": [],
        "risks": risks,
        "summary": {
            "what": "Partial project analysis",
            "why": "System fallback to prevent blocking",
            "issues": list(risks),
        },
        "summary_blocks": {
            "what": "Partial project analysis",
            "why": "System fallback to prevent blocking",
            "remaining": [],
            "issues": list(risks),
        },
    }


async def with_timeout(coro, timeout: int | float = _HARD_ANALYSIS_TIMEOUT_SECONDS, fallback: Any | None = None):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timeout in code analysis")
        return fallback if fallback is not None else minimal_safe_response()
    except Exception as exc:
        logger.warning("Code analysis step failed", extra={"extra_data": {"error": str(exc)}})
        return fallback if fallback is not None else minimal_safe_response()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _contains_vague_language(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in _VAGUE_TERMS)


def _format_grounded_steps(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    steps: list[str] = []
    for item in value:
        if isinstance(item, dict):
            detail = _clean_text(item.get("step") or item.get("detail") or item.get("action"))
            source = _clean_text(item.get("source"))
            if detail and source and not _contains_vague_language(detail):
                steps.append(f"{detail} [{source}]")
    return _dedupe(steps)


def _coerce_grounded_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    key_modules_raw = parsed.get("key_modules", [])
    feature_raw = parsed.get("core_features", [])
    risk_raw = parsed.get("risks", [])
    dependency_raw = parsed.get("dependency_graph", [])
    insights_raw = parsed.get("insights", [])
    workflow_raw = parsed.get("system_workflow", {})

    key_modules: list[str] = []
    module_details: list[dict[str, str]] = []
    if isinstance(key_modules_raw, list):
        for item in key_modules_raw:
            if isinstance(item, dict):
                name = _clean_text(item.get("name"))
                role = _clean_text(item.get("role"))
                source = _clean_text(item.get("source"))
                if name and role and source and not _contains_vague_language(role):
                    key_modules.append(name)
                    module_details.append({"name": name, "role": role, "source": source})

    core_features: list[str] = []
    feature_details: list[dict[str, str]] = []
    if isinstance(feature_raw, list):
        for item in feature_raw:
            if isinstance(item, dict):
                feature = _clean_text(item.get("feature"))
                evidence = _clean_text(item.get("source") or item.get("evidence"))
                if feature and evidence and not _contains_vague_language(feature):
                    core_features.append(feature)
                    feature_details.append({"feature": feature, "evidence": evidence, "source": evidence})

    risks: list[str] = []
    risk_details: list[dict[str, str]] = []
    if isinstance(risk_raw, list):
        for item in risk_raw:
            if isinstance(item, dict):
                risk = _clean_text(item.get("risk"))
                source = _clean_text(item.get("source"))
                if risk and source and not _contains_vague_language(risk):
                    risks.append(risk)
                    risk_details.append({"risk": risk, "source": source})

    edges: list[dict[str, str]] = []
    if isinstance(dependency_raw, list):
        for item in dependency_raw:
            if not isinstance(item, dict):
                continue
            source = _clean_text(item.get("from"))
            target = _clean_text(item.get("to"))
            relation = _clean_text(item.get("type")) or "import"
            if source and target:
                edges.append({"source": source, "target": target, "relation": relation})

    insights: list[dict[str, str]] = []
    if isinstance(insights_raw, list):
        for item in insights_raw:
            if not isinstance(item, dict):
                continue
            insight = _clean_text(item.get("insight"))
            source = _clean_text(item.get("source"))
            impact = _clean_text(item.get("impact"))
            insight_type = _clean_text(item.get("type")).lower() or "architecture"
            if insight_type == "developer_experience":
                insight_type = "dx"
            if insight and source and impact and not _contains_vague_language(insight):
                insights.append({"insight": insight, "impact": impact, "source": source, "type": insight_type})

    workflow = workflow_raw if isinstance(workflow_raw, dict) else {}
    system_workflow = {
        "initialization": _format_grounded_steps(workflow.get("initialization", [])),
        "request_flow": _format_grounded_steps(workflow.get("request_flow", [])),
        "processing_flow": _format_grounded_steps(workflow.get("processing_flow", [])),
        "response_flow": _format_grounded_steps(workflow.get("response_flow", [])),
    }

    parsed["key_modules"] = _dedupe(key_modules)
    parsed["core_features"] = _dedupe(core_features)
    parsed["risks"] = _dedupe(risks)
    parsed["key_module_details"] = module_details
    parsed["feature_details"] = feature_details
    parsed["risk_details"] = risk_details
    parsed["insights"] = insights
    parsed["system_workflow"] = system_workflow
    parsed["dependency_graph"] = {"edges": edges} if edges else {}
    return parsed


def _detect_language(code: str) -> str:
    if re.search(r"^\s*def\s+|^\s*import\s+|^\s*from\s+\w+\s+import", code, re.MULTILINE):
        return "Python"
    if re.search(r"\bclass\s+\w+\s+extends\s+\w+|\bpackage\s+\w+|public\s+class\s+", code):
        return "Java"
    if re.search(r"\b(const|let|var|function)\b.*[=({]", code):
        if re.search(r":\s*(string|number|boolean|interface|type)\b", code):
            return "TypeScript"
        return "JavaScript"
    return ""


def _detect_pattern(code: str, functions: list[str], classes: list[str], imports: list[str]) -> str:
    code_lower = code.lower()
    if "fastapi" in code_lower or "@app.get" in code_lower or "@app.post" in code_lower:
        return "FastAPI endpoint"
    if "flask" in code_lower or "@app.route" in code_lower:
        return "Flask endpoint"
    if "express" in code_lower or "app.listen" in code_lower:
        return "Express.js server"
    if "react" in code_lower or "usestate" in code_lower or "jsx" in code_lower:
        return "React component"
    if "django" in code_lower:
        return "Django view"
    if classes and not functions:
        return "Class definition"
    if functions and not classes:
        return "Single function" if len(functions) == 1 else "Function library"
    if classes and functions:
        return "Class-based module"
    if imports:
        return "Imported module"
    if "if __name__" in code:
        return "Executable script"
    return "Utility script"


def _extract_methods(code: str, language: str) -> list[str]:
    if language == "Java":
        return _dedupe(_JAVA_METHOD_RE.findall(code))[:10]
    if language in {"JavaScript", "TypeScript"}:
        matches = _JS_FUNCTION_RE.findall(code)
        return _dedupe([left or right for left, right in matches if (left or right)])[:10]
    return []


def _count_non_empty_lines(code: str) -> int:
    return sum(1 for line in code.splitlines() if line.strip())


def _is_snippet_mode(code: str, static: Dict[str, Any]) -> bool:
    return _count_non_empty_lines(code) < _SNIPPET_MAX_LINES or (
        len(static.get("classes", [])) + len(static.get("functions", [])) <= 4
    )


def _extract_static_info(code: str) -> Dict[str, Any]:
    functions = _dedupe(_FUNCTION_RE.findall(code))
    classes = _dedupe(_CLASS_RE.findall(code))
    imports = _dedupe([m[0] or m[1] for m in _IMPORT_RE.findall(code)])
    decorators = _dedupe(_DECORATOR_RE.findall(code))
    language = _detect_language(code)
    methods = _extract_methods(code, language)
    extends = [{"class": left, "base": right} for left, right in _EXTENDS_RE.findall(code)]
    pattern = _detect_pattern(code, functions, classes, imports)
    return {
        "functions": functions[:10],
        "classes": classes[:10],
        "methods": methods[:10],
        "imports": imports[:10],
        "decorators": decorators[:10],
        "extends": extends[:6],
        "line_count": _count_non_empty_lines(code),
        "language": language,
        "pattern": pattern,
    }


def _truncate_code(code: str) -> str:
    if len(code) <= _MAX_CODE_LENGTH:
        return code
    half = _MAX_CODE_LENGTH // 2
    return code[:half] + "\n...(truncated)...\n" + code[-half:]


def _build_code_snapshot(code: str, static: Dict[str, Any]) -> str:
    # Deterministic Stage 3 Intelligence
    scores = calculate_project_scores([{"path": "input_code", "content": code}])
    
    parts = [
        f"Language: {static.get('language', 'unknown')}",
        f"Pattern: {static.get('pattern', 'unknown')}",
        f"Signals: {json.dumps(scores)}",
        f"Functions: {', '.join(static.get('functions', [])[:6]) or '(none)'}",
        f"Classes: {', '.join(static.get('classes', [])[:6]) or '(none)'}",
        f"Methods: {', '.join(static.get('methods', [])[:6]) or '(none)'}",
        f"Imports: {', '.join(static.get('imports', [])[:6]) or '(none)'}",
        f"Code Context (First 3000 chars):",
        code[:3000]
    ]
    return "\n".join(parts)


def _label_confidence(text: str, confidence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    prefix = f"[{confidence} confidence] "
    return cleaned if cleaned.startswith(prefix) else prefix + cleaned


def _cache_get(cache_key: str) -> Dict[str, Any] | None:
    cached = _CODE_ANALYSIS_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _CODE_ANALYSIS_CACHE.pop(cache_key, None)
        return None
    return dict(payload)


def _cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    _CODE_ANALYSIS_CACHE[cache_key] = (time.time() + _CODE_CACHE_TTL_SECONDS, dict(payload))


def _merge_result(base: Dict[str, Any], update: Dict[str, Any] | None) -> Dict[str, Any]:
    if not update:
        return base
    for field in ("project_goal", "architecture_style"):
        value = str(update.get(field, "")).strip()
        if value:
            base[field] = value
    for field in ("key_modules", "core_features", "risks"):
        values = _dedupe([str(item) for item in update.get(field, []) if str(item).strip()])
        if values:
            current = _dedupe([str(item) for item in base.get(field, []) if str(item).strip()])
            base[field] = _dedupe(current + values)

    base_blocks = base.setdefault("summary_blocks", {})
    update_blocks = update.get("summary_blocks", {})
    if isinstance(update_blocks, dict):
        for field in ("what", "why"):
            value = str(update_blocks.get(field, "")).strip()
            if value:
                base_blocks[field] = value
        for field in ("remaining", "issues"):
            values = _dedupe([str(item) for item in update_blocks.get(field, []) if str(item).strip()])
            if values:
                current = _dedupe([str(item) for item in base_blocks.get(field, []) if str(item).strip()])
                base_blocks[field] = _dedupe(current + values)
    base["summary_blocks"] = base_blocks
    return base


def _internal_input_detected(code: str) -> bool:
    lowered = code.lower()
    return "base_prompt" in lowered or "prompt =" in lowered


def _invalid_input_response() -> Dict[str, Any]:
    return {
        "project_goal": "Invalid input - system prompt detected",
        "architecture_style": "",
        "key_modules": [],
        "core_features": ["Internal system code detected"],
        "risks": ["Wrong input passed to analyzer"],
        "summary_blocks": {
            "what": "System prompt detected instead of user code",
            "why": "Pipeline error - internal prompt leaked as input",
            "remaining": ["Re-submit actual code for analysis"],
            "issues": ["Input validation bypass"],
        },
    }


def _empty_code_result(static: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "project_goal": "",
        "architecture_style": "",
        "key_modules": [],
        "core_features": [],
        "risks": [],
        "summary_blocks": {
            "what": "",
            "why": "",
            "remaining": [],
            "issues": [],
        },
    }


def _describe_snippet_goal(static: Dict[str, Any]) -> str:
    language = static.get("language") or "code"
    classes = static.get("classes", [])
    functions = static.get("functions", [])
    methods = static.get("methods", [])
    extends = static.get("extends", [])
    pattern = static.get("pattern", "")

    if extends:
        head = extends[0]
        return f"Implements {head['class']} as a custom {language} component extending {head['base']}."
    if classes and methods:
        return f"Defines {classes[0]} with method-level behavior in a focused {language} snippet."
    if classes:
        return f"Defines {classes[0]} as a reusable {language} class."
    if functions:
        return f"Implements {functions[0]} as a focused {language} function."
    if pattern:
        return f"Implements a {pattern.lower()} in isolated {language} code."
    return f"Provides an isolated {language} code snippet for local analysis."


def _build_snippet_features(static: Dict[str, Any]) -> list[str]:
    features: list[str] = []
    for relation in static.get("extends", []):
        features.append(f"Defines subclass {relation['class']} extending {relation['base']}")
    for class_name in static.get("classes", [])[:2]:
        features.append(f"Defines class {class_name}")
    for function_name in static.get("functions", [])[:3]:
        features.append(f"Implements function {function_name}")
    for method_name in static.get("methods", [])[:3]:
        features.append(f"Includes method {method_name}")
    if static.get("imports"):
        features.append(f"Depends on imported modules such as {', '.join(static.get('imports', [])[:3])}")
    pattern = static.get("pattern", "")
    if pattern and pattern not in {"Class definition", "Single function", "Function library", "Class-based module"}:
        features.append(f"Uses a {pattern.lower()} structure")
    return _dedupe(features)[:6]


def _build_snippet_risks(code: str, static: Dict[str, Any]) -> list[str]:
    risks: list[str] = []
    lowered = code.lower()
    if static.get("functions") and "try:" not in lowered and "catch" not in lowered:
        risks.append("No visible error handling around core logic")
    if any(token in lowered for token in ("input(", "request", "args[", "argv", "params", "body")) and "validate" not in lowered:
        risks.append("Input validation is not visible in this snippet")
    if "todo" in lowered or "pass" in lowered or "throw new unsupportedoperationexception" in lowered:
        risks.append("Implementation appears incomplete in at least one path")
    if static.get("classes") and not static.get("methods") and not static.get("functions"):
        risks.append("Class structure is visible, but operational behavior is minimal in this snippet")
    if not risks:
        risks.append("Snippet-level analysis may miss integration constraints outside this file")
    return _dedupe(risks)[:4]


def _build_snippet_result(code: str, static: Dict[str, Any]) -> Dict[str, Any]:
    key_elements = _dedupe(
        [*static.get("classes", []), *static.get("functions", []), *static.get("methods", [])]
    )[:8]
    features = _build_snippet_features(static)
    risks = _build_snippet_risks(code, static)
    project_goal = _describe_snippet_goal(static)
    summary_what = project_goal
    summary_why = "Summarized in snippet mode from visible classes, functions, methods, and inheritance."
    return {
        "project_goal": project_goal,
        "architecture_style": "script-based",
        "key_modules": key_elements,
        "core_features": features,
        "risks": risks,
        "summary_blocks": {
            "what": summary_what,
            "why": summary_why,
            "remaining": ["Broader project context is not included in this snippet"],
            "issues": risks[:2],
        },
    }


CODE_PROMPT = """You are a senior software architect.
Perform a deterministic synthesis of the provided code snapshot.

CORE RULES:
- ONLY report features, modules, or risks that are explicitly present in the provided snapshot, signals, or scores.
- If evidence is missing for a field, return "Insufficient information to determine [field]".
- DO NOT hallucinate or use generic marketing language.
- Mention a technology ONLY if it is explicitly visible in imports, dependencies, or code text.
- Call it an AI or ML system ONLY if libraries such as transformers, torch, tensorflow, openai, gemini, or explicit model inference code are present.

Clearly answer:
1. What exact problem does this code solve?
2. What kind of component or system is it?
3. What is the main workflow?

Think step-by-step before answering:
- Identify domain
- Identify core functionality
- Identify user
- Then generate the final answer

Use this compact code snapshot to produce:
- project_goal
- architecture_style
- key_modules
- core_features
- risks
- summary.what
- summary.why
- summary.issues
- system_workflow
- 3 grounded technical insights only when there is enough evidence

Classification rules:
- Mention a technology only if it is explicitly visible in imports, dependencies, or code text.
- Call it an AI or ML system only if libraries such as transformers, torch, tensorflow, openai, gemini, or explicit model inference code are present.
- If visible UI text, filenames, dataset names, or function names contain biology, bio, learning, student, quiz, course, or education terms, classify the product as an Educational Platform (Biology-focused).
- Do not mention RAG, retrieval, embeddings, inference, or AI unless embeddings code, vector storage, model loading, or inference calls are explicitly visible.
- You may infer a higher-level product purpose only when at least two signal categories agree: meaningful AI-oriented filenames, AI dependencies, or inference/retrieval code patterns.
- Choose architecture_style only from script-based / component-based / api-service / client-server / monolithic / static-web; combine only when evidence clearly shows multiple layers such as client-server + component-based.
- If the code purpose is unclear, use project_goal = "Insufficient evidence to determine project goal".
- If evidence is too weak, return the minimal safe structure with empty arrays and "unknown" workflow fields rather than guessing.

Output must be 2-3 lines maximum with high information density.
Do not repeat classes, functions, methods, or risks already detected structurally.
For single-file input, use architecture_style = script-based unless the code clearly shows a component-based structure.
Each insight must use this exact structure:
- insight: specific technical observation grounded in the snapshot
- source: real module or input_code
- impact: why it matters in real-world usage
- type: architecture | performance | scalability | risk | dx
If evidence is insufficient, return "insights": [].

CODE SNAPSHOT:
Language: {language}
Pattern: {pattern}
Functions: {functions}
Classes: {classes}
Methods: {methods}
Imports: {imports}
Code:
{code}

OUTPUT:
{{
  "project_goal": "",
  "architecture_style": "",
  "key_modules": [],
  "core_features": [],
  "insights": [
    {{"insight": "", "source": "input_code", "impact": "", "type": "architecture"}}
  ],
  "risks": [],
  "summary": {{
    "what": "",
    "why": "",
    "issues": []
  }},
  "system_workflow": {{
    "initialization": "",
    "data_flow": "",
    "processing": "",
    "output": ""
  }}
}}
"""

SNIPPET_PROMPT = """You are a senior software architect working in snippet analysis mode.

Perform a deterministic synthesis of the provided code snippet.

CORE RULES:
- ONLY report what is explicitly visible in this code snippet.
- If evidence is missing for a field, return "Insufficient information".
- DO NOT hallucinate or assume external project context.
- Mention a technology ONLY if it is explicitly visible.
- Call it an AI or ML system ONLY if libraries such as transformers, torch, tensorflow, openai, gemini, or explicit model inference code are present.

SNIPPET STRUCTURE:
- Language: {language}
- Pattern: {pattern}
- Functions: {functions}
- Classes: {classes}
- Methods: {methods}
- Imports: {imports}

CODE:
{code}

OUTPUT (JSON only - no markdown, no explanation):
{{
  "project_goal": "what this snippet implements in isolation",
  "architecture_style": "script-based",
  "key_modules": [],
  "core_features": [],
  "insights": [
    {{
      "insight": "useful grounded snippet-level insight",
      "source": "input_code",
      "impact": "why this matters in real-world usage",
      "type": "architecture"
    }}
  ],
  "risks": [],
  "summary": {{
    "what": "what the code does in isolation",
    "why": "why this snippet exists based on visible structure",
    "issues": []
  }},
  "system_workflow": {{
    "initialization": "unknown",
    "data_flow": "unknown",
    "processing": "unknown",
    "output": "unknown"
  }}
}}

RULES:
- treat this as a snippet, not a whole repository
- use the provided structure instead of re-listing classes or methods
- avoid vague marketing wording or generic product labels
- do not invent external project context
- if visible UI text, filenames, dataset names, or function names contain biology, bio, learning, student, quiz, course, or education terms, classify the product as an Educational Platform (Biology-focused)
- do not mention RAG, retrieval, embeddings, inference, or AI unless embeddings code, vector storage, model loading, or inference calls are explicitly visible
- choose architecture_style only from script-based / component-based / api-service / client-server / monolithic / static-web; combine only when evidence clearly shows multiple layers such as client-server + component-based
- if the snippet purpose is unclear, use project_goal = "Insufficient evidence to determine project goal"
- if evidence is too weak, return the minimal safe structure with empty arrays and "unknown" workflow fields rather than guessing
- return 3-4 specific technical insights only when the snippet supports them; otherwise return "insights": []
- return JSON ONLY"""

CODE_FAST_PROMPT = """Analyze this code snapshot and return ONLY valid JSON.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what this code does",
  "architecture_style": "explicit framework or empty string",
  "key_modules": [],
  "core_features": [],
  "risks": [],
  "system_workflow": {{
    "initialization": [],
    "request_flow": [],
    "processing_flow": [],
    "response_flow": []
  }},
  "dependency_graph": [],
  "insights": [],
  "summary_blocks": {{
    "what": "clear explanation of the code",
    "why": "",
    "remaining": [],
    "issues": []
  }}
}}

RULES:
- no vague words
- leave unsupported sections empty
- use source value input_code for every non-empty item
- return JSON ONLY."""

CODE_GOAL_PROMPT = """Return ONLY valid JSON for the goal and core features of this code.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what this code does",
  "core_features": []
}}"""

CODE_ARCH_PROMPT = """Return ONLY valid JSON for the architecture and key modules of this code.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "architecture_style": "explicit framework or empty string",
  "key_modules": [],
  "summary_blocks": {{
    "what": "",
    "why": ""
  }}
}}"""

CODE_RISK_PROMPT = """Return ONLY valid JSON for the risks and next steps of this code.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "risks": [],
  "summary_blocks": {{
    "remaining": [],
    "issues": []
  }}
}}"""


async def _call_code_llm(prompt: str, timeout: int, mode: str, label: str) -> Dict[str, Any] | None:
    try:
        started = time.monotonic()
        parsed = await with_timeout(
            call_llm_async(
                prompt,
                timeout=min(timeout, _HARD_LLM_TIMEOUT_SECONDS),
                simplified_prompt=prompt,
                mode=mode,
            ),
            timeout=_HARD_LLM_TIMEOUT_SECONDS,
            fallback=None,
        )
        if not isinstance(parsed, dict):
            return None
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        logger.info(
            "Code LLM call succeeded",
            extra={"extra_data": {"label": label, "latency_ms": latency_ms}},
        )
        return parsed
    except Exception as exc:
        logger.warning(f"Code {label} LLM failure: {exc}")
        return None


async def _run_code_llm_enhancement(code: str, static: Dict[str, Any], prompt: str, mode: str) -> Dict[str, Any]:
    cache_key = sha256(f"{mode}|{prompt}".encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        return cached
    snapshot = _build_code_snapshot(code, static)

    full_result = await _call_code_llm(prompt, _HARD_LLM_TIMEOUT_SECONDS, mode, "full")
    if full_result:
        merged = _merge_result(_empty_code_result(static), _coerce_grounded_result(full_result))
        _cache_set(cache_key, merged)
        return merged

    fast_result = await _call_code_llm(CODE_FAST_PROMPT.format(snapshot=snapshot), _HARD_LLM_TIMEOUT_SECONDS, mode, "fast")
    if fast_result:
        merged = _merge_result(_empty_code_result(static), _coerce_grounded_result(fast_result))
        _cache_set(cache_key, merged)
        return merged

    merged = dict(_empty_code_result(static))
    partial_successes = 0
    partial_specs = [
        ("goal", CODE_GOAL_PROMPT.format(snapshot=snapshot)),
        ("architecture", CODE_ARCH_PROMPT.format(snapshot=snapshot)),
        ("risks", CODE_RISK_PROMPT.format(snapshot=snapshot)),
    ]
    partial_results = await asyncio.gather(
        *[_call_code_llm(partial_prompt, _CODE_PARTIAL_TIMEOUT_SECONDS, mode, label) for label, partial_prompt in partial_specs],
        return_exceptions=True,
    )
    for partial in partial_results:
        if isinstance(partial, dict):
            partial_successes += 1
            merged = _merge_result(merged, _coerce_grounded_result(partial))

    if partial_successes > 0:
        _cache_set(cache_key, merged)
        return merged

    return merged


class CodeAnalyzer:
    def build_quick_result(self, code: str) -> Dict[str, Any]:
        static = _extract_static_info(code)
        base = _build_snippet_result(code, static) if _is_snippet_mode(code, static) else _empty_code_result(static)
        base = normalize_analysis_output(normalize_result(base), evidence_text=code)
        return validate_analysis_output(base, TaskType.PROJECT_ANALYSIS)

    async def analyze(self, code: str, mode: str = "offline") -> Dict[str, Any]:
        started_total = time.monotonic()
        try:

            if _internal_input_detected(code):
                logger.warning("Blocked internal prompt-like input from code analysis")
                return normalize_analysis_output(normalize_result(_invalid_input_response()), evidence_text=code)

            static = await asyncio.to_thread(_extract_static_info, code)
            logger.info("Code static extraction complete", extra={"extra_data": {
                "endpoint": "code",
                "language": static["language"],
                "pattern": static["pattern"],
                "functions": len(static["functions"]),
                "classes": len(static["classes"]),
                "imports": len(static["imports"]),
            }})

            truncated_code = await asyncio.to_thread(_truncate_code, code)
            if len(truncated_code) != len(code):
                logger.info(f"Code input truncated from {len(code)} to {len(truncated_code)} chars")

            snippet_mode = await asyncio.to_thread(_is_snippet_mode, code, static)
            prompt_template = SNIPPET_PROMPT if snippet_mode else CODE_PROMPT
            prompt = prompt_template.format(
                language=static["language"],
                pattern=static["pattern"],
                functions=", ".join(static["functions"][:6]) or "(none)",
                classes=", ".join(static["classes"][:6]) or "(none)",
                methods=", ".join(static["methods"][:6]) or "(none)",
                imports=", ".join(static["imports"][:6]) or "(none)",
                code=truncated_code,
            )

            llm_started = time.monotonic()
            parsed = await with_timeout(
                _run_code_llm_enhancement(code=code, static=static, prompt=prompt, mode=mode),
                timeout=_HARD_ANALYSIS_TIMEOUT_SECONDS,
                fallback=_empty_code_result(static),
            )
            if not isinstance(parsed, dict):
                parsed = _empty_code_result(static)
        except Exception as exc:
            logger.warning("Code analysis returned fallback", extra={"extra_data": {"error": str(exc)}})
            return normalize_analysis_output(normalize_result(minimal_safe_response()), evidence_text=str(code or "")[:_MAX_CODE_LENGTH])
        llm_ms = round((time.monotonic() - llm_started) * 1000, 2)
        total_ms = round((time.monotonic() - started_total) * 1000, 2)

        parsed_summary = parsed.get("summary", {}) if isinstance(parsed.get("summary"), dict) else {}
        parsed_blocks = parsed.get("summary_blocks", {}) if isinstance(parsed.get("summary_blocks"), dict) else {}
        is_fallback = str(parsed_blocks.get("why") or parsed_summary.get("why") or "").startswith("[MEDIUM confidence]")
        logger.info("Code analysis complete", extra={"extra_data": {
            "endpoint": "code",
            "mode": mode,
            "llm_time_ms": llm_ms,
            "total_time_ms": total_ms,
            "fallback": is_fallback,
            "context_size": len(prompt),
        }})

        try:
            parsed = _coerce_grounded_result(parsed)
            snippet_fallback = _build_snippet_result(code, static) if snippet_mode else _empty_code_result(static)
            parsed_summary = parsed.get("summary", {}) if isinstance(parsed.get("summary"), dict) else {}
            parsed_blocks = parsed.get("summary_blocks", {}) if isinstance(parsed.get("summary_blocks"), dict) else {}
            result = {
                "project_goal": parsed.get("project_goal", "") or snippet_fallback.get("project_goal", ""),
                "architecture_style": parsed.get("architecture_style", "") or snippet_fallback.get("architecture_style", ""),
                "key_modules": parsed.get("key_modules", []) or snippet_fallback.get("key_modules", []),
                "core_features": parsed.get("core_features", []) or snippet_fallback.get("core_features", []),
                "risks": parsed.get("risks", []) or snippet_fallback.get("risks", []),
                "system_workflow": parsed.get("system_workflow", {}) or snippet_fallback.get("system_workflow", {}),
                "dependency_graph": snippet_fallback.get("dependency_graph", {}),
                "insights": parsed.get("insights", []),
                "summary_blocks": {
                    "what": parsed_blocks.get("what", "") or parsed_summary.get("what", "") or snippet_fallback.get("summary_blocks", {}).get("what", ""),
                    "why": parsed_blocks.get("why", "") or parsed_summary.get("why", "") or snippet_fallback.get("summary_blocks", {}).get("why", ""),
                    "remaining": parsed_blocks.get("remaining", []) or snippet_fallback.get("summary_blocks", {}).get("remaining", []),
                    "issues": parsed_blocks.get("issues", []) or parsed_summary.get("issues", []) or snippet_fallback.get("summary_blocks", {}).get("issues", []),
                },
            }
            validation_errors = find_analysis_validation_errors(truncated_code, result)
            if validation_errors:
                logger.warning("Correcting invalid code analysis output", extra={"extra_data": {"errors": validation_errors}})
                result = correct_invalid_analysis_output(truncated_code, result, validation_errors)
            result = enforce_truth(result)
            if is_bad_output(result):
                result = safe_fallback()

            normalized = normalize_analysis_output(normalize_result(result), evidence_text=truncated_code)
            return validate_analysis_output(normalized, TaskType.PROJECT_ANALYSIS)
        except Exception as exc:
            logger.warning("Code normalization fallback used", extra={"extra_data": {"error": str(exc)}})
            return normalize_analysis_output(normalize_result(minimal_safe_response()), evidence_text=truncated_code)
