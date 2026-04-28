"""
Query engine for conversational knowledge retrieval.

Retrieves relevant stored summaries, constructs grounded context,
and generates answers using the fast LLM model. Optionally augments
with RAG for complex queries.
"""

from typing import Optional, List

from app.db.repository import SummaryRepository, RepoRepository, RepoFileRepository, RiskRepository
from app.db.models import SummaryDocument
from app.db.schemas import SourceReference, QueryResponse
from app.services.rag import RAGService
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.llm_handler import call_llm_async

logger = get_logger("query_engine")

REPO_RAG_PROMPT = """
Answer the question using ONLY the context below.

NO explanations. NO markdown.

CONTEXT:
{context}

QUESTION:
{question}

FORMAT:

{{
  "answer": "string",
  "reasoning": "string",
  "confidence": 0.0
}}

If context is insufficient, set answer to "Not enough information".

RETURN ONLY JSON:
"""

class QueryEngine:
    """
    Generates grounded answers from stored summaries.

    Flow:
        1. Retrieve relevant summaries (text search + recency)
        2. Optionally augment with RAG context
        3. Construct grounded context
        4. Call LLM with strict "context only" prompt
        5. Return answer with source references
    """

    def __init__(self):
        self.rag = RAGService()
        self.settings = get_settings()

    async def answer(
        self,
        question: str,
        project: Optional[str] = None,
        max_context: int = 5,
        repo_id: Optional[str] = None,
        mode: str = "offline",
    ) -> QueryResponse:
        """
        Generate a grounded answer to a question.

        Args:
            question:    The user's question
            project:     Optional project filter
            max_context: Max summaries to use as context
            repo_id:     Optional repo ID to exclusively query repository ingestion data

        Returns:
            QueryResponse with answer, confidence, and source references.
        """
        if repo_id:
            return await self._answer_repo_rag(question, repo_id, max_context, mode)

        logger.info(
            "Processing query",
            extra={"extra_data": {
                "question_length": len(question),
                "project": project,
            }},
        )

        # ── Step 1: Retrieve relevant summaries ──────────────────
        summaries = await self._retrieve_summaries(
            question, project, max_context
        )

        if not summaries:
            logger.info("No relevant summaries found")
            return QueryResponse(
                answer="I don't have enough context to answer this question. "
                       "No relevant summaries were found.",
                confidence=0.1,
                sources=[],
                rag_used=False,
            )

        # ── Step 2: Optional RAG augmentation ────────────────────
        rag_context = ""
        rag_used = False

        if self.settings.RAG_ENABLED and self._is_complex_query(question):
            rag_context = await self._get_rag_context(question)
            rag_used = bool(rag_context)

        # ── Step 3: Build grounded context ───────────────────────
        context = self._build_context(summaries, rag_context)

        # ── Step 4: Generate answer ──────────────────────────────
        prompt = REPO_RAG_PROMPT.format(context=context, question=question)
        result = await call_llm_async(
            prompt,
            timeout=self.settings.LLM_TIMEOUT_SECONDS,
            fallback_context=context,
            mode=mode,
        )

        # ── Step 5: Build response ───────────────────────────────
        sources = self._build_sources(summaries)

        response = QueryResponse(
            answer=result.get("answer", "Unable to generate answer"),
            reasoning=result.get("reasoning"),
            confidence=float(result.get("confidence", 0.5)),
            sources=sources,
            rag_used=rag_used,
        )

        logger.info(
            "Query answered",
            extra={"extra_data": {
                "confidence": response.confidence,
                "sources_count": len(sources),
                "rag_used": rag_used,
            }},
        )

        return response

    async def _retrieve_summaries(
        self,
        question: str,
        project: Optional[str],
        limit: int,
    ) -> List[SummaryDocument]:
        """
        Retrieve summaries using text search, falling back to
        recent summaries if text search yields no results.
        """
        # Try text search first
        try:
            summaries = await SummaryRepository.search_by_text(
                query_text=question,
                project=project,
                limit=limit,
            )
            if summaries:
                return summaries
        except Exception as e:
            logger.warning(f"Text search failed, falling back to recent: {e}")

        # Fallback: recent summaries
        return await SummaryRepository.find_recent(
            project=project,
            limit=limit,
        )

    def _is_complex_query(self, question: str) -> bool:
        """
        Heuristic to detect complex queries that benefit from RAG.

        Triggers RAG for:
        - Questions over 100 chars
        - Questions containing technical keywords
        - Multi-part questions (containing 'and' or 'or')
        """
        if len(question) > 100:
            return True

        complexity_markers = [
            " and ", " or ", "compare", "difference",
            "how does", "why does", "architecture",
            "performance", "security", "trade-off",
        ]
        question_lower = question.lower()
        return any(marker in question_lower for marker in complexity_markers)

    async def _get_rag_context(self, question: str) -> str:
        """Fetch additional context from the RAG service."""
        try:
            results = await self.rag.retrieve(question)
            if results:
                return "\n\n--- EXTERNAL CONTEXT ---\n" + "\n".join(results)
        except Exception as e:
            logger.warning(f"RAG retrieval failed (non-fatal): {e}")

        return ""

    def _build_context(
        self,
        summaries: List[SummaryDocument],
        rag_context: str = "",
    ) -> str:
        """
        Construct a grounded context string from retrieved summaries.
        """
        parts = []

        for i, summary in enumerate(summaries):
            s = summary.summary
            part = (
                f"--- Summary {i + 1} (Project: {summary.project}) ---\n"
                f"What was done: {s.what_done.text}\n"
                f"Why it was done: {s.why_done.text}\n"
                f"What remains: {s.what_remains.text}\n"
                f"Potential issues: {s.potential_issues.text}\n"
            )
            parts.append(part)

        context = "\n".join(parts)

        if rag_context:
            context += "\n" + rag_context

        return context

    def _build_sources(
        self,
        summaries: List[SummaryDocument],
    ) -> List[SourceReference]:
        """Build source reference objects for the response."""
        sources = []
        for i, summary in enumerate(summaries):
            # Simple relevance decay based on position
            relevance = max(0.3, 1.0 - (i * 0.15))
            sources.append(SourceReference(
                summary_id=summary.id,
                project=summary.project,
                relevance=round(relevance, 2),
                snippet=summary.summary.what_done.text[:100],
            ))
        return sources

    async def _answer_repo_rag(self, question: str, repo_id: str, max_context: int, mode: str = "offline") -> QueryResponse:
        """RAG implementation exclusively for Repo logic."""
        logger.info(f"Processing Repo RAG query for {repo_id}")
        
        repo = await RepoRepository.get_by_id(repo_id)
        files = await RepoFileRepository.search_by_keywords(question, repo_id, max_context)
        risks = await RiskRepository.search_by_keywords(question, repo_id, max_context)
        
        if not files and not repo:
            return QueryResponse(
                answer="No repository information found matching this query.",
                confidence=0.1,
                sources=[],
                rag_used=False
            )
            
        context = self._build_repo_context(repo, files, risks)
        prompt = REPO_RAG_PROMPT.format(context=context, question=question)
        
        try:
            parsed = await call_llm_async(
                prompt,
                timeout=self.settings.LLM_TIMEOUT_SECONDS,
                fallback_context=context,
                mode=mode,
            )
            
            # Extract sources
            sources = []
            for f in files:
                sources.append(SourceReference(
                    summary_id=f.id,
                    project=repo_id,
                    relevance=1.0,
                    snippet=f.summary[:100]
                ))
                
            return QueryResponse(
                answer=parsed.get("answer", "No answer generated."),
                reasoning=parsed.get("reasoning", "No reasoning provided."),
                confidence=float(parsed.get("confidence", 0.5)),
                sources=sources,
                rag_used=True
            )
        except Exception as e:
            logger.error(f"Repo RAG generation failed: {e}")
            return QueryResponse(answer=f"Generation failed: {e}", confidence=0.0)

    def _build_repo_context(self, repo, files, risks) -> str:
        parts = []
        if repo:
            parts.append(f"--- REPOSITORY SUMMARY ---\\nGoal: {repo.project_goal}\\nTech Stack: {', '.join(repo.tech_stack)}\\nArchitecture: {repo.architecture_style}\\nCore Modules: {', '.join(repo.core_modules)}\\n")
            
        if files:
            parts.append("--- RELEVANT FILES ---")
            for f in files:
                parts.append(f"File: {f.file_path}\\nRole: {f.module_role}\\nSummary: {f.summary}\\n")
                
        if risks:
            parts.append("--- IDENTIFIED RISKS ---")
            for r in risks:
                parts.append(f"File: {r.file_path} | Type: {r.type} | Risk: {r.description}\\n")
                
        # Limit context to avoid overflow
        return "\\n".join(parts)[:10000]
