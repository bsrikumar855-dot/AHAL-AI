"""
Application configuration via Pydantic Settings.

All settings are loaded from environment variables (or .env file).
Use get_settings() to access the singleton instance.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration for ContextBridge AI."""

    # ── Application ──────────────────────────────────────────────
    APP_NAME: str = "ContextBridge AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── MongoDB ──────────────────────────────────────────────────
    MONGODB_URL: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection string",
    )
    DB_NAME: str = Field(
        default="contextbridge",
        description="MongoDB database name",
    )

    # ── Ollama / LLM ────────────────────────────────────────────
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for the Ollama API",
    )
    OLLAMA_URL: str = Field(
        default="http://localhost:11434/api/generate",
        description="Full Ollama generate endpoint URL",
    )
    OLLAMA_MODEL: str = Field(
        default="gemma:7b",
        description="Single centralized LLM model for all tasks",
    )
    LLM_MODE: str = Field(
        default="online",
        description="Default LLM routing mode: offline, online, or smart",
    )
    ONLINE_ONLY: bool = Field(
        default=True,
        description="Temporarily force all LLM traffic to the online provider only",
    )
    GEMINI_API_KEY: str = Field(
        ...,
        description="Google GenAI API key for online mode (REQUIRED)",
    )
    GEMMA_SUMMARIZE_MODEL: str = Field(
        default="gemma:7b",
        description="Model used for deep summarization tasks",
    )
    GEMMA_QUERY_MODEL: str = Field(
        default="gemma:7b",
        description="Model used for fast conversational queries",
    )
    OLLAMA_TEMPERATURE: float = Field(
        default=0,
        description="LLM temperature (0 = deterministic output)",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default=60,
        description="Timeout for a single LLM call",
    )
    LLM_MAX_RETRIES: int = Field(
        default=2,
        description="Number of retries on LLM failure",
    )
    LLM_MAX_RESPONSE_TOKENS: int = Field(
        default=2048,
        description="Maximum tokens requested from Ollama for structured output",
    )

    # ── File Uploads ─────────────────────────────────────────────
    UPLOAD_DIR: str = Field(
        default="./uploads",
        description="Temporary directory for uploaded files",
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50,
        description="Maximum upload size in megabytes",
    )
    MAX_FILE_SIZE_KB: int = Field(
        default=100,
        description="Maximum individual file size to process (KB)",
    )

    # ── RAG ──────────────────────────────────────────────────────
    RAG_ENABLED: bool = Field(
        default=False,
        description="Enable the optional RAG retrieval layer",
    )
    RAG_API_URL: str = Field(
        default="http://localhost:8100/retrieve",
        description="External RAG retrieval API endpoint",
    )
    RAG_CIRCUIT_BREAKER_THRESHOLD: int = Field(
        default=3,
        description="Consecutive failures before disabling RAG temporarily",
    )
    RAG_CIRCUIT_BREAKER_COOLDOWN: int = Field(
        default=60,
        description="Seconds to wait before retrying RAG after circuit break",
    )

    # ── Processing ───────────────────────────────────────────────
    CHUNK_SIZE_CHARS: int = Field(
        default=2000,
        description="Max characters per chunk sent to LLM",
    )
    CHUNK_BATCH_SIZE: int = Field(
        default=3,
        description="Maximum number of chunks sent in a single LLM request",
    )
    SMART_FILE_SAMPLE_LIMIT: int = Field(
        default=8,
        description="Maximum number of prioritized files sampled for repository analysis",
    )
    CONFIDENCE_THRESHOLD: float = Field(
        default=0.6,
        description="Fields below this confidence are flagged",
    )
    DEFAULT_PAGE_SIZE: int = Field(
        default=20,
        description="Default pagination page size",
    )

    model_config = {
        "env_file": (".env", "ClairoAI/.env", "app/.env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    settings = Settings()
    print(f"GEMINI KEY: {settings.GEMINI_API_KEY[:8]}..." if settings.GEMINI_API_KEY else "GEMINI KEY: NOT SET")
    print(f"ONLINE_ONLY: {settings.ONLINE_ONLY}")
    print(f"LLM_MODE: {settings.LLM_MODE}")
    return settings
