"""
Summarization orchestrator.

Coordinates the full pipeline:
    Preprocess → Chunk (if needed) → LLM Summarize → Merge → Postprocess → Store

This service is called by the background worker, never directly by API endpoints.
"""

from typing import Optional

from app.db.models import SummaryDocument, InputType, JobStatus
from app.db.repository import SummaryRepository
from app.services.llm.factory import get_llm_provider
from app.services.preprocessor import (
    preprocess_diff,
    preprocess_commit,
    preprocess_project_files,
    chunk_text,
)
from app.services.postprocessor import postprocess_summary, deduplicate_check
from app.core.logging import get_logger
from app.core.exceptions import LLMError

logger = get_logger("summarizer")


class SummarizationService:
    """
    Orchestrates code-to-summary transformation.

    Handles the full lifecycle from raw input to stored document,
    including chunking for large inputs and multi-chunk merging.
    """

    def __init__(self):
        self.llm = get_llm_provider("summarize")

    async def summarize(
        self,
        input_content: str,
        input_type: InputType,
        project: str = "default",
        file_contents: Optional[dict] = None,
    ) -> SummaryDocument:
        """
        Run the complete summarization pipeline.

        Args:
            input_content: Raw diff, commit message, or pre-processed text
            input_type:    Type of input (diff, commit, project)
            project:       Project identifier
            file_contents: Dict of file paths → content (for project uploads)

        Returns:
            A fully processed and stored SummaryDocument.
        """
        logger.info(
            f"Starting summarization pipeline",
            extra={"extra_data": {
                "input_type": input_type.value,
                "project": project,
                "input_length": len(input_content),
            }},
        )

        # ── Step 1: Preprocess ───────────────────────────────────
        if input_type == InputType.DIFF:
            processed = preprocess_diff(input_content)
        elif input_type == InputType.COMMIT:
            processed = preprocess_commit(input_content)
        elif input_type == InputType.PROJECT and file_contents:
            processed = preprocess_project_files(file_contents)
        else:
            processed = input_content

        # ── Step 2: Chunk if needed ──────────────────────────────
        chunks = chunk_text(processed)
        logger.info(f"Input split into {len(chunks)} chunk(s)")

        # ── Step 3: LLM Summarize ───────────────────────────────
        if len(chunks) == 1:
            raw_summary = await self.llm.summarize(chunks[0])
        else:
            raw_summary = await self._summarize_chunks(chunks)

        # ── Step 4: Post-process ─────────────────────────────────
        summary_content, flagged = postprocess_summary(raw_summary, processed)

        # ── Step 5: Dedup check ──────────────────────────────────
        recent = await SummaryRepository.find_recent(project=project, limit=3)
        for existing in recent:
            existing_text = " ".join([
                existing.summary.what_done.text,
                existing.summary.why_done.text,
                existing.summary.what_remains.text,
                existing.summary.potential_issues.text,
            ])
            if deduplicate_check(summary_content, existing_text):
                logger.warning("Duplicate summary detected — storing with flag")
                flagged = True
                break

        # ── Step 6: Store ────────────────────────────────────────
        # Truncate input_content for storage (keep first 2000 chars)
        stored_input = input_content[:2000]
        if len(input_content) > 2000:
            stored_input += "\n... [truncated for storage]"

        doc = SummaryDocument(
            project=project,
            input_type=input_type,
            input_content=stored_input,
            summary=summary_content,
            status=JobStatus.COMPLETED,
            flagged_for_review=flagged,
            metadata={
                "model": self.llm.get_model_name(),
                "chunks": len(chunks),
                "original_input_length": len(input_content),
            },
        )

        await SummaryRepository.create(doc)
        logger.info(
            f"Summary stored",
            extra={"extra_data": {
                "summary_id": doc.id,
                "flagged": flagged,
            }},
        )

        return doc

    async def _summarize_chunks(self, chunks: list[str]) -> dict:
        """
        Summarize multiple chunks and merge into a single summary.

        Strategy: summarize each chunk individually, then send all
        partial summaries to the LLM for a final merge pass.
        """
        partial_summaries = []

        for i, chunk in enumerate(chunks):
            logger.info(f"Summarizing chunk {i + 1}/{len(chunks)}")
            try:
                partial = await self.llm.summarize(chunk)
                partial_summaries.append(partial)
            except LLMError as e:
                logger.warning(f"Chunk {i + 1} failed: {e}")
                continue

        if not partial_summaries:
            raise LLMError("All chunks failed to summarize")

        if len(partial_summaries) == 1:
            return partial_summaries[0]

        # Merge pass: combine partial summaries
        merge_input = self._format_partials_for_merge(partial_summaries)
        merged = await self.llm.summarize(merge_input)
        return merged

    def _format_partials_for_merge(self, partials: list[dict]) -> str:
        """Format partial summaries into a merge prompt input."""
        parts = []
        for i, partial in enumerate(partials):
            part_text = f"--- PARTIAL SUMMARY {i + 1} ---\n"
            for key in ["what_done", "why_done", "what_remains", "potential_issues"]:
                if key in partial and isinstance(partial[key], dict):
                    part_text += f"{key}: {partial[key].get('text', 'N/A')}\n"
            parts.append(part_text)

        return (
            "Below are partial summaries of different sections of the same codebase. "
            "Merge them into a single coherent summary.\n\n"
            + "\n".join(parts)
        )
