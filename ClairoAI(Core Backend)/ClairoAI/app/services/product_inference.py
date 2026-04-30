"""
Product-purpose and domain inference.

Turns structural analysis signals into product-level understanding:
- domain
- purpose
- target users
- system type
- investor-grade project goal
"""

from __future__ import annotations

import os
import re
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


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if token]


DOMAIN_RULES: list[dict[str, Any]] = [
    {
        "domain": "developer tools",
        "system_type": "code analysis tool",
        "target_users": "software engineers, engineering teams, and technical leads",
        "tokens": {"repo", "repository", "code", "analysis", "workflow", "module", "developer", "chat", "assistant", "architecture"},
        "purpose": "help engineering teams understand codebases, trace execution flow, and identify architectural risks faster",
    },
    {
        "domain": "AI verification",
        "system_type": "AI verification platform",
        "target_users": "AI teams, research teams, and trust and safety operators",
        "tokens": {"claim", "claims", "verification", "verify", "fact", "facts", "hallucination", "hallucinations", "source", "sources", "evidence", "validate", "truth", "score", "evaluate", "risk", "extract"},
        "purpose": "verify generated information, reduce hallucination risk, and surface trust-aware decisions",
    },
    {
        "domain": "education",
        "system_type": "learning platform",
        "target_users": "students, teachers, and education teams",
        "tokens": {"course", "lesson", "student", "quiz", "curriculum", "education", "learning"},
        "purpose": "turn structured learning content into accessible educational experiences and study workflows",
    },
    {
        "domain": "finance",
        "system_type": "financial operations platform",
        "target_users": "finance teams, analysts, and business operators",
        "tokens": {"payment", "invoice", "transaction", "portfolio", "trading", "finance", "billing"},
        "purpose": "streamline financial workflows, reduce operational overhead, and improve transaction visibility",
    },
    {
        "domain": "healthcare",
        "system_type": "health operations platform",
        "target_users": "clinicians, healthcare staff, and operations teams",
        "tokens": {"patient", "clinic", "medical", "health", "ehr", "appointment"},
        "purpose": "coordinate healthcare workflows, improve data access, and support reliable operational decisions",
    },
    {
        "domain": "security",
        "system_type": "security automation platform",
        "target_users": "security teams, platform teams, and compliance operators",
        "tokens": {"auth", "authentication", "authorization", "token", "security", "compliance", "permission"},
        "purpose": "protect system access, automate security controls, and reduce operational risk",
    },
    {
        "domain": "e-commerce",
        "system_type": "commerce platform",
        "target_users": "online retailers, operations teams, and shoppers",
        "tokens": {"cart", "checkout", "order", "product", "catalog", "inventory", "shop"},
        "purpose": "manage digital commerce workflows, from catalog operations to order fulfillment",
    },
    {
        "domain": "data analytics",
        "system_type": "analytics platform",
        "target_users": "analysts, operators, and decision-makers",
        "tokens": {"dashboard", "report", "metric", "analytics", "visualization", "insight", "kpi"},
        "purpose": "turn operational data into actionable insights and faster business decisions",
    },
]


GENERIC_GOAL_PATTERNS = (
    "this code appears",
    "this project appears",
    "this repository appears",
    "software system",
    "software project",
    "structured application",
    "analysis completed",
    "partial analysis completed",
)


def _score_rule(tokens: set[str], rule: dict[str, Any]) -> int:
    return sum(2 for token in rule["tokens"] if token in tokens)


def _trim_words(text: str, max_words: int) -> str:
    words = " ".join(str(text).split()).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:.") + "."


def _two_sentence_goal(sentence_one: str, sentence_two: str, max_words: int = 60) -> str:
    first = " ".join(str(sentence_one).split()).rstrip(" .") + "."
    second = " ".join(str(sentence_two).split()).rstrip(" .") + "."
    combined = f"{first} {second}"
    words = combined.split()
    if len(words) <= max_words:
        return combined

    first_words = first.split()
    second_words = second.split()
    remaining = max_words - len(first_words)
    if remaining < 8:
        first = _trim_words(first, max(20, max_words // 2))
        first_words = first.split()
        remaining = max_words - len(first_words)
    second = _trim_words(second, max(8, remaining))
    return f'{first.rstrip(".")}. {second}'


def _planner_domain(
    *,
    profile: Dict[str, Any],
    result: Dict[str, Any],
    behavior: Dict[str, bool],
) -> str:
    validated_domain = " ".join(str(result.get("validated_domain", "")).split())
    if validated_domain:
        return validated_domain
    if (
        behavior["extracts_claims"]
        or behavior["verifies_information"]
        or behavior["scores_truth"]
        or behavior["uses_external_sources"]
    ):
        return "AI verification"
    return " ".join(str(profile.get("domain", "")).split())


def _analyst_value_props(
    *,
    profile: Dict[str, Any],
    result: Dict[str, Any],
    behavior: Dict[str, bool],
) -> tuple[str, str]:
    target_users = " ".join(str(profile.get("target_users", "")).split()) or "teams"
    system_type = " ".join(str(result.get("system_type") or profile.get("system_type", "")).split())
    validated_behavior = " ".join(str(result.get("validated_behavior", "")).split())
    purpose = " ".join(str(profile.get("purpose", "")).split())

    if (
        behavior["extracts_claims"]
        or behavior["verifies_information"]
        or behavior["scores_truth"]
        or str(result.get("validated_domain", "")).strip().lower() == "ai verification"
    ):
        problem_statement = (
            "A verification product that detects unsupported claims and untrusted generated output"
        )
        solution_statement = (
            "It extracts claims, validates them with external evidence, and scores reliability to deliver explainable truth assessments at scale"
        )
        if behavior["multi_agent"]:
            solution_statement = (
                "It combines multi-agent reasoning, external validation, and reliability scoring to deliver explainable truth assessments at scale"
            )
        return problem_statement, solution_statement

    if str(profile.get("domain", "")).strip().lower() == "developer tools":
        return (
            f"A {system_type or 'code analysis tool'} that reduces codebase complexity for {target_users}",
            "It converts opaque software behavior into clear execution insight, accelerating debugging, architecture reviews, and technical decisions",
        )

    problem_statement = (
        f"A {str(_planner_domain(profile=profile, result=result, behavior=behavior) or 'software').strip()} "
        f"{system_type or 'product'} that removes friction for {target_users}"
    )
    solution_statement = (
        f"It transforms that workflow into a repeatable product experience built to {purpose}, creating faster decisions and more reliable outcomes"
        if purpose
        else "It turns complex operational logic into a repeatable product experience, creating faster decisions and more reliable outcomes"
    )
    if validated_behavior and "verification" not in validated_behavior.lower():
        solution_statement = (
            validated_behavior.rstrip(".") + ", creating faster decisions and more reliable outcomes"
        )
    return problem_statement, solution_statement


def _verifier_locked_domain(
    *,
    planned_domain: str,
    behavior: Dict[str, bool],
) -> str:
    if (
        behavior["extracts_claims"]
        or behavior["verifies_information"]
        or behavior["scores_truth"]
        or behavior["uses_external_sources"]
    ):
        return "AI verification"
    return planned_domain


def _synthesizer_goal(
    *,
    locked_domain: str,
    problem_statement: str,
    solution_statement: str,
) -> str:
    if locked_domain.lower().replace(" ", "_") == "ai_verification":
        return _two_sentence_goal(problem_statement, solution_statement)
    return _two_sentence_goal(problem_statement, solution_statement)


def _detect_scope(
    *,
    sampled_files: List[Dict[str, str]],
    result: Dict[str, Any],
) -> str:
    file_count = len([file_info for file_info in sampled_files if str(file_info.get("path", "")).strip() or str(file_info.get("content", "")).strip()])
    total_lines = 0
    meaningful_logic = False

    for file_info in sampled_files[:8]:
        content = str(file_info.get("content", "") or "")
        if content.strip():
            total_lines += len([line for line in content.splitlines() if line.strip()])
        lowered = content.lower()
        if any(token in lowered for token in ("def ", "class ", "async ", "return ", "if ", "for ", "while ", "try:", "await ", "function ", "=>", "app.", "router.", "select ", "insert ", "update ")):
            meaningful_logic = True

    if len(_dedupe(result.get("key_modules", []))) >= 3 or len(_dedupe(result.get("core_features", []))) >= 3:
        meaningful_logic = True

    if file_count < 3 or total_lines < 20 or not meaningful_logic:
        return "trivial"
    return "system"


def _extract_entry_points(sampled_files: List[Dict[str, str]]) -> List[str]:
    hints = ("main", "app", "server", "index", "bootstrap", "startup", "create_app")
    entry_points: List[str] = []
    for file_info in sampled_files[:12]:
        path = str(file_info.get("path", "") or "")
        lowered = os.path.basename(path).lower()
        if any(hint in lowered for hint in hints):
            entry_points.append(os.path.basename(path) or path)
    return _dedupe(entry_points)[:4]


def _infer_behavior_actions(result: Dict[str, Any], sampled_files: List[Dict[str, str]]) -> List[str]:
    combined = " ".join(
        [
            " ".join(_dedupe(result.get("key_modules", []))),
            " ".join(_dedupe(result.get("core_features", []))),
            " ".join(str(file_info.get("path", "")) for file_info in sampled_files[:12]),
            " ".join(str(file_info.get("content", ""))[:500] for file_info in sampled_files[:6]),
        ]
    ).lower()
    actions: List[str] = []
    action_map = [
        (("analy", "parse", "extract"), "analyzes structured inputs"),
        (("fetch", "request", "http", "api", "retriev"), "fetches or receives external or user-provided data"),
        (("save", "store", "persist", "repo", "mongo", "db", "database"), "stores results and session state"),
        (("map", "graph", "depend"), "maps relationships between modules and dependencies"),
        (("workflow", "route", "dispatch", "execute"), "traces execution flow across processing steps"),
        (("verify", "validate", "score", "risk"), "evaluates and scores processed information"),
        (("chat", "prompt", "answer", "context"), "builds contextual responses from stored analysis"),
    ]
    for tokens, description in action_map:
        if any(token in combined for token in tokens):
            actions.append(description)
    return _dedupe(actions)[:5]


def _build_grounded_system_goal(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
) -> str:
    entry_points = _extract_entry_points(sampled_files)
    modules = _dedupe(result.get("key_modules", []))[:4]
    features = _dedupe(result.get("core_features", []))[:4]
    workflows = result.get("workflows", []) if isinstance(result.get("workflows"), list) else []
    dependency_graph = result.get("dependency_graph", {}) if isinstance(result.get("dependency_graph"), dict) else {}
    actions = _infer_behavior_actions(result, sampled_files)

    workflow_steps: List[str] = []
    for workflow in workflows[:2]:
        if isinstance(workflow, dict):
            workflow_steps.extend(_dedupe(workflow.get("steps", []))[:4])
    workflow_steps = _dedupe(workflow_steps)[:5]
    central_nodes = _dedupe(dependency_graph.get("central_nodes", []))[:3]

    if not actions and not modules and not features and not workflow_steps:
        return "A modular analysis pipeline that receives structured inputs, routes them through staged processing, and returns analyzed outputs."

    sentence_one_parts: List[str] = ["A modular system"]
    if actions:
        sentence_one_parts.append(actions[0])
    elif features:
        sentence_one_parts.append(f"focused on {features[0].lower().rstrip('.')}")
    elif modules:
        sentence_one_parts.append(f"organized around modules such as {', '.join(modules[:2])}")
    sentence_one = " ".join(sentence_one_parts).rstrip(" ,") + "."

    sentence_two_parts: List[str] = []
    if entry_points:
        sentence_two_parts.append(f"Execution begins through {', '.join(entry_points[:2])}")
    else:
        sentence_two_parts.append("Execution begins when input enters the primary processing path")

    if workflow_steps:
        sentence_two_parts.append("moves through " + " -> ".join(workflow_steps[:4]))
    elif central_nodes:
        sentence_two_parts.append("routes through " + ", ".join(central_nodes))
    elif len(actions) > 1:
        sentence_two_parts.append("continues by " + ", then ".join(action.lower() for action in actions[1:3]))
    else:
        sentence_two_parts.append("continues through modular processing stages")

    if len(actions) > 2:
        sentence_two_parts.append("and returns analyzed results")
    elif any("stores" in action for action in actions):
        sentence_two_parts.append("and stores the resulting state")
    else:
        sentence_two_parts.append("and returns structured output")

    sentence_two = " ".join(sentence_two_parts).rstrip(" ,") + "."

    sentence_three = ""
    if len(actions) >= 3:
        sentence_three = "Its purpose is to " + ", ".join(action.lower() for action in actions[:3]) + "."
    elif features:
        sentence_three = f"Its purpose is to support {features[0].lower().rstrip('.')} through modular execution flow."
    elif modules:
        sentence_three = f"Its purpose is to coordinate {', '.join(modules[:2])} into a consistent processing workflow."

    final = " ".join(part for part in [sentence_one, sentence_two, sentence_three] if part).strip()
    return _trim_words(final, 65)


def _classify_goal_confidence(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
) -> str:
    behavior = _extract_behavior_signals(result, sampled_files)
    modules = _dedupe(result.get("key_modules", []))
    features = _dedupe(result.get("core_features", []))
    workflows = result.get("workflows", []) if isinstance(result.get("workflows"), list) else []
    graph = result.get("dependency_graph", {}) if isinstance(result.get("dependency_graph"), dict) else {}
    entry_points = _extract_entry_points(sampled_files)

    signal_count = sum(
        1
        for flag in behavior.values()
        if flag
    )
    if signal_count >= 3 and (len(workflows) >= 1 or len(graph.get("edges", []) or []) >= 4 or entry_points):
        return "HIGH"
    if signal_count >= 1 or len(modules) >= 2 or len(features) >= 2 or entry_points:
        return "MEDIUM"
    return "LOW"


def _detect_domain_theme(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
) -> str:
    combined = " ".join(
        [
            " ".join(_dedupe(result.get("key_modules", []))),
            " ".join(_dedupe(result.get("core_features", []))),
            str(result.get("validated_domain", "")),
            str(result.get("domain", "")),
            " ".join(str(file_info.get("path", "")) for file_info in sampled_files[:15]),
            " ".join(str(file_info.get("content", ""))[:500] for file_info in sampled_files[:8]),
        ]
    ).lower()

    biology_tokens = ("bio", "biology", "genome", "genomic", "dna", "rna", "cell", "protein")
    healthcare_tokens = ("medical", "patient", "clinic", "health", "ehr", "diagnosis")
    education_tokens = ("learning", "quiz", "student", "course", "curriculum", "lesson", "teacher")
    verification_tokens = ("claim", "claims", "verify", "verification", "truth", "fact", "evidence", "hallucination")
    ai_tokens = ("model", "predict", "prediction", "train", "inference", "agent", "llm", "reasoning")

    has_biology = any(token in combined for token in biology_tokens)
    has_healthcare = any(token in combined for token in healthcare_tokens)
    has_education = any(token in combined for token in education_tokens)
    has_verification = any(token in combined for token in verification_tokens)
    has_ai = any(token in combined for token in ai_tokens)

    if has_verification:
        return "verification_system"
    if has_biology and has_education:
        return "biology_education_platform"
    if has_healthcare and has_ai:
        return "healthcare_ai_system"
    if has_healthcare:
        return "healthcare_system"
    if has_biology:
        return "biology_system"
    if has_education:
        return "education_platform"
    if has_ai:
        return "ai_system"
    return ""


def _detect_project_type(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
) -> str:
    behavior = _extract_behavior_signals(result, sampled_files)
    modules = _dedupe(result.get("key_modules", []))
    features = _dedupe(result.get("core_features", []))
    entry_points = _extract_entry_points(sampled_files)
    workflows = result.get("workflows", []) if isinstance(result.get("workflows"), list) else []
    graph = result.get("dependency_graph", {}) if isinstance(result.get("dependency_graph"), dict) else {}
    combined = " ".join(
        [
            " ".join(modules),
            " ".join(features),
            " ".join(str(file_info.get("path", "")) for file_info in sampled_files[:15]),
            " ".join(str(file_info.get("content", ""))[:500] for file_info in sampled_files[:8]),
        ]
    ).lower()

    if _detect_scope(sampled_files=sampled_files, result=result) == "trivial":
        return "script_utility"
    if any(token in combined for token in ("predict", "prediction", "model", "train", "inference", "classifier")):
        return "ai_ml_system"
    if behavior["analysis_intelligence"] and (behavior["extracts_claims"] or any(token in combined for token in ("analy", "extract", "transform", "pipeline"))):
        return "data_processing_analysis_system"
    if any(token in combined for token in ("middleware", "route", "router", "endpoint", "request", "response")) or (
        entry_points and len(workflows) >= 1 and len(graph.get("edges", []) or []) >= 3
    ):
        return "backend_service"
    if len(modules) >= 4 and len(entry_points) >= 1 and len(graph.get("edges", []) or []) >= 6:
        return "full_product_platform"
    if len(modules) >= 5 or len(features) >= 5:
        return "full_product_platform"
    if any(token in combined for token in ("analy", "extract", "transform", "pipeline", "workflow", "graph")):
        return "data_processing_analysis_system"
    return "backend_service"

def extract_fact_sheet(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    sampled_files = sampled_files or []
    entry_points = _extract_entry_points(sampled_files)
    modules = _dedupe(result.get("key_modules", []))[:6]
    actions = _infer_behavior_actions(result, sampled_files)
    workflows = result.get("workflows", []) if isinstance(result.get("workflows"), list) else []
    dependency_graph = result.get("dependency_graph", {}) if isinstance(result.get("dependency_graph"), dict) else {}

    workflow_steps: List[str] = []
    for workflow in workflows[:2]:
        if isinstance(workflow, dict):
            workflow_steps.extend(_dedupe(workflow.get("steps", []))[:4])
    workflow_steps = _dedupe(workflow_steps)[:4]

    if workflow_steps:
        flow = " -> ".join(workflow_steps)
    elif entry_points and modules:
        flow = " -> ".join(_dedupe(entry_points[:1] + modules[:2] + ["output"]))
    elif modules:
        flow = " -> ".join(_dedupe(["input"] + modules[:2] + ["output"]))
    elif dependency_graph.get("central_nodes"):
        central_nodes = _dedupe(dependency_graph.get("central_nodes", []))[:2]
        flow = " -> ".join(["input"] + central_nodes + ["output"])
    else:
        flow = "input -> processing -> output"

    return {
        "entry_points": entry_points,
        "modules": modules,
        "actions": actions,
        "flow": flow,
        "domain_theme": _detect_domain_theme(result=result, sampled_files=sampled_files),
        "project_type": _detect_project_type(result=result, sampled_files=sampled_files),
        "confidence": _classify_goal_confidence(result=result, sampled_files=sampled_files),
    }


def _describe_trivial_code(
    *,
    sampled_files: List[Dict[str, str]],
    result: Dict[str, Any],
) -> str:
    content = "\n".join(str(file_info.get("content", "") or "") for file_info in sampled_files[:3]).strip()
    lowered = content.lower()
    modules = _dedupe(result.get("key_modules", []))[:2]
    features = _dedupe(result.get("core_features", []))[:2]

    if "print(" in lowered or "console.log" in lowered:
        return "A simple script that prints output and demonstrates basic program execution."
    if any(token in lowered for token in ("input(", "readline", "argv", "sys.argv")):
        return "A small utility that reads input, applies a direct transformation, and returns the result."
    if any(token in lowered for token in ("def ", "function ", "=>")) and not any(token in lowered for token in ("requests.", "httpx", "fetch(", "router.", "app.")):
        return "A focused code snippet that defines a small piece of logic for a specific calculation or transformation."
    if features:
        return f"A small code snippet centered on {features[0].lower().rstrip('.')}, with localized logic and limited system context."
    if modules:
        return f"A compact code sample focused on {modules[0]}, with localized logic rather than a broader execution workflow."
    return "A simple code snippet with limited logic, intended for a focused technical explanation rather than full system inference."


def _extract_behavior_signals(
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]],
) -> Dict[str, bool]:
    modules = _dedupe(result.get("key_modules", []))
    features = _dedupe(result.get("core_features", []))
    architecture = " ".join(str(result.get("architecture_style", "")).split())
    combined = " ".join(
        [
            architecture,
            " ".join(modules),
            " ".join(features),
            " ".join(str(file_info.get("path", "")) for file_info in sampled_files[:20]),
            " ".join(str(file_info.get("content", ""))[:800] for file_info in sampled_files[:8]),
        ]
    ).lower()

    return {
        "extracts_claims": any(token in combined for token in ("claim", "claims", "extract_claim", "claim_extractor")),
        "verifies_information": any(token in combined for token in ("verify", "verification", "validate_fact", "fact_check", "factual")),
        "uses_external_sources": any(token in combined for token in ("requests.", "httpx", "serpapi", "wikipedia", "google", "bing", "external api", "source", "evidence", "retriev")),
        "scores_truth": any(token in combined for token in ("score", "scoring", "confidence", "risk", "truth", "groundedness", "hallucination")),
        "multi_agent": any(token in combined for token in ("agent", "orchestr", "planner", "worker", "supervisor", "delegate")),
        "analysis_intelligence": any(token in combined for token in ("analy", "reason", "evaluate", "assess", "risk")),
    }


def extract_behavior_signals(
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
) -> Dict[str, bool]:
    return _extract_behavior_signals(result, sampled_files or [])


def infer_analysis_plan(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
    session_type: str = "repo",
) -> Dict[str, Any]:
    sampled_files = sampled_files or []
    profile = infer_product_profile(
        result=result,
        sampled_files=sampled_files,
        session_type=session_type,
    )
    behavior = _extract_behavior_signals(result, sampled_files)
    focus: List[str] = []

    domain = str(profile.get("domain", "")).strip()
    confidence = str(profile.get("confidence", "low")).strip() or "low"

    if domain.lower().replace(" ", "_") == "ai_verification" or behavior["extracts_claims"] or behavior["verifies_information"]:
        focus.extend(["goal", "workflow", "risks", "architecture"])
        if behavior["scores_truth"] and confidence != "high":
            confidence = "high"
    else:
        focus.append("goal")
        if behavior["uses_external_sources"] or behavior["multi_agent"] or str(result.get("architecture_style", "")).strip():
            focus.append("architecture")
        if behavior["verifies_information"] or behavior["scores_truth"] or result.get("risks"):
            focus.append("risks")
        if behavior["extracts_claims"] or behavior["analysis_intelligence"] or result.get("workflows"):
            focus.append("workflow")

    if len(focus) < 4:
        for item in ("goal", "architecture", "risks", "workflow"):
            if item not in focus:
                focus.append(item)
            if len(focus) >= 4:
                break

    return {
        "domain": domain or "unknown",
        "focus": _dedupe(focus)[:4],
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
    }


def infer_product_profile(
    *,
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
    session_type: str = "repo",
) -> Dict[str, Any]:
    sampled_files = sampled_files or []
    modules = _dedupe(result.get("key_modules", []))[:8]
    features = _dedupe(result.get("core_features", []))[:8]
    architecture = " ".join(str(result.get("architecture_style", "")).split())
    combined_parts = [
        architecture,
        " ".join(modules),
        " ".join(features),
        " ".join(str(file_info.get("path", "")) for file_info in sampled_files[:20]),
        " ".join(str(file_info.get("content", ""))[:400] for file_info in sampled_files[:6]),
    ]
    tokens = set(_tokenize(" ".join(combined_parts)))

    behavior = _extract_behavior_signals(result, sampled_files)

    if (
        behavior["extracts_claims"]
        and behavior["verifies_information"]
        and behavior["scores_truth"]
    ) or (
        behavior["extracts_claims"]
        and behavior["uses_external_sources"]
        and behavior["analysis_intelligence"]
    ):
        keywords = _dedupe(list(tokens))[:12]
        return {
            "domain": "AI verification",
            "purpose": "extract claims, validate them against external evidence, and score factual reliability to reduce hallucination risk",
            "target_users": "AI product teams, trust and safety teams, researchers, and enterprises deploying generative AI",
            "system_type": "multi-agent AI verification platform" if behavior["multi_agent"] else "AI verification platform",
            "keywords": keywords,
            "confidence": "high",
        }

    best_rule = None
    best_score = -1
    for rule in DOMAIN_RULES:
        score = _score_rule(tokens, rule)
        if score > best_score:
            best_rule = rule
            best_score = score

    if best_rule and best_score > 0:
        domain = best_rule["domain"]
        system_type = best_rule["system_type"]
        target_users = best_rule["target_users"]
        purpose = best_rule["purpose"]
        confidence = "high" if best_score >= 8 else "medium"
    else:
        if session_type == "code":
            domain = "developer tools"
            system_type = "code intelligence tool"
            target_users = "developers reviewing implementation logic"
            purpose = "explain code behavior, implementation flow, and technical responsibilities"
        elif session_type == "folder":
            domain = "developer tools"
            system_type = "project intelligence workspace"
            target_users = "engineering teams exploring project structure"
            purpose = "map project structure, execution flow, and module responsibilities"
        else:
            domain = "software infrastructure"
            system_type = "application platform"
            target_users = "technical operators and product teams"
            purpose = "deliver the core workflow encoded in the analyzed modules and services"
        confidence = "low"

    if "fastapi" in architecture.lower() or "flask" in architecture.lower() or "express" in architecture.lower():
        system_type = "API platform"
    elif "react" in architecture.lower() or "frontend" in architecture.lower():
        system_type = "interactive web platform"
    elif "dashboard" in " ".join(features).lower():
        system_type = "analytics dashboard"
    elif "assistant" in " ".join(features + modules).lower():
        system_type = "AI assistant platform"

    keywords = _dedupe(list(tokens))[:12]
    return {
        "domain": domain,
        "purpose": purpose,
        "target_users": target_users,
        "system_type": system_type,
        "keywords": keywords,
        "confidence": confidence,
    }


def build_project_goal(
    profile: Dict[str, Any],
    result: Dict[str, Any],
    sampled_files: List[Dict[str, str]] | None = None,
) -> str:
    del profile
    sampled_files = sampled_files or []
    scope = _detect_scope(sampled_files=sampled_files, result=result)
    if scope == "trivial":
        return _describe_trivial_code(sampled_files=sampled_files, result=result)
    facts = extract_fact_sheet(result=result, sampled_files=sampled_files)
    actions = list(facts.get("actions", []))
    flow = str(facts.get("flow", "")).strip()
    modules = list(facts.get("modules", []))
    domain_theme = str(facts.get("domain_theme", "")).strip()
    project_type = str(facts.get("project_type", "")).strip()

    if domain_theme == "verification_system":
        goal = (
            "A verification system designed to analyze information, extract claims, and validate them against supporting evidence. "
            f"It follows {flow}, helping turn uncertain inputs into explainable verification outcomes."
        )
    elif domain_theme == "biology_education_platform":
        goal = (
            "A biology-focused learning system designed to organize and deliver structured educational content around complex scientific topics. "
            f"It follows {flow}, helping users understand biological concepts through a coordinated content and analysis workflow."
        )
    elif domain_theme == "healthcare_ai_system":
        goal = (
            "A healthcare-oriented AI system designed to process domain-specific information and generate structured analytical outputs for clinical or operational use. "
            f"It follows {flow}, combining medical context with automated reasoning to support clearer decisions."
        )
    elif domain_theme == "healthcare_system":
        goal = (
            "A healthcare-oriented system designed to manage and analyze medically relevant information through modular processing stages. "
            f"It follows {flow}, supporting more reliable handling of clinical or operational workflows."
        )
    elif domain_theme == "biology_system":
        goal = (
            "A biology-focused system designed to process and organize domain-specific scientific information through modular analysis stages. "
            f"It follows {flow}, helping convert specialized biological inputs into structured outputs for interpretation."
        )
    elif domain_theme == "education_platform":
        goal = (
            "An education-oriented system designed to organize learning content and guide users through structured instructional workflows. "
            f"It follows {flow}, turning educational inputs into clearer, more usable learning outputs."
        )
    elif domain_theme == "ai_system":
        goal = (
            "An AI-oriented system designed to process inputs through automated reasoning or inference components and generate structured outputs. "
            f"It follows {flow}, indicating intelligence-driven decision logic rather than simple data transport."
        )
    elif project_type == "script_utility":
        goal = (
            "A lightweight utility designed to perform a focused task through a compact execution flow. "
            "It runs localized logic and produces a direct output without the broader coordination expected from a larger system."
        )
    elif project_type == "backend_service":
        action_fragment = actions[0] if actions else "handles requests and coordinates processing"
        goal = (
            f"A backend service that {action_fragment} through modular request-handling components. "
            f"It follows the execution path {flow}, showing a structured API-oriented workflow that returns organized outputs."
        )
    elif project_type == "data_processing_analysis_system":
        action_fragment = ", ".join(actions[:2]) if actions else "processes and analyzes structured information"
        goal = (
            f"A system built to {action_fragment} through a coordinated processing pipeline. "
            f"It moves through {flow}, turning raw inputs into structured outputs that support downstream interpretation and decision-making."
        )
    elif project_type == "ai_ml_system":
        action_fragment = ", ".join(actions[:2]) if actions else "processes inputs through learned or rule-based logic"
        goal = (
            f"An AI or ML-oriented system that {action_fragment} to generate intelligent outputs. "
            f"Its workflow progresses through {flow}, indicating automated reasoning or inference rather than simple data transport."
        )
    elif project_type == "full_product_platform":
        module_fragment = ", ".join(modules[:3]) if modules else "multiple coordinated components"
        goal = (
            f"A software platform that connects {module_fragment} to manage a multi-stage workflow. "
            f"It follows {flow}, indicating a layered product architecture with processing, persistence, and delivery responsibilities."
        )
    else:
        goal = _build_grounded_system_goal(result=result, sampled_files=sampled_files)

    return _trim_words(goal, 58)


def should_replace_project_goal(project_goal: str) -> bool:
    normalized = " ".join(str(project_goal or "").split()).lower()
    if not normalized:
        return True
    return any(pattern in normalized for pattern in GENERIC_GOAL_PATTERNS)
