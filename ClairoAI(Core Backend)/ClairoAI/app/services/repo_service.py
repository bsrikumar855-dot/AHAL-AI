"""
Repository analysis service.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List

import requests

from app.core.logging import get_logger
from app.db.models import SessionStatus
from app.db.repository import SessionRepository
from app.services.llm_handler import call_llm

logger = get_logger("services.repo")

VALID_EXTENSIONS = {".py", ".js", ".ts", ".json", ".jsx", ".tsx", ".md", ".txt", ".yml", ".yaml", ".toml", ".html", ".css"}
IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
MAX_FILES = 10
MAX_CHARS_PER_FILE = 1500
MAX_CONTEXT_CHARS = 8000
DOWNLOAD_TIMEOUT = 20
LLM_TIMEOUT = 90
GITHUB_API_TIMEOUT = 15
GITHUB_BRANCH_FALLBACKS = ("main", "master", "dev")

REPO_ANALYSIS_PROMPT = """You MUST return valid JSON.

Analyze this GitHub repository's source files and return ONLY valid JSON.

REPOSITORY FILES:
{context}

DETECTED STRUCTURE:
- File count: {file_count}
- Framework hints: {framework_hints}
- Key filenames: {filenames}

OUTPUT (JSON only - no markdown, no explanation):
{{
  "project_goal": "one sentence: what this project does",
  "architecture_style": "specific label",
  "key_modules": [],
  "core_features": [],
  "risks": [],
  "summary_blocks": {{
    "what": "precise summary of the project",
    "why": "why this project exists",
    "remaining": [],
    "issues": []
  }}
}}
"""


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


def _detect_framework(context: str) -> str:
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


def _normalize_summary_blocks(summary_blocks: Any, file_count: int) -> Dict[str, Any]:
    payload = summary_blocks if isinstance(summary_blocks, dict) else {}
    return {
        "what": str(payload.get("what", "")).strip() or f"Repository snapshot with {file_count} non-empty text files.",
        "why": str(payload.get("why", "")).strip() or "Provides repository files for inspection.",
        "remaining": _dedupe([str(x) for x in payload.get("remaining", []) if str(x).strip()]),
        "issues": _dedupe([str(x) for x in payload.get("issues", []) if str(x).strip()]),
    }


def _call_repo_llm(prompt: str, timeout: int, label: str) -> Dict[str, Any]:
    started = time.monotonic()
    parsed = call_llm(
        prompt,
        timeout=timeout,
        simplified_prompt=prompt,
        mode="online",
    )
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    print(f"[REPO][{label}] LLM latency: {latency_ms}ms")
    if not isinstance(parsed, dict) or not parsed:
        raise Exception("LLM returned empty response")
    return parsed


def _run_repo_llm_enhancement(
    repo_url: str,
    branch: str,
    files: List[Dict[str, str]],
    context: str,
    framework: str,
) -> Dict[str, Any]:
    full_prompt = REPO_ANALYSIS_PROMPT.format(
        context=context,
        file_count=len(files),
        framework_hints=framework,
        filenames=", ".join(os.path.basename(f["path"]) for f in files),
    )
    print(f"[REPO] files_sent={len(files)}, context_size={len(context)}, prompt_size={len(full_prompt)}, branch={branch}")
    return _call_repo_llm(full_prompt, LLM_TIMEOUT, "full")


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
    owner, repo = _parse_github_repo_url(repo_url)
    branch_candidates = _resolve_branch_candidates(owner, repo)
    last_response: requests.Response | None = None

    for branch in branch_candidates:
        zip_url = _repo_zip_url(owner, repo, branch)
        response = requests.get(
            zip_url,
            headers=_github_api_headers(),
            timeout=DOWNLOAD_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
        last_response = response

        if response.status_code == 404:
            continue
        if response.status_code in {401, 403}:
            raise RepoDownloadError(
                message="Repository not found or is private",
                suggestion="Ensure the repo is public or provide access token",
                status_code=response.status_code,
            )

        response.raise_for_status()
        with open(dest_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file_handle.write(chunk)

        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            raise RepoDownloadError(
                message="Downloaded repository archive is empty",
                suggestion="Failed to download repository. Please check the repo link or branch.",
                status_code=502,
            )

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
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
        raise RepoDownloadError(
            message="Repository ZIP was not downloaded successfully",
            suggestion="Failed to download repository. Please check the repo link or branch.",
            status_code=400,
        )

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            bad_member = zip_file.testzip()
            if bad_member is not None:
                raise RepoDownloadError(
                    message=f"Repository ZIP is corrupted near {bad_member}",
                    suggestion="Failed to download repository. Please try again.",
                    status_code=400,
                )
            zip_file.extractall(extract_dir)
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


def _select_files(root_dir: str) -> List[Dict[str, str]]:
    all_files: List[Dict[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [directory for directory in dirnames if directory not in IGNORE_DIRS]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
            ext = os.path.splitext(filename)[1].lower()

            if ext and ext not in VALID_EXTENSIONS:
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as file_handle:
                    content = file_handle.read()
            except Exception:
                continue

            if "\x00" in content:
                continue

            content = content.strip()
            if not content:
                continue

            if len(content) > MAX_CHARS_PER_FILE:
                content = content[:MAX_CHARS_PER_FILE]

            all_files.append({"path": rel_path, "content": content})

    valid_files = all_files[:MAX_FILES]
    if not valid_files:
        valid_files = all_files[:10]
    return valid_files


def _build_context(files: List[Dict[str, str]]) -> str:
    parts = []
    total = 0
    for file_info in files:
        snippet = f"=== FILE: {file_info['path']} ===\n{file_info['content']}"
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


def generate_minimal_analysis(files: List[Dict[str, str]], repo_ref: str) -> Dict[str, Any]:
    paths = [file_info["path"] for file_info in files if str(file_info.get("content", "")).strip()]
    context = _build_context(files) if files else ""
    framework = _detect_framework(context) if context else "general"
    return {
        "project_goal": "Repository source snapshot for inspection.",
        "architecture_style": framework,
        "key_modules": paths[:8],
        "core_features": [],
        "risks": [],
        "summary_blocks": {
            "what": f"Repository input `{repo_ref}` produced {len(paths)} non-empty text files.",
            "why": "Provides repository files for analysis.",
            "remaining": [],
            "issues": [],
        },
    }


def analyze_repo_from_url(repo_url: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "repo.zip")
        branch = _download_zip(repo_url, zip_path)
        root_dir = _extract_zip(zip_path, temp_dir)
        files = _select_files(root_dir)
        if not files:
            return generate_minimal_analysis([], repo_url)

        context = _build_context(files)
        if not context.strip():
            return generate_minimal_analysis(files, repo_url)

        framework = _detect_framework(context)

        try:
            parsed = _run_repo_llm_enhancement(
                repo_url=repo_url,
                branch=branch,
                files=files,
                context=context,
                framework=framework,
            )
            summary_blocks = _normalize_summary_blocks(parsed.get("summary_blocks", {}), len(files))
            result = {
                "project_goal": str(parsed.get("project_goal", "")).strip() or "Repository source snapshot for inspection.",
                "architecture_style": str(parsed.get("architecture_style", "")).strip() or framework,
                "key_modules": _dedupe([str(x) for x in parsed.get("key_modules", []) if str(x).strip()]),
                "core_features": _dedupe([str(x) for x in parsed.get("core_features", []) if str(x).strip()]),
                "risks": _dedupe([str(x) for x in parsed.get("risks", []) if str(x).strip()]),
                "summary_blocks": summary_blocks,
            }
            valid_names = set()
            for file_info in files:
                valid_names.add(file_info["path"])
                valid_names.add(os.path.basename(file_info["path"]))
                valid_names.add(os.path.splitext(os.path.basename(file_info["path"]))[0])
            result["key_modules"] = [
                module for module in result["key_modules"]
                if module in valid_names
            ]
            if not result["key_modules"]:
                result["key_modules"] = [file_info["path"] for file_info in files[:8]]
            return result
        except Exception:
            return generate_minimal_analysis(files, repo_url)


async def process_repo_analysis_session(session_id: str, repo_url: str) -> None:
    await SessionRepository.update_progress(session_id, 5, "Queued repository analysis")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "repo.zip")

            await SessionRepository.update_progress(session_id, 12, "Downloading repository")
            branch = await asyncio.to_thread(_download_zip, repo_url, zip_path)

            await SessionRepository.update_progress(session_id, 22, "Extracting repository")
            root_dir = await asyncio.to_thread(_extract_zip, zip_path, temp_dir)

            await SessionRepository.update_progress(session_id, 34, "Scanning repository structure")
            files = await asyncio.to_thread(_select_files, root_dir)
            structure = _build_repo_structure(files)
            await SessionRepository.update_fields(
                session_id,
                source_ref=repo_url,
                structure=structure,
                summary="",
            )

            if not files:
                final_result = generate_minimal_analysis([], repo_url)
            else:
                context = await asyncio.to_thread(_build_context, files)
                if not context.strip():
                    final_result = generate_minimal_analysis(files, repo_url)
                else:
                    framework = await asyncio.to_thread(_detect_framework, context)
                    await SessionRepository.update_progress(session_id, 60, "Calling LLM", result=None)
                    try:
                        enhanced = await asyncio.to_thread(
                            _run_repo_llm_enhancement,
                            repo_url,
                            branch,
                            files,
                            context,
                            framework,
                        )
                        summary_blocks = _normalize_summary_blocks(enhanced.get("summary_blocks", {}), len(files))
                        final_result = {
                            "project_goal": str(enhanced.get("project_goal", "")).strip() or "Repository source snapshot for inspection.",
                            "architecture_style": str(enhanced.get("architecture_style", "")).strip() or framework,
                            "key_modules": _dedupe([str(x) for x in enhanced.get("key_modules", []) if str(x).strip()]),
                            "core_features": _dedupe([str(x) for x in enhanced.get("core_features", []) if str(x).strip()]),
                            "risks": _dedupe([str(x) for x in enhanced.get("risks", []) if str(x).strip()]),
                            "summary_blocks": summary_blocks,
                        }
                        valid_names = set()
                        for file_info in files:
                            valid_names.add(file_info["path"])
                            valid_names.add(os.path.basename(file_info["path"]))
                            valid_names.add(os.path.splitext(os.path.basename(file_info["path"]))[0])
                        final_result["key_modules"] = [
                            module for module in final_result["key_modules"]
                            if module in valid_names
                        ]
                        if not final_result["key_modules"]:
                            final_result["key_modules"] = [file_info["path"] for file_info in files[:8]]
                    except Exception:
                        final_result = generate_minimal_analysis(files, repo_url)

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
        fallback_result = generate_minimal_analysis([], repo_url)
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="Analysis complete",
            result=fallback_result,
        )
        await SessionRepository.update_fields(
            session_id,
            source_ref=repo_url,
            structure=[],
            summary=fallback_result.get("summary_blocks", {}).get("what", ""),
        )
