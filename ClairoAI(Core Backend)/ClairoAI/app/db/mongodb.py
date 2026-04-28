"""
Async MongoDB client lifecycle management.

Uses Motor (async driver for MongoDB) with connection pooling.
The client is initialized on app startup and closed on shutdown
via the FastAPI lifespan context manager.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("db")


class MongoDB:
    """
    Manages the async MongoDB connection lifecycle.

    Usage:
        db = MongoDB()
        await db.connect()       # called at startup
        collection = db.get_collection("summaries")
        await db.disconnect()    # called at shutdown
    """

    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.database: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        """Establish connection to MongoDB and create indexes."""
        settings = get_settings()
        logger.info(
            "Connecting to MongoDB",
            extra={"extra_data": {"url": settings.MONGODB_URL, "db": settings.DB_NAME}},
        )

        self.client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            maxPoolSize=20,
            minPoolSize=5,
            serverSelectionTimeoutMS=500,
        )
        self.database = self.client[settings.DB_NAME]

        # Verify connectivity (non-fatal — app starts in degraded mode)
        try:
            await self.client.admin.command("ping")
            logger.info("MongoDB connection established")
            await self._ensure_indexes()
        except Exception as e:
            logger.warning(
                f"MongoDB not available at startup: {e}. "
                "App will start in degraded mode. "
                "Database operations will fail until MongoDB is reachable."
            )

    async def _ensure_indexes(self) -> None:
        """Create indexes for efficient querying."""
        summaries = self.database["summaries"]
        await summaries.create_index("project")
        await summaries.create_index("status")
        await summaries.create_index("flagged_for_review")
        await summaries.create_index("created_at")
        # Text index for full-text search across summary fields
        await summaries.create_index(
            [
                ("summary.what_done.text", "text"),
                ("summary.why_done.text", "text"),
                ("summary.what_remains.text", "text"),
                ("summary.potential_issues.text", "text"),
                ("input_content", "text"),
            ],
            name="summary_text_search",
            default_language="english",
        )

        jobs = self.database["jobs"]
        await jobs.create_index("status")
        await jobs.create_index("created_at")

        repos = self.database["repos"]
        await repos.create_index("repo_id", unique=True)
        await repos.create_index("created_at")

        files = self.database["files"]
        await files.create_index("repo_id")
        await files.create_index(
            [
                ("file_path", "text"),
                ("summary", "text"),
                ("module_role", "text"),
            ],
            name="file_text_search",
            default_language="english",
        )

        risks = self.database["risks"]
        await risks.create_index("repo_id")
        await risks.create_index(
            [
                ("description", "text"),
                ("file_path", "text"),
            ],
            name="risk_text_search",
            default_language="english",
        )

        # ── Sessions collection (multi-session architecture) ──
        sessions = self.database["sessions"]
        await sessions.create_index("type")
        await sessions.create_index("status")
        await sessions.create_index("created_at")
        await sessions.create_index("job_id", sparse=True)
        await sessions.create_index("source_ref")

        projects = self.database["projects"]
        await projects.create_index("session_id", unique=True)
        await projects.create_index("session_type")
        await projects.create_index("status")
        await projects.create_index("created_at")

        modules = self.database["modules"]
        await modules.create_index("session_id")
        await modules.create_index("name")
        await modules.create_index("importance")

        functions = self.database["functions"]
        await functions.create_index("session_id")
        await functions.create_index("module_name")
        await functions.create_index("name")

        workflows = self.database["workflows"]
        await workflows.create_index("session_id")
        await workflows.create_index("name")

        relationships = self.database["relationships"]
        await relationships.create_index("session_id", unique=True)
        await relationships.create_index("session_type")

        memory_profiles = self.database["memory_profiles"]
        await memory_profiles.create_index("session_id", unique=True)
        await memory_profiles.create_index("session_type")
        await memory_profiles.create_index("updated_at")

        chat_history = self.database["chat_history"]
        await chat_history.create_index("session_id")
        await chat_history.create_index("chat_mode")
        await chat_history.create_index("timestamp")

        logger.info("Database indexes ensured")

    async def disconnect(self) -> None:
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

    def get_collection(self, name: str):
        """Get a collection by name from the active database."""
        if self.database is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self.database[name]

    async def is_healthy(self) -> bool:
        """Check if MongoDB is reachable."""
        try:
            if self.client is None:
                return False
            await self.client.admin.command("ping")
            return True
        except Exception:
            return False


# Singleton instance — imported across the app
mongodb = MongoDB()
