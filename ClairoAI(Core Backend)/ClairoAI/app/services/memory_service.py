"""
Session memory and personalized context engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.db.models import MemoryProfileDocument, SessionType
from app.db.repository import MemoryProfileRepository


def _dedupe(items: Iterable[str], limit: int = 12) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in items:
        cleaned = " ".join(str(item).split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


async def get_or_create_memory_profile(session_id: str, session_type: str) -> MemoryProfileDocument:
    existing = await MemoryProfileRepository.get_by_session_id(session_id)
    if existing:
        return existing
    profile = MemoryProfileDocument(
        session_id=session_id,
        session_type=SessionType(session_type if session_type in {"code", "folder", "repo"} else "code"),
    )
    await MemoryProfileRepository.upsert(profile)
    return profile


async def update_session_focus(
    session_id: str,
    session_type: str,
    *,
    focus: str = "",
    module: str = "",
    workflow: str = "",
    file_path: str = "",
) -> Dict[str, Any]:
    profile = await get_or_create_memory_profile(session_id, session_type)
    if focus:
        profile.focus = focus
    if module:
        profile.modules_viewed = _dedupe([module] + profile.modules_viewed, 20)
        profile.important_modules = _dedupe([module] + profile.important_modules, 20)
    if workflow:
        profile.workflows_viewed = _dedupe([workflow] + profile.workflows_viewed, 20)
    if file_path:
        profile.files_viewed = _dedupe([file_path] + profile.files_viewed, 20)
    profile.updated_at = datetime.now(timezone.utc)
    await MemoryProfileRepository.upsert(profile)
    return profile.model_dump()


async def record_chat_turn(
    session_id: str,
    session_type: str,
    question: str,
    answer: str,
    modules_involved: List[str] | None = None,
) -> Dict[str, Any]:
    profile = await get_or_create_memory_profile(session_id, session_type)
    profile.previous_questions = _dedupe([question] + profile.previous_questions, 12)
    profile.previous_answers = _dedupe([answer] + profile.previous_answers, 12)
    if modules_involved:
        profile.important_modules = _dedupe(list(modules_involved) + profile.important_modules, 20)
    profile.updated_at = datetime.now(timezone.utc)
    await MemoryProfileRepository.upsert(profile)
    return profile.model_dump()


async def get_memory_profile(session_id: str) -> Dict[str, Any] | None:
    profile = await MemoryProfileRepository.get_by_session_id(session_id)
    return profile.model_dump() if profile else None
