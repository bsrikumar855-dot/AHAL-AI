"""
Repository analysis service — production-grade.

Downloads a GitHub repo as ZIP, selects top files by importance scoring,
builds truncated context, calls LLM with strict prompt, and returns
deterministic non-empty output. No git clone required.
"""

import asyncio
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, Any, List

import requests

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.services.intelligence_engine import enrich_result_with_intelligence
from app.services.knowledge_store import persist_analysis_knowledge
from app.services.llm_handler import call_llm
from app.services.normalize import normalize_result

logger = get_logger("services.repo")

# ── Config ───────────────────────────────────────────────────────
VALID_EXTENSIONS = {".py", ".js", ".ts", ".json"}
IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
MAX_FILES = 10
MAX_CHARS_PER_FILE = 1500
MAX_CONTEXT_CHARS = 8000
DOWNLOAD_TIMEOUT = 20
LLM_TIMEOUT = 55
FAST_LLM_TIMEOUT = 25
PARTIAL_LLM_TIMEOUT = 18
GITHUB_API_TIMEOUT = 15
GITHUB_BRANCH_FALLBACKS = ("main", "master", "dev")
ANALYSIS_CACHE_TTL_SECONDS = 600
_REPO_ANALYSIS_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}

# ── Static extraction ────────────────────────────────────────────
_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", re.MULTILINE)


def _dedupe(items: list) -> list:
    seen: set = set()
    result = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


@dataclass
class RepoDownloadError(Exception):
    message: str
    suggestion: str = "Failed to download repository. Please check the repo link or branch."
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


# ── Prompt ───────────────────────────────────────────────────────
REPO_ANALYSIS_PROMPT = """You MUST return valid JSON. If data is missing, infer ONLY from visible code. NEVER return empty response.

Analyze this GitHub repository's source files and return ONLY valid JSON.

REPOSITORY FILES:
{context}

DETECTED STRUCTURE:
- File count: {file_count}
- Framework hints: {framework_hints}
- Key filenames: {filenames}

OUTPUT (JSON only — no markdown, no explanation):
{{
  "project_goal": "one sentence: what this project does",
  "architecture_style": "specific label (microservice, monolith, library, CLI, MVC, etc.)",
  "key_modules": ["REAL filenames from the === FILE: headers === ONLY"],
  "core_features": ["specific implemented capability — NOT generic"],
  "risks": ["concrete risk found in the code"],
  "summary_blocks": {{
    "what": "precise summary of the project",
    "why": "why this project exists",
    "remaining": ["specific improvement needed"],
    "issues": ["specific weakness or problem"]
  }}
}}

RULES:
- key_modules = ONLY real filenames from the === FILE: headers ===
- core_features = derive from actual code behavior
- Detect framework: Flask, FastAPI, Express, React, Django, etc.
- Detect architecture: microservice, layered, monolith, library
- Every list must have at least 2 items
- NEVER return empty arrays
- Return JSON ONLY"""

REPO_FAST_PROMPT = """Analyze this repository using the compact project snapshot below and return ONLY valid JSON.

PROJECT SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the repository appears to do",
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only"],
  "core_features": ["implemented capabilities"],
  "risks": ["concrete technical risks"],
  "summary_blocks": {{
    "what": "concise explanation of the repository",
    "why": "why the project likely exists",
    "remaining": ["practical next step"],
    "issues": ["important weakness"]
  }}
}}

Rules:
- Be concise and specific
- Use only real filenames from the snapshot
- Return JSON ONLY"""

REPO_GOAL_PROMPT = """Return ONLY valid JSON describing this repository's goal and core features.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "project_goal": "what the repository does",
  "core_features": ["implemented capabilities", "second capability"]
}}"""

REPO_ARCH_PROMPT = """Return ONLY valid JSON describing this repository's architecture and key modules.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "architecture_style": "best architecture label",
  "key_modules": ["real filenames only", "second real filename"],
  "summary_blocks": {{
    "what": "how the system is structured",
    "why": "what the structure suggests about responsibilities"
  }}
}}"""

REPO_RISK_PROMPT = """Return ONLY valid JSON describing the main technical risks and next steps for this repository.

SNAPSHOT:
{snapshot}

OUTPUT:
{{
  "risks": ["concrete risk", "second concrete risk"],
  "summary_blocks": {{
    "remaining": ["practical next step", "second next step"],
    "issues": ["notable weakness", "second weakness"]
  }}
}}"""


def _detect_framework(context: str) -> str:
    """Detect framework from context."""
    ctx = context.lower()
    if "fastapi" in ctx:
        return "FastAPI"
    if "flask" in ctx:
        return "Flask"
    if "django" in ctx:
        return "Django"
    if "express" in ctx:
        return "Express.js"
    if "react" in ctx or "jsx" in ctx:
        return "React"
    if "next" in ctx and "next/app" in ctx:
        return "Next.js"
    if "vue" in ctx:
        return "Vue.js"
    return "general"


def _cache_get(cache_key: str) -> Dict[str, Any] | None:
    cached = _REPO_ANALYSIS_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _REPO_ANALYSIS_CACHE.pop(cache_key, None)
        return None
    return dict(payload)


def _cache_set(cache_key: str, payload: Dict[str, Any]) -> None:
    _REPO_ANALYSIS_CACHE[cache_key] = (time.time() + ANALYSIS_CACHE_TTL_SECONDS, dict(payload))
    if len(_REPO_ANALYSIS_CACHE) > 128:
        oldest_key = min(_REPO_ANALYSIS_CACHE, key=lambda key: _REPO_ANALYSIS_CACHE[key][0])
        _REPO_ANALYSIS_CACHE.pop(oldest_key, None)


def _build_structure_snapshot(files: List[Dict[str, str]], framework: str, branch: str) -> str:
    lines = [
        f"Default branch: {branch}",
        f"Framework hint: {framework}",
        f"Selected files: {', '.join(file['path'] for file in files[:10])}",
    ]
    for file in files[:6]:
        snippet = " ".join(file["content"].split())
        if len(snippet) > 260:
            snippet = snippet[:257].rstrip() + "..."
        lines.append(f"{file['path']}: {snippet}")
    return "\n".join(lines)


def _label_confidence(text: str, confidence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    prefix = f"[{confidence} confidence] "
    return cleaned if cleaned.startswith(prefix) else prefix + cleaned


def _merge_sectioned_result(base: Dict[str, Any], update: Dict[str, Any] | None) -> Dict[str, Any]:
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


def _infer_repo_goal(files: List[Dict[str, str]], framework: str) -> str:
    names = [os.path.basename(file["path"]) for file in files[:4]]
    if framework != "general":
        return f"A {framework} product organized around {', '.join(names)}, built to deliver the main workflow inferred from the repository structure."
    return f"A modular product codebase organized around {', '.join(names)}, built to support the primary workflow inferred from the analyzed repository."


def _smart_repo_fallback(files: List[Dict[str, str]], framework: str, branch: str) -> Dict[str, Any]:
    modules = [os.path.basename(file["path"]) for file in files[:6]]
    combined = "\n".join(file["content"] for file in files)
    functions = _dedupe(_FUNCTION_RE.findall(combined))[:4]
    classes = _dedupe(_CLASS_RE.findall(combined))[:4]
    features: list[str] = []
    if functions:
        features.append(f"Core logic is implemented through functions such as {', '.join(functions[:3])}")
    if classes:
        features.append(f"State and domain structure appear to be centered on classes such as {', '.join(classes[:3])}")
    if not features:
        features = [
            f"The repository is organized around modules like {', '.join(modules[:3])}",
            f"The codebase suggests a {framework} oriented workflow on branch {branch}",
        ]

    risks = [
        "Some architectural details are inferred from the sampled files rather than the entire repository",
        "A deeper pass across more files would improve dependency and edge-case coverage",
    ]
    return {
        "project_goal": _infer_repo_goal(files, framework),
        "architecture_style": f"{framework} repository".strip() if framework != "general" else "Structured code repository",
        "key_modules": modules,
        "core_features": features,
        "risks": risks,
        "summary_blocks": {
            "what": _label_confidence(
                f"The repository is structured around {', '.join(modules[:4])} and appears to separate core responsibilities into focused modules.",
                "MEDIUM",
            ),
            "why": _label_confidence(
                "Partial analysis completed from repository structure, prioritized source files, and inferred execution paths. Deeper semantic refinement can extend this view.",
                "MEDIUM",
            ),
            "remaining": [
                "Review additional non-sampled files for deeper dependency coverage",
                "Validate inferred architecture against deployment and configuration files",
            ],
            "issues": [
                "Some reasoning is inferred from sampled modules rather than a full repository pass",
                "Cross-module runtime behavior may need deeper verification",
            ],
        },
    }


def _call_repo_llm(prompt: str, timeout: int, label: str) -> Dict[str, Any] | None:
    try:
        started = time.monotonic()
        parsed = call_llm(
            prompt,
            timeout=timeout,
            simplified_prompt=prompt,
            mode="online",
        )
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        print(f"[REPO][{label}] LLM latency: {latency_ms}ms")
        return parsed
    except Exception as exc:
        print(f"[REPO][{label}] LLM failure: {exc}")
        logger.warning(f"Repo {label} LLM failure: {exc}")
        return None


def _run_repo_llm_enhancement(
    repo_url: str,
    branch: str,
    files: List[Dict[str, str]],
    context: str,
    framework: str,
) -> Dict[str, Any]:
    cache_key = sha256(f"{repo_url}|{branch}|{','.join(file['path'] for file in files[:10])}".encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        print("[REPO] Analysis cache hit")
        return cached

    base_result = _smart_repo_fallback(files, framework, branch)
    snapshot = _build_structure_snapshot(files, framework, branch)

    full_prompt = REPO_ANALYSIS_PROMPT.format(
        context=context,
        file_count=len(files),
        framework_hints=framework,
        filenames=", ".join(os.path.basename(f["path"]) for f in files),
    )
    print(f"[REPO] files_sent={len(files)}, context_size={len(context)}, prompt_size={len(full_prompt)}, branch={branch}")
    full_result = _call_repo_llm(full_prompt, LLM_TIMEOUT, "full")
    if full_result:
        merged = _merge_sectioned_result(base_result, full_result)
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(merged["summary_blocks"].get("why", ""), "HIGH")
        _cache_set(cache_key, merged)
        return merged

    time.sleep(1.0)
    fast_prompt = REPO_FAST_PROMPT.format(snapshot=snapshot)
    fast_result = _call_repo_llm(fast_prompt, FAST_LLM_TIMEOUT, "fast")
    if fast_result:
        merged = _merge_sectioned_result(base_result, fast_result)
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(
            merged["summary_blocks"].get("why", "") or "Partial analysis completed and refined through targeted AI passes.",
            "HIGH",
        )
        _cache_set(cache_key, merged)
        return merged

    partial_prompts = [
        ("goal", REPO_GOAL_PROMPT.format(snapshot=snapshot), PARTIAL_LLM_TIMEOUT),
        ("architecture", REPO_ARCH_PROMPT.format(snapshot=snapshot), PARTIAL_LLM_TIMEOUT),
        ("risks", REPO_RISK_PROMPT.format(snapshot=snapshot), PARTIAL_LLM_TIMEOUT),
    ]
    partial_successes = 0
    merged = dict(base_result)
    for index, (label, prompt, timeout) in enumerate(partial_prompts, start=1):
        partial = _call_repo_llm(prompt, timeout, label)
        if partial:
            partial_successes += 1
            merged = _merge_sectioned_result(merged, partial)
        if index < len(partial_prompts):
            time.sleep(1.0)

    if partial_successes > 0:
        merged["summary_blocks"]["what"] = _label_confidence(merged["summary_blocks"].get("what", ""), "HIGH")
        merged["summary_blocks"]["why"] = _label_confidence(
            "Partial analysis completed through targeted AI recovery plus repository structure inference.",
            "HIGH",
        )
        _cache_set(cache_key, merged)
        return merged

    _cache_set(cache_key, base_result)
    return base_result


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    match = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)/?$", repo_url.strip())
    if not match:
        raise RepoDownloadError(
            message="Invalid GitHub repository URL",
            suggestion="Use a public GitHub repository URL in the format https://github.com/owner/repo",
            status_code=400,
        )

    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _github_api_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AHAL-AI-Repo-Analyzer",
    }


def _repo_zip_url(owner: str, repo: str, branch: str) -> str:
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"


def _detect_default_branch(owner: str, repo: str) -> str | None:
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(api_url, headers=_github_api_headers(), timeout=GITHUB_API_TIMEOUT)
    print(f"GitHub API URL: {api_url}")
    print(f"GitHub API status: {response.status_code}")

    if response.status_code == 404:
        raise RepoDownloadError(
            message="Repository not found or is private",
            suggestion="Ensure the repo is public or provide access token",
            status_code=404,
        )

    if response.status_code in {401, 403}:
        raise RepoDownloadError(
            message="Repository not accessible or GitHub API access is restricted",
            suggestion="Ensure the repo is public or provide access token",
            status_code=403,
        )

    response.raise_for_status()
    payload = response.json()
    branch = str(payload.get("default_branch", "")).strip()
    print(f"Detected branch: {branch}")
    return branch or None


def _resolve_branch_candidates(owner: str, repo: str) -> list[str]:
    try:
        detected = _detect_default_branch(owner, repo)
    except RepoDownloadError:
        raise
    except Exception as exc:
        logger.warning(f"Default branch detection failed for {owner}/{repo}: {exc}")
        detected = None

    candidates: list[str] = []
    if detected:
        candidates.append(detected)
    candidates.extend(GITHUB_BRANCH_FALLBACKS)
    return _dedupe(candidates)


def _download_zip(repo_url: str, dest_path: str) -> str:
    """Download ZIP file from GitHub using detected or fallback branches."""
    owner, repo = _parse_github_repo_url(repo_url)
    branch_candidates = _resolve_branch_candidates(owner, repo)
    last_response: requests.Response | None = None

    for branch in branch_candidates:
        zip_url = _repo_zip_url(owner, repo, branch)
        logger.info(f"Downloading repository ZIP: {zip_url}")
        print(f"Detected branch: {branch}")
        print(f"Download URL: {zip_url}")
        response = requests.get(
            zip_url,
            headers=_github_api_headers(),
            timeout=DOWNLOAD_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
        print(f"Download status: {response.status_code}")
        last_response = response

        if response.status_code == 404:
            continue
        if response.status_code in {401, 403}:
            raise RepoDownloadError(
                message="Repository not found or is private",
                suggestion="Ensure the repo is public or provide access token",
                status_code=response.status_code,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RepoDownloadError(
                message=f"Failed to download repository archive: HTTP {response.status_code}",
                suggestion="Failed to download repository. Please check the repo link or branch.",
                status_code=response.status_code,
            ) from exc

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            raise RepoDownloadError(
                message="Downloaded repository archive is empty",
                suggestion="Failed to download repository. Please check the repo link or branch.",
                status_code=502,
            )

        logger.info(f"Downloaded {os.path.getsize(dest_path)} bytes from branch {branch}")
        return branch

    if last_response and last_response.status_code == 404:
        raise RepoDownloadError(
            message="Failed to download repository. Please check the repo link or branch.",
            suggestion="Ensure the repository exists and the default branch is accessible.",
            status_code=404,
        )

    raise RepoDownloadError(
        message="Failed to download repository. Please check the repo link or branch.",
        suggestion="Ensure the repository exists and is publicly accessible.",
        status_code=400,
    )


def _extract_zip(zip_path: str, extract_dir: str) -> str:
    """Extract ZIP and return root folder path."""
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
        raise RepoDownloadError(
            message="Repository ZIP was not downloaded successfully",
            suggestion="Failed to download repository. Please check the repo link or branch.",
            status_code=400,
        )

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise RepoDownloadError(
                    message=f"Repository ZIP is corrupted near {bad_member}",
                    suggestion="Failed to download repository. Please try again.",
                    status_code=400,
                )
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise RepoDownloadError(
            message="Downloaded repository archive is not a valid ZIP file",
            suggestion="Failed to download repository. Please check the repo link or branch.",
            status_code=400,
        ) from exc

    entries = os.listdir(extract_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
        root_dir = os.path.join(extract_dir, entries[0])
    else:
        root_dir = extract_dir

    if not os.path.isdir(root_dir):
        raise RepoDownloadError(
            message="Repository archive extracted without a valid project directory",
            suggestion="Failed to download repository. Please try again.",
            status_code=400,
        )

    return root_dir


def _score_file(rel_path: str) -> int:
    """Score a file by importance. Higher = more important."""
    path_lower = rel_path.lower().replace("\\", "/")
    basename = os.path.basename(path_lower)

    low_keywords = {"test", "spec", "mock", "dist", "build", "__pycache__", ".min.", "example"}
    for kw in low_keywords:
        if kw in path_lower:
            return 0

    high_priority = {
        "main.py", "app.py", "index.js", "index.ts", "server.py",
        "config.py", "settings.py", "package.json", "requirements.txt",
    }
    if basename in high_priority:
        return 100

    medium_keywords = {"service", "controller", "handler", "model", "route", "api", "middleware"}
    for kw in medium_keywords:
        if kw in path_lower:
            return 50

    return 20


def _select_files(root_dir: str) -> List[Dict[str, str]]:
    """Walk repo and select top files by importance."""
    candidates = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in VALID_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, root_dir)

            try:
                size = os.path.getsize(full_path)
                if size > 500_000 or size == 0:
                    continue
            except OSError:
                continue

            score = _score_file(rel_path)
            candidates.append((score, full_path, rel_path))

    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = candidates[:MAX_FILES]

    result = []
    for _score, full_path, rel_path in selected:
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(MAX_CHARS_PER_FILE)
            # Middle-trim if content exceeds limit
            if len(content) > MAX_CHARS_PER_FILE:
                head = MAX_CHARS_PER_FILE * 2 // 3
                tail = MAX_CHARS_PER_FILE // 3
                content = content[:head].rstrip() + "\n...(middle trimmed)...\n" + content[-tail:].lstrip()
            if content.strip():
                result.append({"path": rel_path, "content": content.strip()})
        except Exception:
            continue

    return result


def _build_context(files: List[Dict[str, str]]) -> str:
    """Build the LLM context string using === FILE: format."""
    parts = []
    total = 0
    for f in files:
        snippet = f"=== FILE: {f['path']} ===\n{f['content']}"
        if total + len(snippet) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total
            if remaining > 200:
                parts.append(snippet[:remaining])
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n".join(parts)


def _build_repo_structure(files: List[Dict[str, str]]) -> List[str]:
    return _dedupe([file["path"] for file in files])[:40]


def _force_non_empty(result: Dict[str, Any], files: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
    """Ensure all fields are populated using file data if needed."""
    sb = result.setdefault("summary_blocks", {})
    files = files or []

    if not result.get("key_modules"):
        result["key_modules"] = [os.path.basename(f["path"]) for f in files[:5]]

    if not result.get("core_features"):
        combined = "\n".join(f["content"] for f in files)
        functions = _dedupe(_FUNCTION_RE.findall(combined))[:4]
        classes = _dedupe(_CLASS_RE.findall(combined))[:4]
        features = []
        if functions:
            features.append(f"Defines functions: {', '.join(functions[:3])}")
        if classes:
            features.append(f"Defines classes: {', '.join(classes[:3])}")
        result["core_features"] = features or ["Repository structure analysis", "Module detection"]

    if not result.get("risks"):
        result["risks"] = ["No critical risks surfaced from sampled files"]

    if not sb.get("what"):
        sb["what"] = f"Analyzed {len(files)} repository source files"
    if not sb.get("why"):
        sb["why"] = "Extract project purpose and architecture from source code"
    if not sb.get("remaining"):
        sb["remaining"] = ["Analyze additional files for deeper coverage"]
    if not sb.get("issues"):
        sb["issues"] = ["Review recommended for production readiness"]

    result["summary_blocks"] = sb
    return result


def analyze_repo_from_url(repo_url: str) -> Dict[str, Any]:
    """
    Full repo analysis pipeline:
    1. Download ZIP from GitHub
    2. Extract to temp dir
    3. Select top files by importance
    4. Build context with truncation
    5. Call LLM with detected structure
    6. Return normalized, validated result
    """
    started_total = time.monotonic()

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "repo.zip")

        # Step 1: Download
        branch = _download_zip(repo_url, zip_path)

        # Step 2: Extract
        root_dir = _extract_zip(zip_path, temp_dir)
        if not os.path.isdir(root_dir):
            raise RepoDownloadError(
                message="Repository extraction failed",
                suggestion="Failed to download repository. Please check the repo link or branch.",
                status_code=400,
            )

        # Step 3: Select files
        files = _select_files(root_dir)
        if not files:
            raise RepoDownloadError(
                message="Repository downloaded successfully but no analyzable files were found",
                suggestion="Ensure the repository contains source files supported by the analyzer.",
                status_code=400,
            )

        selected_names = [f["path"] for f in files]
        logger.info("Repo files selected", extra={"extra_data": {
            "endpoint": "repo",
            "repo_url": repo_url,
            "branch": branch,
            "selected_files": selected_names,
            "selected_count": len(files),
        }})

        # Step 4: Build context
        context = _build_context(files)
        if not context.strip():
            raise Exception("Failed to build context from repository files")

        # Detect framework
        framework = _detect_framework(context)

        logger.info("Repo context built", extra={"extra_data": {
            "endpoint": "repo",
            "context_size": len(context),
            "framework": framework,
            "branch": branch,
        }})

        llm_started = time.monotonic()
        parsed = _run_repo_llm_enhancement(
            repo_url=repo_url,
            branch=branch,
            files=files,
            context=context,
            framework=framework,
        )
        llm_ms = round((time.monotonic() - llm_started) * 1000, 2)
        total_ms = round((time.monotonic() - started_total) * 1000, 2)

        is_fallback = str(parsed.get("summary_blocks", {}).get("why", "")).startswith("[MEDIUM confidence]")
        print(f"[REPO] LLM enhancement completed: fallback={is_fallback}, llm_time={llm_ms}ms")
        logger.info("Repo analysis complete", extra={"extra_data": {
            "endpoint": "repo",
            "mode": "online",
            "llm_time_ms": llm_ms,
            "total_time_ms": total_ms,
            "fallback": is_fallback,
            "files_selected": selected_names,
            "context_size": len(context),
        }})

        # Step 6: Validate key_modules and normalize
        result = {
            "project_goal": parsed.get("project_goal", ""),
            "architecture_style": parsed.get("architecture_style", ""),
            "key_modules": parsed.get("key_modules", []),
            "core_features": parsed.get("core_features", []),
            "risks": parsed.get("risks", []),
            "summary_blocks": parsed.get("summary_blocks", {}),
        }

        # Validate key_modules against real filenames
        valid_names = set()
        for f in files:
            valid_names.add(f["path"])
            valid_names.add(os.path.basename(f["path"]))
            valid_names.add(os.path.splitext(os.path.basename(f["path"]))[0])

        filtered_modules = [m for m in _dedupe(result.get("key_modules", [])) if m in valid_names]
        if not filtered_modules:
            filtered_modules = [os.path.basename(f["path"]) for f in files[:5]]
        result["key_modules"] = filtered_modules

        return normalize_result(_force_non_empty(result, files))


async def process_repo_analysis_session(session_id: str, repo_url: str) -> None:
    """
    Run repository analysis in the background and publish progress updates to
    the session document so the frontend can poll live status.
    """
    started_total = time.monotonic()
    await SessionRepository.update_progress(session_id, 5, "Queued repository analysis")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "repo.zip")

            await SessionRepository.update_progress(session_id, 12, "Downloading repository")
            branch = await asyncio.to_thread(_download_zip, repo_url, zip_path)

            await SessionRepository.update_progress(session_id, 22, "Extracting repository")
            root_dir = await asyncio.to_thread(_extract_zip, zip_path, temp_dir)
            if not os.path.isdir(root_dir):
                raise RepoDownloadError(
                    message="Repository extraction failed",
                    suggestion="Failed to download repository. Please check the repo link or branch.",
                    status_code=400,
                )

            await SessionRepository.update_progress(session_id, 34, "Scanning repository structure")
            files = await asyncio.to_thread(_select_files, root_dir)
            if not files:
                raise RepoDownloadError(
                    message="Repository downloaded successfully but no analyzable files were found",
                    suggestion="Ensure the repository contains source files supported by the analyzer.",
                    status_code=400,
                )

            context = await asyncio.to_thread(_build_context, files)
            if not context.strip():
                raise RepoDownloadError(
                    message="Failed to build context from repository files",
                    suggestion="Repository structure was detected but analyzable content could not be prepared.",
                    status_code=400,
                )

            framework = await asyncio.to_thread(_detect_framework, context)
            partial_result = normalize_result(_force_non_empty(_smart_repo_fallback(files, framework, branch), files))
            partial_result = normalize_result(
                enrich_result_with_intelligence(
                    session_type="repo",
                    result=partial_result,
                    sampled_files=files,
                )
            )
            structure = _build_repo_structure(files)
            await SessionRepository.update_progress(
                session_id,
                45,
                "Fast scanning repository structure",
                result=partial_result,
            )
            await SessionRepository.update_fields(
                session_id,
                source_ref=repo_url,
                structure=structure,
                summary=partial_result.get("summary_blocks", {}).get("what", ""),
            )

            await SessionRepository.update_progress(
                session_id,
                60,
                "Analyzing architecture",
                result=partial_result,
            )
            enhanced = await asyncio.to_thread(
                _run_repo_llm_enhancement,
                repo_url,
                branch,
                files,
                context,
                framework,
            )

            result = {
                "project_goal": enhanced.get("project_goal", ""),
                "architecture_style": enhanced.get("architecture_style", ""),
                "key_modules": enhanced.get("key_modules", []),
                "core_features": enhanced.get("core_features", []),
                "risks": enhanced.get("risks", []),
                "summary_blocks": enhanced.get("summary_blocks", {}),
            }

            valid_names = set()
            for file in files:
                valid_names.add(file["path"])
                valid_names.add(os.path.basename(file["path"]))
                valid_names.add(os.path.splitext(os.path.basename(file["path"]))[0])

            filtered_modules = [m for m in _dedupe(result.get("key_modules", [])) if m in valid_names]
            if not filtered_modules:
                filtered_modules = [os.path.basename(file["path"]) for file in files[:5]]
            result["key_modules"] = filtered_modules

            final_result = normalize_result(_force_non_empty(result, files))
            final_result = normalize_result(
                enrich_result_with_intelligence(
                    session_type="repo",
                    result=final_result,
                    sampled_files=files,
                )
            )
            total_ms = round((time.monotonic() - started_total) * 1000, 2)
            logger.info(
                "Background repo analysis completed",
                extra={"extra_data": {"session_id": session_id, "repo_url": repo_url, "total_time_ms": total_ms}},
            )
            await persist_analysis_knowledge(
                session_id=session_id,
                session_type=SessionType.REPO,
                title=f"Repo: {repo_url.rstrip('/').split('/')[-1] or 'repository'}",
                source_ref=repo_url,
                structure=structure,
                result=final_result,
                sampled_files=files,
                tech_stack=[framework] if framework and framework != "general" else [],
                status=SessionStatus.COMPLETED,
            )
            await SessionRepository.update_status(
                session_id=session_id,
                status=SessionStatus.COMPLETED,
                progress=100,
                stage="Analysis complete",
                result=final_result,
            )
            await SessionRepository.update_fields(
                session_id,
                source_ref=repo_url,
                structure=structure,
                summary=final_result.get("summary_blocks", {}).get("what", ""),
            )

    except Exception as exc:
        logger.error(f"Background repo analysis failed for {session_id}: {exc}")
        print(f"REPO BACKGROUND ERROR: {exc}")
        existing_session = await SessionRepository.get_by_id(session_id)
        partial_result = None
        if existing_session and existing_session.result is not None:
            partial_result = (
                existing_session.result.model_dump()
                if hasattr(existing_session.result, "model_dump")
                else dict(existing_session.result)
            )
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="Partial analysis completed",
            result=partial_result,
            error="Partial analysis completed. Full analysis can continue from the latest stored intelligence.",
        )
