"""
Optional RAG (Retrieval-Augmented Generation) service.

Provides external context retrieval to augment query answers.
Implements a circuit breaker pattern to prevent cascade failures
when the external service is unavailable.

The system works perfectly without RAG — this is an enhancement layer.
"""

import time
from typing import List

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("rag")


class RAGService:
    """
    Optional retrieval service with circuit breaker protection.

    Circuit breaker states:
    - CLOSED:   Normal operation, requests go through
    - OPEN:     Too many failures, requests short-circuit to empty results
    - HALF-OPEN: Cooldown passed, next request is a probe

    The system degrades gracefully — when RAG is unavailable,
    the query engine simply uses stored summaries alone.
    """

    # Shared circuit breaker state across instances
    _consecutive_failures: int = 0
    _circuit_open_since: float = 0.0
    _circuit_state: str = "closed"  # closed, open, half_open

    def __init__(self):
        self.settings = get_settings()

    async def retrieve(self, query: str) -> List[str]:
        """
        Retrieve external context for a query.

        Returns a list of relevant text snippets from the external API.
        Returns an empty list on any failure (graceful degradation).

        Args:
            query: The search query

        Returns:
            List of context strings, or empty list if unavailable.
        """
        if not self.settings.RAG_ENABLED:
            return []

        # Check circuit breaker
        if not self._should_attempt():
            logger.info("RAG circuit breaker is OPEN — skipping retrieval")
            return []

        try:
            results = await self._call_retrieval_api(query)
            self._on_success()
            return results

        except Exception as e:
            self._on_failure()
            logger.warning(
                f"RAG retrieval failed (non-fatal): {e}",
                extra={"extra_data": {
                    "consecutive_failures": self._consecutive_failures,
                    "circuit_state": self._circuit_state,
                }},
            )
            return []

    async def _call_retrieval_api(self, query: str) -> List[str]:
        """
        Call the external retrieval API.

        Expected API contract:
            POST /retrieve
            Body: {"query": "...", "top_k": 3}
            Response: {"results": [{"text": "..."}, ...]}

        In development/testing, this uses a mock response
        if the external API is not available.
        """
        url = self.settings.RAG_API_URL

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={"query": query, "top_k": 3},
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        return [
            item.get("text", "") for item in results
            if isinstance(item, dict) and item.get("text")
        ]

    def _should_attempt(self) -> bool:
        """Check if a request should be attempted based on circuit state."""
        if self._circuit_state == "closed":
            return True

        if self._circuit_state == "open":
            cooldown = self.settings.RAG_CIRCUIT_BREAKER_COOLDOWN
            elapsed = time.time() - self._circuit_open_since

            if elapsed >= cooldown:
                logger.info("RAG circuit breaker → HALF-OPEN (probing)")
                RAGService._circuit_state = "half_open"
                return True
            return False

        # half_open — allow one probe request
        return True

    def _on_success(self) -> None:
        """Reset circuit breaker on successful request."""
        if self._circuit_state != "closed":
            logger.info("RAG circuit breaker → CLOSED (recovered)")
        RAGService._consecutive_failures = 0
        RAGService._circuit_state = "closed"
        RAGService._circuit_open_since = 0.0

    def _on_failure(self) -> None:
        """Update circuit breaker state on failure."""
        RAGService._consecutive_failures += 1
        threshold = self.settings.RAG_CIRCUIT_BREAKER_THRESHOLD

        if RAGService._consecutive_failures >= threshold:
            RAGService._circuit_state = "open"
            RAGService._circuit_open_since = time.time()
            logger.warning(
                f"RAG circuit breaker → OPEN "
                f"(after {RAGService._consecutive_failures} failures)"
            )
        elif self._circuit_state == "half_open":
            RAGService._circuit_state = "open"
            RAGService._circuit_open_since = time.time()
            logger.warning("RAG circuit breaker → OPEN (half-open probe failed)")

    async def health_check(self) -> dict:
        """Return RAG service health status."""
        return {
            "enabled": self.settings.RAG_ENABLED,
            "circuit_state": self._circuit_state,
            "consecutive_failures": self._consecutive_failures,
        }
