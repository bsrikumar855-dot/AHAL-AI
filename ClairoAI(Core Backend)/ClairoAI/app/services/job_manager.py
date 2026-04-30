"""
Shared background job orchestration for analysis sessions.

This keeps the request thread fast while analysis deepens in the background.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Coroutine, Dict, Set

from app.core.logging import get_logger
from app.db.models import SessionStatus
from app.db.repository import SessionRepository
from app.services.analysis_service import update_task_record
from app.services.code_analyzer import CodeAnalyzer
from app.services.folder_analyzer import FolderAnalyzer
from app.services.llm_handler import LLM_TIMEOUT_BACKGROUND
from app.services.repo_service import process_repo_analysis_session

logger = get_logger("services.job_manager")

_BACKGROUND_TASKS: Set[asyncio.Task] = set()
_TASKS_BY_JOB_ID: Dict[str, asyncio.Task] = {}
_JOB_RUNTIME_CACHE: Dict[str, Dict[str, Any]] = {}
_CODE_JOB_TIMEOUT_SECONDS = 90
_FOLDER_JOB_TIMEOUT_SECONDS = 90
_JOB_MAX_ATTEMPTS = 3
_JOB_RETRY_BASE_DELAY_SECONDS = 1.0
_GENERIC_RESULT_MARKERS = (
    "codebase centered on llm prompt handling",
    "repository source snapshot for inspection",
    "repository input `",
    "uploaded archive `",
    "project archive contains",
    "project archive with",
    "repository snapshot with",
    "software project with prioritized entrypoints",
    "software project composed of entrypoints",
    "fastapi-based backend service that exposes api routes and application logic",
    "fastapi-based backend service that exposes api endpoints and coordinates application logic",
    "flask-based web service that handles routed requests",
    "backend api service that organizes request routing",
    "frontend interface for a wider product workflow",
)


def _cache_job_state(
    job_id: str,
    *,
    status: str,
    progress: int,
    stage: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    snapshot = _JOB_RUNTIME_CACHE.get(job_id, {})
    snapshot.update(
        {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "stage": stage,
            "error": error,
        }
    )
    if result is not None:
        snapshot["result"] = result
    _JOB_RUNTIME_CACHE[job_id] = snapshot
    update_task_record(
        job_id,
        status=status,
        progress=progress,
        stage=stage,
        result=result,
        error=error,
    )


def get_cached_job_state(job_id: str) -> Dict[str, Any] | None:
    snapshot = _JOB_RUNTIME_CACHE.get(job_id)
    return dict(snapshot) if snapshot else None


def start_background_job(job_id: str, coro: Coroutine[object, object, None]) -> None:
    existing = _TASKS_BY_JOB_ID.get(job_id)
    if existing and not existing.done():
        if hasattr(coro, "close"):
            coro.close()
        logger.info(
            "Background job already running; skipping duplicate launch",
            extra={"extra_data": {"session_id": job_id}},
        )
        return

    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    _TASKS_BY_JOB_ID[job_id] = task
    _cache_job_state(job_id, status="processing", progress=0, stage="upload")

    def _cleanup(completed_task: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(completed_task)
        current = _TASKS_BY_JOB_ID.get(job_id)
        if current is completed_task:
            _TASKS_BY_JOB_ID.pop(job_id, None)

    task.add_done_callback(_cleanup)


def _is_valid_final_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False

    summary_blocks = result.get("summary_blocks", {}) if isinstance(result.get("summary_blocks"), dict) else {}
    insights = result.get("insights", [])
    required_string_fields = ("project_goal", "domain", "purpose", "target_users")
    for field in required_string_fields:
        if not str(result.get(field, "")).strip():
            return False
    if not isinstance(insights, list):
        return False

    project_goal = str(result.get("project_goal", "")).strip()
    summary_what = str(summary_blocks.get("what", "")).strip()
    summary_why = str(summary_blocks.get("why", "")).strip()
    if not project_goal or not summary_what or not summary_why:
        return False

    combined = f"{project_goal} {summary_what} {summary_why}".lower()
    return not any(marker in combined for marker in _GENERIC_RESULT_MARKERS)


def _coerce_final_result(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return result

    coerced = dict(result)
    coerced["project_goal"] = str(coerced.get("project_goal", "")).strip() or "Not enough information"
    coerced["domain"] = str(coerced.get("domain", "")).strip() or "Not enough information"
    coerced["purpose"] = str(coerced.get("purpose", "")).strip() or "Not enough information"
    coerced["target_users"] = str(coerced.get("target_users", "")).strip() or "Not enough information"
    if not isinstance(coerced.get("insights"), list):
        coerced["insights"] = []

    summary_blocks = coerced.get("summary_blocks", {}) if isinstance(coerced.get("summary_blocks"), dict) else {}
    summary_what = str(summary_blocks.get("what", "")).strip() or coerced["project_goal"]
    summary_why = str(summary_blocks.get("why", "")).strip() or "Not enough information"
    summary_blocks["what"] = summary_what
    summary_blocks["why"] = summary_why
    coerced["summary_blocks"] = summary_blocks
    coerced["summary"] = {"what": summary_what, "why": summary_why}
    return coerced


def _build_recovered_result(result: dict | None, label: str, error: Exception | str | None = None) -> dict:
    base = _coerce_final_result(result if isinstance(result, dict) else {}) or {}
    summary_text = str(base.get("project_goal", "")).strip() or "Analysis failed but recovered"
    architecture_name = str(base.get("architecture_style", "")).strip() or "Not enough information"
    recovered = dict(base)
    recovered["project_goal"] = summary_text
    recovered["domain"] = str(recovered.get("domain", "")).strip() or "Not enough information"
    recovered["purpose"] = str(recovered.get("purpose", "")).strip() or "Not enough information"
    recovered["target_users"] = str(recovered.get("target_users", "")).strip() or "Not enough information"
    recovered["key_modules"] = list(recovered.get("key_modules", [])) if isinstance(recovered.get("key_modules", []), list) else []
    recovered["risks"] = list(recovered.get("risks", [])) if isinstance(recovered.get("risks", []), list) else []
    recovered["summary_blocks"] = {
        "what": summary_text,
        "why": f"{label} produced a recovered fallback result after validation or parsing issues.",
        "remaining": [],
        "issues": list(dict.fromkeys([*recovered["risks"][:2], str(error or "Recovered from invalid final result")])),
    }
    recovered["summary"] = {
        "what": summary_text,
        "why": recovered["summary_blocks"]["why"],
    }
    recovered["architecture"] = {"style": architecture_name}
    recovered["modules"] = list(recovered["key_modules"])
    recovered["summary_text"] = summary_text
    return recovered


def _is_background_timeout_error(error: Exception | str | None) -> bool:
    return LLM_TIMEOUT_BACKGROUND.lower() in str(error or "").lower()


async def _run_job_attempts(
    *,
    session_id: str,
    label: str,
    timeout_seconds: int,
    progress_base: int,
    analysis_factory: Callable[[], Awaitable[dict]],
) -> dict:
    last_error: Exception | None = None

    for attempt in range(1, _JOB_MAX_ATTEMPTS + 1):
        try:
            logger.info(
                f"{label} LLM start",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt}},
            )
            await SessionRepository.update_status(
                session_id=session_id,
                status=SessionStatus.PROCESSING,
                progress=min(95, progress_base + (attempt * 5)),
                stage="insights",
            )
            _cache_job_state(
                session_id,
                status=SessionStatus.PROCESSING.value,
                progress=min(95, progress_base + (attempt * 5)),
                stage="insights",
            )
            final_result = await asyncio.wait_for(analysis_factory(), timeout=timeout_seconds)
            final_result = _coerce_final_result(final_result)
            if not _is_valid_final_result(final_result):
                logger.warning(
                    "Invalid final result recovered",
                    extra={"extra_data": {"session_id": session_id, "attempt": attempt, "label": label}},
                )
                final_result = _build_recovered_result(final_result, label, "INVALID_FINAL_RESULT")
            logger.info(
                f"{label} LLM success",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt}},
            )
            return final_result
        except Exception as exc:
            last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
            if _is_background_timeout_error(last_error):
                await SessionRepository.update_status(
                    session_id=session_id,
                    status=SessionStatus.PROCESSING,
                    progress=min(95, progress_base + (attempt * 5)),
                    stage="insights",
                    error=LLM_TIMEOUT_BACKGROUND,
                )
                _cache_job_state(
                    session_id,
                    status=SessionStatus.PROCESSING.value,
                    progress=min(95, progress_base + (attempt * 5)),
                    stage="insights",
                    error=LLM_TIMEOUT_BACKGROUND,
                )
                raise
            logger.error(
                f"{label} LLM failure",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt, "error": str(last_error)}},
            )
            if attempt < _JOB_MAX_ATTEMPTS:
                backoff_seconds = _JOB_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                await SessionRepository.update_status(
                    session_id=session_id,
                    status=SessionStatus.PROCESSING,
                    progress=min(95, progress_base + (attempt * 5)),
                    stage="insights",
                )
                _cache_job_state(
                    session_id,
                    status=SessionStatus.PROCESSING.value,
                    progress=min(95, progress_base + (attempt * 5)),
                    stage="insights",
                    error=str(last_error),
                )
                await asyncio.sleep(backoff_seconds)

    raise RuntimeError(f"{label} failed after {_JOB_MAX_ATTEMPTS} attempts: {last_error}")


async def process_code_analysis_session(
    session_id: str,
    code: str,
    mode: str = "online",
) -> None:
    started = time.monotonic()
    analyzer = CodeAnalyzer()
    partial_result: dict | None = None

    try:
        await SessionRepository.update_progress(session_id, 5, "upload")
        _cache_job_state(session_id, status=SessionStatus.PROCESSING.value, progress=5, stage="upload")
        quick_result = analyzer.build_quick_result(code)
        partial_result = quick_result
        structure = quick_result.get("key_modules", [])[:20]
        await SessionRepository.update_fields(
            session_id,
            source_ref="inline-code",
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
        )
        await SessionRepository.update_progress(
            session_id,
            35,
            "analyze",
            result=quick_result,
        )
        _cache_job_state(session_id, status=SessionStatus.PROCESSING.value, progress=35, stage="analyze", result=quick_result)

        final_result = await _run_job_attempts(
            session_id=session_id,
            label="Code analysis",
            timeout_seconds=_CODE_JOB_TIMEOUT_SECONDS,
            progress_base=70,
            analysis_factory=lambda: analyzer.analyze(code, mode=mode),
        )

        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="finalize",
            result=final_result,
        )
        await SessionRepository.update_fields(
            session_id,
            summary=final_result.get("summary_blocks", {}).get("what", ""),
            error=None,
        )
        _cache_job_state(
            session_id,
            status=SessionStatus.COMPLETED.value,
            progress=100,
            stage="finalize",
            result=final_result,
            error=None,
        )
        logger.info(
            "Code analysis background job completed",
            extra={"extra_data": {"session_id": session_id, "latency_ms": round((time.monotonic() - started) * 1000, 2)}},
        )
    except Exception as exc:
        if _is_background_timeout_error(exc):
            logger.warning(
                "Code analysis continues after timeout",
                extra={"extra_data": {"session_id": session_id, "error": str(exc)}},
            )
            return
        logger.error(
            "Code analysis background job failed",
            extra={"extra_data": {"session_id": session_id, "error": str(exc)}},
        )
        if partial_result is None:
            partial_result = _build_recovered_result(None, "Code analysis", exc)
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            progress=100,
            stage="finalize",
            result=partial_result,
            error=str(exc),
        )
        _cache_job_state(
            session_id,
            status=SessionStatus.FAILED.value,
            progress=100,
            stage="finalize",
            result=partial_result,
            error=str(exc),
        )


async def process_folder_analysis_session(
    session_id: str,
    file_bytes: bytes,
    filename: str,
    mode: str = "online",
) -> None:
    started = time.monotonic()
    analyzer = FolderAnalyzer()
    partial_result: dict | None = None

    try:
        await SessionRepository.update_progress(session_id, 5, "upload")
        _cache_job_state(session_id, status=SessionStatus.PROCESSING.value, progress=5, stage="upload")
        file_contents, selected_files, _arch_hints, quick_result = await asyncio.wait_for(
            analyzer.prepare_analysis(file_bytes, filename),
            timeout=5,
        )
        partial_result = quick_result
        structure = list(selected_files.keys())[:30]
        await SessionRepository.update_fields(
            session_id,
            source_ref=filename,
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
        )
        await SessionRepository.update_progress(session_id, 30, "analyze", result=quick_result)
        _cache_job_state(session_id, status=SessionStatus.PROCESSING.value, progress=30, stage="analyze", result=quick_result)

        final_result = await _run_job_attempts(
            session_id=session_id,
            label="Folder analysis",
            timeout_seconds=_FOLDER_JOB_TIMEOUT_SECONDS,
            progress_base=65,
            analysis_factory=lambda: analyzer.analyze_prepared(
                file_contents=file_contents,
                selected_files=selected_files,
                arch_hints=_arch_hints,
                minimal_result=quick_result,
                filename=filename,
                mode=mode,
            ),
        )

        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="finalize",
            result=final_result,
        )
        await SessionRepository.update_fields(
            session_id,
            summary=final_result.get("summary_blocks", {}).get("what", ""),
            error=None,
        )
        _cache_job_state(
            session_id,
            status=SessionStatus.COMPLETED.value,
            progress=100,
            stage="finalize",
            result=final_result,
            error=None,
        )
        logger.info(
            "Folder analysis background job completed",
            extra={"extra_data": {"session_id": session_id, "latency_ms": round((time.monotonic() - started) * 1000, 2)}},
        )
    except Exception as exc:
        if _is_background_timeout_error(exc):
            logger.warning(
                "Folder analysis continues after timeout",
                extra={"extra_data": {"session_id": session_id, "error": str(exc)}},
            )
            return
        logger.error(
            "Folder analysis background job failed",
            extra={"extra_data": {"session_id": session_id, "error": str(exc)}},
        )
        if partial_result is None:
            partial_result = analyzer.generate_minimal_analysis({}, filename)
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FAILED,
            progress=100,
            stage="finalize",
            result=partial_result,
            error=str(exc),
        )
        _cache_job_state(
            session_id,
            status=SessionStatus.FAILED.value,
            progress=100,
            stage="finalize",
            result=partial_result,
            error=str(exc),
        )


async def process_repo_analysis_job(session_id: str, repo_url: str) -> None:
    last_error: Exception | None = None
    for attempt in range(1, _JOB_MAX_ATTEMPTS + 1):
        try:
            logger.info(
                "Repo analysis LLM start",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt}},
            )
            await process_repo_analysis_session(session_id, repo_url)
            logger.info(
                "Repo analysis LLM success",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt}},
            )
            session = await SessionRepository.get_by_id(session_id)
            final_result = session.result.model_dump() if session and hasattr(session.result, "model_dump") else session.result if session else None
            _cache_job_state(
                session_id,
                status=SessionStatus.COMPLETED.value,
                progress=100,
                stage="finalize",
                result=final_result if isinstance(final_result, dict) else None,
                error=None,
            )
            return
        except Exception as exc:
            last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
            if _is_background_timeout_error(last_error):
                await SessionRepository.update_status(
                    session_id=session_id,
                    status=SessionStatus.PROCESSING,
                    progress=min(95, 70 + (attempt * 5)),
                    stage="insights",
                    error=LLM_TIMEOUT_BACKGROUND,
                )
                _cache_job_state(
                    session_id,
                    status=SessionStatus.PROCESSING.value,
                    progress=min(95, 70 + (attempt * 5)),
                    stage="insights",
                    error=LLM_TIMEOUT_BACKGROUND,
                )
                return
            logger.error(
                "Repo analysis LLM failure",
                extra={"extra_data": {"session_id": session_id, "attempt": attempt, "error": str(last_error)}},
            )
            if attempt < _JOB_MAX_ATTEMPTS:
                backoff_seconds = _JOB_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                await SessionRepository.update_status(
                    session_id=session_id,
                    status=SessionStatus.PROCESSING,
                    progress=min(95, 70 + (attempt * 5)),
                    stage="insights",
                )
                _cache_job_state(
                    session_id,
                    status=SessionStatus.PROCESSING.value,
                    progress=min(95, 70 + (attempt * 5)),
                    stage="insights",
                    error=str(last_error),
                )
                await asyncio.sleep(backoff_seconds)

    await SessionRepository.update_status(
        session_id=session_id,
        status=SessionStatus.FAILED,
        progress=100,
        stage="finalize",
        error=str(last_error or "Repository analysis failed"),
    )
    _cache_job_state(
        session_id,
        status=SessionStatus.FAILED.value,
        progress=100,
        stage="finalize",
        error=str(last_error or "Repository analysis failed"),
    )
