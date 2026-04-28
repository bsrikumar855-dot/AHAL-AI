"""
LLM provider factory.

Returns the appropriate LLM provider instance based on the task type.
This abstraction allows swapping providers without changing service code.
"""

from app.core.config import get_settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemma import GemmaProvider


def get_llm_provider(task: str = "summarize") -> BaseLLMProvider:
    """
    Factory function to get an LLM provider for a specific task.

    Args:
        task: "summarize" or "query" — all tasks now use gemma:7b

    Returns:
        An initialized BaseLLMProvider instance.

    To add a new provider:
        1. Create a new class implementing BaseLLMProvider
        2. Add a branch here based on a config flag
    """
    settings = get_settings()

    # All tasks use the single centralized model (gemma:7b)
    return GemmaProvider(model_name=settings.OLLAMA_MODEL)
