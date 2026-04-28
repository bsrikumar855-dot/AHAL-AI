"""
Shared background job orchestration for analysis sessions.

This keeps the request thread fast while analysis deepens in the background.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable, Coroutine, Set

from app.core.logging import get_logger
from app.db.models import SessionStatus, SessionType
from app.db.repository import SessionRepository
from app.services.code_analyzer import CodeAnalyzer
from app.services.folder_analyzer import FolderAnalyzer
from app.services.knowledge_store import persist_analysis_knowledge
from app.services.repo_service import process_repo_analysis_session

logger = get_logger("services.job_manager")

_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def start_background_job(coro: Coroutine[object, object, None]) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def process_code_analysis_session(
    session_id: str,
    code: str,
    mode: str = "online",
) -> None:
    started = time.monotonic()
    analyzer = CodeAnalyzer()

    try:
        await SessionRepository.update_progress(session_id, 10, "Queued code analysis")
        quick_result = analyzer.build_quick_result(code)
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
            "Static code scan completed",
            result=quick_result,
        )

        await SessionRepository.update_progress(session_id, 70, "Analyzing code semantics", result=quick_result)
        final_result = await analyzer.analyze(code, mode=mode)

        await persist_analysis_knowledge(
            session_id=session_id,
            session_type=SessionType.CODE,
            title="Code Analysis",
            source_ref="inline-code",
            structure=structure,
            result=final_result,
            sampled_files=[{"path": "inline_code.py", "content": code[:12000]}],
            tech_stack=[final_result.get("architecture_style", "")],
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
            summary=final_result.get("summary_blocks", {}).get("what", ""),
        )
        logger.info(
            "Code analysis background job completed",
            extra={"extra_data": {"session_id": session_id, "latency_ms": round((time.monotonic() - started) * 1000, 2)}},
        )
    except Exception as exc:
        logger.error(f"Code analysis background job failed for {session_id}: {exc}")
        existing = await SessionRepository.get_by_id(session_id)
        partial_result = None
        if existing and existing.result is not None:
            partial_result = existing.result.model_dump() if hasattr(existing.result, "model_dump") else dict(existing.result)
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="Partial analysis completed",
            result=partial_result,
            error="Partial analysis completed. Full analysis can continue from the latest stored intelligence.",
        )


async def process_folder_analysis_session(
    session_id: str,
    file_bytes: bytes,
    filename: str,
    mode: str = "online",
) -> None:
    started = time.monotonic()
    analyzer = FolderAnalyzer()

    try:
        await SessionRepository.update_progress(session_id, 10, "Queued folder analysis")
        _file_contents, selected_files, arch_hints, quick_result = await analyzer.prepare_analysis(file_bytes, filename)
        structure = list(selected_files.keys())[:30]
        await SessionRepository.update_fields(
            session_id,
            source_ref=filename,
            structure=structure,
            summary=quick_result.get("summary_blocks", {}).get("what", ""),
        )
        await SessionRepository.update_progress(
            session_id,
            30,
            "Static project scan completed",
            result=quick_result,
        )
        await SessionRepository.update_progress(session_id, 65, "Analyzing architecture", result=quick_result)
        final_result = await analyzer.analyze(file_bytes, filename, mode=mode)

        tech_stack = [arch_hints] if arch_hints and arch_hints != "general code repository" else []
        sampled_files = [{"path": path, "content": content} for path, content in selected_files.items()]
        await persist_analysis_knowledge(
            session_id=session_id,
            session_type=SessionType.FOLDER,
            title=f"Project: {filename}",
            source_ref=filename,
            structure=structure,
            result=final_result,
            sampled_files=sampled_files,
            tech_stack=tech_stack,
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
            summary=final_result.get("summary_blocks", {}).get("what", ""),
        )
        logger.info(
            "Folder analysis background job completed",
            extra={"extra_data": {"session_id": session_id, "latency_ms": round((time.monotonic() - started) * 1000, 2)}},
        )
    except Exception as exc:
        logger.error(f"Folder analysis background job failed for {session_id}: {exc}")
        existing = await SessionRepository.get_by_id(session_id)
        partial_result = None
        if existing and existing.result is not None:
            partial_result = existing.result.model_dump() if hasattr(existing.result, "model_dump") else dict(existing.result)
        await SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            progress=100,
            stage="Partial analysis completed",
            result=partial_result,
            error="Partial analysis completed. Full analysis can continue from the latest stored intelligence.",
        )


async def process_repo_analysis_job(session_id: str, repo_url: str) -> None:
    await process_repo_analysis_session(session_id, repo_url)
