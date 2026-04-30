import re
from typing import Any


BAD_FEATURE_PATTERNS = [
    "data processing",
    "request execution",
    "handling logic",
    "system orchestration",
]

ALLOWED_ARCHITECTURES = [
    "component-based",
    "api-service",
    "client-server",
    "monolithic",
    "script-based",
    "static-web",
    "client-server + component-based",
]

_UNCERTAIN_PHRASES = ("suggests", "appears", "indicates")
_MEDICAL_RE = re.compile(r"\b(medical|diagnosis|diagnostic|clinical|patient|healthcare|clinic)\b", re.IGNORECASE)
_CODE_ANALYSIS_RE = re.compile(r"\b(repo|repository|codebase|source code|code analysis|folder analysis|developer workflow|code insight)\b", re.IGNORECASE)
_BIO_EDU_RE = re.compile(r"\b(biology|bio|learning|student|quiz|education|course)\b", re.IGNORECASE)
_RAG_RE = re.compile(r"\b(rag|retrieval|embedding|embeddings|vector|chromadb|faiss)\b", re.IGNORECASE)
_AI_DEP_RE = re.compile(r"\b(ollama|transformers|torch|tensorflow|langchain|openai|gemini|llm|inference)\b", re.IGNORECASE)
_AI_FILE_RE = re.compile(r"\b(ai_engine|rag|pipeline|inference|retrieval|embedding|model)\.(py|js|ts|tsx|jsx)\b", re.IGNORECASE)
_API_RE = re.compile(r"\b(api|endpoint|route|router|request|backend|fastapi|flask|express)\b", re.IGNORECASE)
_COMPONENT_RE = re.compile(r"\b(component|page|layout|ui|frontend|react|next)\b", re.IGNORECASE)
_STATIC_WEB_RE = re.compile(r"\b(html|css|template|static|landing page|addEventListener|document\.getElementById)\b", re.IGNORECASE)


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _strip_uncertain_language(text: str) -> str:
    cleaned = str(text or "").strip()
    for phrase in _UNCERTAIN_PHRASES:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmay represent\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:-")
    return cleaned


def _strip_file_noise(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][^,\]\[;:]+)+", "", cleaned)
    cleaned = re.sub(r"[\w\-/\\.]+\.py", "", cleaned)
    cleaned = re.sub(r"[\w\-/\\.]+\.md", "", cleaned)
    cleaned = re.sub(r"[\w\-/\\.]+\.txt", "", cleaned)
    cleaned = re.sub(r"[\w\-/\\.]+\.tsx?", "", cleaned)
    cleaned = re.sub(r"[\w\-/\\.]+\.jsx?", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:-")
    return cleaned


def _combined_text(data: dict[str, Any]) -> str:
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    summary_blocks = data.get("summary_blocks") if isinstance(data.get("summary_blocks"), dict) else {}
    return " ".join(
        [
            str(data.get("project_goal", "")),
            str(data.get("architecture_style", "")),
            " ".join(str(item) for item in data.get("key_modules", []) or []),
            " ".join(str(item) for item in data.get("core_features", []) or []),
            " ".join(str(item) for item in data.get("risks", []) or []),
            str(summary.get("what", "")),
            str(summary.get("why", "")),
            str(summary_blocks.get("what", "")),
            str(summary_blocks.get("why", "")),
        ]
    )


def _detect_domain(text: str) -> str:
    lowered = str(text or "").lower()
    if _BIO_EDU_RE.search(lowered):
        return "educational-biology"
    if _MEDICAL_RE.search(lowered):
        return "medical"
    if _CODE_ANALYSIS_RE.search(lowered):
        return "code-analysis"
    return "generic"


def _count_strong_signals(text: str, architecture: str) -> int:
    lowered = str(text or "").lower()
    count = 0
    if _AI_FILE_RE.search(lowered):
        count += 1
    if _AI_DEP_RE.search(lowered):
        count += 1
    if _API_RE.search(lowered) or "api-service" in architecture:
        count += 1
    return count


def _has_strong_ai_evidence(text: str, architecture: str) -> bool:
    return _count_strong_signals(text, architecture) >= 2 and (
        bool(_AI_DEP_RE.search(text)) or bool(_AI_FILE_RE.search(text))
    )


def _has_strong_rag_evidence(text: str, architecture: str) -> bool:
    lowered = str(text or "").lower()
    return _has_strong_ai_evidence(lowered, architecture) and bool(_RAG_RE.search(lowered))


def _rewrite_project_goal(goal: str, *, domain: str, architecture: str, text: str, file_count: int = 2) -> str:
    cleaned = clean_project_goal(goal)
    if cleaned and cleaned.lower() != "insufficient evidence to determine project goal":
        return cleaned

    lowered = text.lower()
    is_rag = "rag.py" in lowered or bool(_RAG_RE.search(lowered))
    is_medical = bool(_MEDICAL_RE.search(lowered))
    is_web = "index.html" in lowered or bool(_STATIC_WEB_RE.search(lowered))
    is_ai = "ai_engine.py" in lowered or bool(_AI_FILE_RE.search(lowered))

    if is_medical and is_rag:
        return "Offline-first medical RAG system for clinical decision support"
    if is_medical:
        return "Medical system for healthcare and clinical workflows"
    if is_web:
        return "Frontend-based interactive web application"
    if is_rag:
        return "RAG system for intelligent retrieval and processing"
    if is_ai:
        return "AI system for inference and intelligence workflows"

    if file_count < 2:
        return "Insufficient evidence to determine project goal"
    return "Lightweight application with limited structural signals"


def _default_features_for_domain(domain: str, architecture: str, text: str) -> list[str]:
    return ["Insufficient data"]


def _rewrite_summary_why(domain: str, architecture: str, text: str) -> str:
    return "Insufficient evidence"


def _clean_insights(insights: Any) -> list[dict[str, str]]:
    if not isinstance(insights, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in insights:
        if not isinstance(item, dict):
            continue
        insight = _strip_file_noise(_strip_uncertain_language(str(item.get("insight", "")).strip()))
        source = str(item.get("source", "")).replace("\\", "/").strip().split("/")[-1]
        impact = _strip_file_noise(_strip_uncertain_language(str(item.get("impact", "")).strip()))
        insight_type = str(item.get("type", "")).strip() or "architecture"
        if not insight or not source or not impact:
            continue
        key = (insight, source, impact, insight_type)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "insight": insight,
            "source": source,
            "impact": impact,
            "type": insight_type,
        })
    return cleaned[:5]


def normalize_architecture(text: str) -> str:
    text = str(text or "").lower()
    has_api = any(x in text for x in ["fastapi", "flask", "express", "api-service", "api", "router", "route"])
    has_component = any(x in text for x in ["react", "next", "component-based", "component", "page.tsx", "layout.tsx"])
    has_static_web = bool(_STATIC_WEB_RE.search(text)) and not has_component and not has_api
    has_script = any(x in text for x in ["script-based", "script", "if __name__", ".sh"])

    if has_api and has_component:
        result = "client-server + component-based"
    elif has_api:
        result = "api-service"
    elif has_component:
        result = "component-based"
    elif has_static_web:
        result = "static-web"
    elif has_script:
        result = "script-based"
    else:
        result = "monolithic"

    return result if result in ALLOWED_ARCHITECTURES else "monolithic"


def clean_features(features: list, *, domain: str = "generic", architecture: str = "monolithic", text: str = "") -> list:
    cleaned: list[str] = []
    lowered_text = text.lower()

    for feature in features or []:
        feature_text = _strip_file_noise(_strip_uncertain_language(str(feature or "")))
        if not feature_text:
            continue
        feature_lower = feature_text.lower()

        if any(p in feature_lower for p in BAD_FEATURE_PATTERNS):
            continue

        feature_text = re.sub(r"\s{2,}", " ", feature_text).strip(" ,.;:-")
        if feature_text:
            cleaned.append(feature_text)

    if not cleaned:
        if "api" in lowered_text or "route" in lowered_text:
            cleaned.append("REST API handling [routes]")
        if "ai_engine" in lowered_text:
            cleaned.append("AI inference pipeline [ai_engine.py]")
        if "html" in lowered_text or "js" in lowered_text:
            cleaned.append("User interface layer [index.html]")

    if not cleaned:
        cleaned = ["REST API handling [main.py]", "User interface layer [index.html]", "System processing logic [app.py]"]

    return _dedupe_preserve(cleaned)


def clean_risks(risks: list, *, domain: str = "generic", architecture: str = "monolithic", text: str = "") -> list:
    cleaned: list[str] = []

    for risk in risks or []:
        text_risk = _strip_file_noise(str(risk or ""))
        text_risk = re.sub(r"across .*", "", text_risk, flags=re.IGNORECASE)
        text_risk = _strip_uncertain_language(text_risk).strip(" ,.;:-")

        text_risk = re.sub(r"\s{2,}", " ", text_risk).strip(" ,.;:-")
        if len(text_risk) > 10:
            cleaned.append(text_risk)

    if not cleaned:
        lowered = text.lower()
        if ".env" in lowered:
            cleaned.append("Environment configuration dependency")
        if "test" in lowered:
            cleaned.append("Test code mixed with production")
        if "except" not in lowered and "error" not in lowered:
            cleaned.append("Limited error handling coverage")
        if not cleaned:
            cleaned.append("Limited error handling coverage")

    return _dedupe_preserve(cleaned)


def clean_project_goal(goal: str) -> str:
    goal = _strip_file_noise(str(goal or ""))
    goal = goal.replace("system that orchestrates", "")
    goal = goal.replace("codebase that suggests", "")
    goal = goal.replace("Codebase with modules that suggest", "")
    goal = _strip_uncertain_language(goal)
    goal = re.sub(r"\s{2,}", " ", goal).strip(" ,.;:-")
    return goal or "Insufficient evidence to determine project goal"


def clean_modules(modules: list) -> list:
    return _dedupe_preserve([
        str(module or "").replace("\\", "/").strip().split("/")[-1]
        for module in modules or []
        if str(module or "").strip()
    ])[:8]


def normalize_analysis_output(data: dict[str, Any], *, evidence_text: str = "", file_count: int = 2) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "project_goal": "Insufficient evidence to determine project goal" if file_count < 2 else "Lightweight application with limited structural signals",
            "architecture_style": "monolithic",
            "key_modules": ["core_module"],
            "core_features": ["REST API handling [routes]", "User interface layer [index.html]", "System processing logic [app.py]"],
            "risks": ["Limited error handling coverage"],
            "summary": {
                "what": "Insufficient evidence to determine project goal" if file_count < 2 else "Lightweight application with limited structural signals",
                "why": "Insufficient evidence",
                "issues": ["Limited error handling coverage"],
            },
        }

    normalized = dict(data)
    combined_text = " ".join([_combined_text(normalized), str(evidence_text or "")])
    architecture_source = " ".join(
        [
            str(normalized.get("architecture_style", "")),
            str(normalized.get("project_goal", "")),
            " ".join(str(item) for item in normalized.get("core_features", []) or []),
            " ".join(str(item) for item in normalized.get("key_modules", []) or []),
            str((normalized.get("summary") or {}).get("what", "")) if isinstance(normalized.get("summary"), dict) else "",
        ]
    )

    normalized["architecture_style"] = normalize_architecture(architecture_source)
    domain = _detect_domain(combined_text)
    normalized["project_goal"] = _rewrite_project_goal(
        normalized.get("project_goal", ""),
        domain=domain,
        architecture=normalized["architecture_style"],
        text=combined_text,
        file_count=file_count,
    )
    combined_text = " ".join([_combined_text(normalized), str(evidence_text or "")])
    normalized["core_features"] = clean_features(
        normalized.get("core_features", []),
        domain=domain,
        architecture=normalized["architecture_style"],
        text=combined_text,
    )
    normalized["risks"] = clean_risks(
        normalized.get("risks", []),
        domain=domain,
        architecture=normalized["architecture_style"],
        text=combined_text,
    )
    normalized["key_modules"] = clean_modules(normalized.get("key_modules", []))
    if not normalized["key_modules"]:
        normalized["key_modules"] = ["core_module"]
    
    if not normalized["core_features"]:
        normalized["core_features"] = ["Insufficient data signals detected"]

    if not normalized["risks"]:
        normalized["risks"] = ["Limited error handling coverage"]
    normalized["insights"] = _clean_insights(normalized.get("insights"))


    summary = normalized.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    summary["what"] = normalized["project_goal"]
    summary["why"] = _rewrite_summary_why(domain, normalized["architecture_style"], combined_text)
    summary["issues"] = list(normalized["risks"])
    normalized["summary"] = summary

    summary_blocks = normalized.get("summary_blocks")
    if isinstance(summary_blocks, dict):
        summary_blocks["what"] = normalized["project_goal"]
        summary_blocks["why"] = summary.get("why", "Insufficient evidence")
        summary_blocks["issues"] = list(normalized["risks"])
        remaining = summary_blocks.get("remaining", [])
        if isinstance(remaining, list):
            summary_blocks["remaining"] = _dedupe_preserve([
                _strip_file_noise(_strip_uncertain_language(str(item or ""))).strip(" ,.;:-")
                for item in remaining
                if _strip_file_noise(_strip_uncertain_language(str(item or ""))).strip(" ,.;:-")
            ])
            if not summary_blocks["remaining"] and domain in {"educational-biology", "medical", "code-analysis"} and "missing" in combined_text.lower():
                summary_blocks["remaining"] = ["Core domain logic not fully present in uploaded files"]
        normalized["summary_blocks"] = summary_blocks

    if normalized["architecture_style"] not in ALLOWED_ARCHITECTURES:
        normalized["architecture_style"] = "monolithic"

    return normalized
