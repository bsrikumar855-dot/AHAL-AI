"""
Abstract base class for LLM providers.

All LLM integrations must implement this interface, ensuring
the rest of the application never depends on a specific provider.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseLLMProvider(ABC):
    """
    Contract for any LLM provider used by ContextBridge.

    Implementations handle:
    - Model selection
    - Prompt formatting
    - Response parsing
    - Timeout / retry logic
    """

    @abstractmethod
    async def summarize(
        self,
        input_text: str,
        prompt_template: Optional[str] = None,
    ) -> dict:
        """
        Generate a structured summary from input text.

        Returns a dict with keys:
            what_done:        {text, confidence}
            why_done:         {text, confidence}
            what_remains:     {text, confidence}
            potential_issues:  {text, confidence}
        """
        ...

    @abstractmethod
    async def answer(
        self,
        context: str,
        question: str,
    ) -> dict:
        """
        Generate a grounded answer to a question using the provided context.

        Returns a dict with keys:
            answer:     str
            confidence: float
        """
        ...

    @abstractmethod
    async def generate_structured(self, prompt: str) -> dict:
        """
        Generate generic structured JSON output.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check whether the LLM backend is reachable and responsive.
        Returns True if healthy.
        """
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the name of the model currently in use."""
        ...
