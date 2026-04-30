"""
Workflow extraction engine.

Builds execution-flow style workflows from sampled modules, functions, routes,
and lightweight call-chain heuristics.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List

_PY_ROUTE_RE = re.compile(r'@(?:app|router)\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']', re.IGNORECASE)
_FLASK_ROUTE_RE = re.compile(r'@(?:app|bp|blueprint)\.route\(["\']([^"\']+)["\'].*methods\s*=\s*\[([^\]]+)\]', re.IGNORECASE)
_EXPRESS_ROUTE_RE = re.compile(r'(?:app|router)\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']\s*,\s*([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)
_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_JS_FUNCTION_RE = re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(|\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", re.MULTILINE)
_JS_IMPORT_RE = re.compile(r'^\s*import\s+(?:.+?\s+from\s+)?["\']([^"\']+)["\']', re.MULTILINE)
_DATABASE_HINT_RE = re.compile(r"\b(find|find_one|query|execute|select|insert|update|delete|commit|rollback)\b", re.IGNORECASE)
_ENTRYPOINT_HINTS = ("main", "app", "server", "index", "create_app", "bootstrap", "startup")


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


def _extract_functions(content: str) -> List[str]:
    js_names = []
    for first, second in _JS_FUNCTION_RE.findall(content or ""):
        if first:
            js_names.append(first)
        elif second:
            js_names.append(second)
    return _dedupe(list(_FUNCTION_RE.findall(content or "")) + js_names)[:40]


def _extract_imports(content: str) -> List[str]:
    imports = []
    for left, right in _IMPORT_RE.findall(content or ""):
        imports.append(left or right)
    imports.extend(_JS_IMPORT_RE.findall(content or ""))
    return _dedupe(imports)[:20]


def _infer_route_handler(content: str, method: str, route_path: str) -> str:
    lines = (content or "").splitlines()
    pending_match = False
    for line in lines:
        if re.search(rf'@(?:app|router)\.{method.lower()}\(["\']{re.escape(route_path)}["\']', line, re.IGNORECASE):
            pending_match = True
            continue
        if pending_match and "@app" in line:
            pending_match = False
        if pending_match:
            match = re.match(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if match:
                return match.group(1)
    return ""


def _find_function_body(content: str, function_name: str) -> str:
    if not content or not function_name:
        return ""
    lines = content.splitlines()
    body_lines: List[str] = []
    capture = False
    base_indent = 0
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if re.match(rf"^\s*(?:async\s+)?def\s+{re.escape(function_name)}\s*\(", line):
            capture = True
            base_indent = indent
            body_lines.append(line)
            continue
        if capture:
            if stripped and indent <= base_indent and not stripped.startswith((")", "]", "}")):
                break
            body_lines.append(line)
    return "\n".join(body_lines)


def _extract_calls(function_body: str, known_functions: List[str]) -> List[str]:
    candidates = [match for match in _CALL_RE.findall(function_body or "") if match not in {"if", "for", "while", "return", "print"}]
    known = set(known_functions)
    ordered = []
    for candidate in candidates:
        if candidate in known and candidate not in ordered:
            ordered.append(candidate)
        elif candidate.lower().startswith(("get_", "create_", "update_", "delete_", "validate_", "find_", "save_", "load_", "generate_")) and candidate not in ordered:
            ordered.append(candidate)
    return ordered[:6]


def _decorate_call(call_name: str, imports: List[str]) -> str:
    lowered = call_name.lower()
    for imported in imports:
        imported_name = imported.split(".")[-1]
        if imported_name and imported_name.lower().startswith(lowered.split("_")[0]):
            return f"{imported_name}.{call_name}()"
    if "db" in lowered or "repo" in lowered or "model" in lowered:
        return f"{call_name}()"
    return f"{call_name}()"


def _infer_database_step(function_body: str, imports: List[str]) -> str | None:
    lowered = function_body.lower()
    if any(token in lowered for token in ("session.query", "db.", "database.", "cursor.", ".execute(", ".find(", ".save(")):
        return "database query"
    if any("sql" in item.lower() or "db" in item.lower() for item in imports):
        if _DATABASE_HINT_RE.search(function_body):
            return "database query"
    return None


def _infer_initialization_flow(sampled_files: List[Dict[str, str]], known_functions: List[str]) -> Dict[str, Any]:
    prioritized = []
    for file_info in sampled_files:
        path = str(file_info.get("path", "") or "")
        basename = os.path.basename(path).lower()
        if any(hint in basename for hint in _ENTRYPOINT_HINTS):
            prioritized.append(file_info)
    selected = prioritized or sampled_files[:3]

    steps: List[str] = []
    modules: List[str] = []
    for file_info in selected[:3]:
        path = str(file_info.get("path", "") or "")
        content = str(file_info.get("content", "") or "")
        imports = _extract_imports(content)
        functions = _extract_functions(content)
        modules.append(os.path.basename(path) or path)
        steps.append(os.path.basename(path) or path)
        for candidate in functions:
            if any(hint in candidate.lower() for hint in _ENTRYPOINT_HINTS):
                steps.append(f"{candidate}()")
                body = _find_function_body(content, candidate)
                steps.extend(_decorate_call(call, imports) for call in _extract_calls(body, known_functions)[:3])
                break
        if imports:
            steps.append(f"load dependencies: {', '.join(imports[:2])}")

    steps.append("system ready")
    return {
        "name": "Initialization Flow",
        "steps": _dedupe(steps)[:8] or ["load configuration", "initialize application", "system ready"],
        "entry_point": steps[0] if steps else "application startup",
        "modules": _dedupe(modules)[:6],
        "confidence": "medium",
        "confidence_percent": 72,
        "uncertainty_reasons": [
            "Initialization was inferred from entrypoint naming and imported modules",
        ],
        "summary": "Bootstraps the application, loads dependencies, and prepares runtime components.",
    }


def _infer_request_flow(sampled_files: List[Dict[str, str]], workflows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if workflows:
        primary = workflows[0]
        steps = _dedupe(primary.get("steps", []))[:8]
        modules = _dedupe(primary.get("modules", []))[:6]
        return {
            "name": "Request Handling Flow",
            "steps": steps or ["receive request", "route to handler", "return response"],
            "entry_point": primary.get("entry_point", "request handler"),
            "modules": modules,
            "confidence": primary.get("confidence", "medium"),
            "confidence_percent": 84 if len(steps) >= 4 else 70,
            "uncertainty_reasons": [] if len(steps) >= 4 else ["Flow inferred from handlers without full runtime tracing"],
            "summary": "Shows how incoming requests move through handlers, services, and response generation.",
        }

    modules = _dedupe(os.path.basename(str(file_info.get("path", "") or "")) for file_info in sampled_files[:4])
    return {
        "name": "Request Handling Flow",
        "steps": ["receive request", *(modules[:2] or ["dispatch to module"]), "return response"],
        "entry_point": modules[0] if modules else "request entrypoint",
        "modules": modules,
        "confidence": "medium",
        "confidence_percent": 66,
        "uncertainty_reasons": ["No explicit routes were found, so request handling was inferred from module structure"],
        "summary": "Inferred request path based on top modules and function entrypoints.",
    }


def _infer_processing_flow(sampled_files: List[Dict[str, str]], known_functions: List[str]) -> Dict[str, Any]:
    steps: List[str] = []
    modules: List[str] = []
    for file_info in sampled_files[:4]:
        path = str(file_info.get("path", "") or "")
        content = str(file_info.get("content", "") or "")
        imports = _extract_imports(content)
        functions = _extract_functions(content)
        if functions:
            chosen = functions[0]
            body = _find_function_body(content, chosen)
            calls = _extract_calls(body, known_functions)
            modules.append(os.path.basename(path) or path)
            steps.append(f"{chosen}()")
            steps.extend(_decorate_call(call, imports) for call in calls[:3])
            db_step = _infer_database_step(body, imports)
            if db_step:
                steps.append(db_step)
            if len(steps) >= 5:
                break
    steps.append("return processed result")
    return {
        "name": "Data Processing Flow",
        "steps": _dedupe(steps)[:8] or ["validate input", "process data", "return processed result"],
        "entry_point": steps[0] if steps else "processing pipeline",
        "modules": _dedupe(modules)[:6],
        "confidence": "medium",
        "confidence_percent": 74 if len(steps) >= 4 else 61,
        "uncertainty_reasons": [] if len(steps) >= 4 else ["Processing flow inferred from top-level functions instead of explicit pipelines"],
        "summary": "Captures the main processing path from business logic through downstream operations.",
    }


def _infer_response_flow(sampled_files: List[Dict[str, str]], workflows: List[Dict[str, Any]]) -> Dict[str, Any]:
    modules = _dedupe(os.path.basename(str(file_info.get("path", "") or "")) for file_info in sampled_files[:4])
    steps: List[str] = []
    if workflows:
        primary = workflows[0]
        entry_point = str(primary.get("entry_point", "")).strip()
        if entry_point:
            steps.append(entry_point)
        steps.extend(_dedupe(primary.get("steps", []))[-2:])
    steps.extend(["prepare result", "return response"])
    return {
        "name": "Response Flow",
        "steps": _dedupe(steps)[:6] or ["prepare result", "return response"],
        "entry_point": steps[0] if steps else "response handler",
        "modules": modules,
        "confidence": "medium",
        "confidence_percent": 70 if workflows else 62,
        "uncertainty_reasons": [] if workflows else ["Response handling was assembled from workflow termination patterns"],
        "summary": "Shows how processed output is finalized and returned to the caller.",
    }


def _ensure_named_workflows(sampled_files: List[Dict[str, str]], known_functions: List[str], workflows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    named = {str(workflow.get("name", "")).lower(): workflow for workflow in workflows}
    results: List[Dict[str, Any]] = []

    results.append(named.get("initialization flow") or _infer_initialization_flow(sampled_files, known_functions))
    request_flow = next((workflow for workflow in workflows if "request" in str(workflow.get("name", "")).lower()), None)
    results.append(request_flow or _infer_request_flow(sampled_files, workflows))
    processing_flow = next((workflow for workflow in workflows if "processing" in str(workflow.get("name", "")).lower() or "data" in str(workflow.get("name", "")).lower()), None)
    results.append(processing_flow or _infer_processing_flow(sampled_files, known_functions))
    response_flow = next((workflow for workflow in workflows if "response" in str(workflow.get("name", "")).lower()), None)
    results.append(response_flow or _infer_response_flow(sampled_files, workflows))

    for workflow in workflows:
        if workflow not in results:
            results.append(workflow)
    return results[:8]


def _derive_workflow_name(route_path: str, handler_name: str) -> str:
    if route_path and route_path != "/":
        label = route_path.strip("/").replace("-", " ").replace("_", " ")
        if label:
            return label.title()
    if handler_name:
        return handler_name.replace("_", " ").title()
    return "Primary Flow"


def _extract_routes(sampled_files: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    routes: List[Dict[str, Any]] = []
    for file_info in sampled_files:
        path = str(file_info.get("path", ""))
        content = str(file_info.get("content", "") or "")
        for method, route_path in _PY_ROUTE_RE.findall(content):
            routes.append({"method": method.upper(), "path": route_path, "handler": _infer_route_handler(content, method, route_path), "file_path": path})
        for route_path, methods in _FLASK_ROUTE_RE.findall(content):
            primary_method = methods.split(",")[0].strip(" '\"") if methods else "GET"
            routes.append({"method": primary_method.upper(), "path": route_path, "handler": _infer_route_handler(content, primary_method, route_path), "file_path": path})
        for method, route_path, handler in _EXPRESS_ROUTE_RE.findall(content):
            routes.append({"method": method.upper(), "path": route_path, "handler": handler, "file_path": path})
    return routes


def extract_workflows(
    *,
    session_type: str,
    sampled_files: List[Dict[str, str]],
    result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    routes = _extract_routes(sampled_files)
    workflows: List[Dict[str, Any]] = []
    known_functions = _dedupe(
        [name for file_info in sampled_files for name in _extract_functions(str(file_info.get("content", "") or ""))]
        + [str(module) for module in result.get("key_modules", [])]
    )

    for route in routes[:8]:
        path = route.get("path", "")
        handler = route.get("handler", "")
        file_path = route.get("file_path", "")
        file_content = next((str(item.get("content", "") or "") for item in sampled_files if item.get("path") == file_path), "")
        imports = _extract_imports(file_content)
        if not handler:
            possible_handlers = _extract_functions(file_content)
            handler = possible_handlers[0] if possible_handlers else os.path.splitext(os.path.basename(file_path))[0]
        body = _find_function_body(file_content, handler)
        calls = _extract_calls(body, known_functions)
        steps = [f"{route.get('method', 'GET')} {path}", f"{os.path.basename(file_path)}::{handler}"]
        steps.extend(_decorate_call(call, imports) for call in calls)
        database_step = _infer_database_step(body, imports)
        if database_step:
            steps.append(database_step)
        steps.append("return response")
        workflows.append({
            "name": _derive_workflow_name(path, handler),
            "steps": _dedupe(steps),
            "entry_point": f"{route.get('method', 'GET')} {path}",
            "modules": _dedupe([os.path.basename(file_path)] + imports + calls)[:8],
            "confidence": "high" if len(calls) >= 2 else "medium",
            "summary": f"Execution flow beginning at {route.get('method', 'GET')} {path} and handled by {handler}.",
        })

    if not workflows:
        modules = _dedupe(result.get("key_modules", []))[:6]
        features = _dedupe(result.get("core_features", []))[:5]
        workflows.append({
            "name": "Primary System Flow",
            "steps": features or modules or ["Analyze request", "Process module", "Return result"],
            "entry_point": modules[0] if modules else session_type,
            "modules": modules,
            "confidence": "medium",
            "confidence_percent": 58,
            "uncertainty_reasons": ["No explicit routes or call chains were available in sampled files"],
            "summary": str(result.get("project_goal", "")).strip() or "Primary flow inferred from analyzed modules.",
        })

    return _ensure_named_workflows(sampled_files, known_functions, workflows)


def detect_design_patterns(
    *,
    architecture_style: str,
    sampled_files: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    paths = " ".join(str(file_info.get("path", "")).lower() for file_info in sampled_files)
    architecture = architecture_style.lower()
    patterns: List[Dict[str, str]] = []

    if any(token in paths for token in ("controller", "service", "model")):
        patterns.append({"name": "Layered", "confidence": "high"})
    if "mvc" in architecture or all(token in paths for token in ("controller", "model")):
        patterns.append({"name": "MVC", "confidence": "medium"})
    if any(token in paths for token in ("repository", "repo")):
        patterns.append({"name": "Repository", "confidence": "medium"})
    if "microservice" in architecture:
        patterns.append({"name": "Microservice", "confidence": "high"})
    if not patterns and architecture_style:
        patterns.append({"name": architecture_style, "confidence": "medium"})

    return patterns[:5]
