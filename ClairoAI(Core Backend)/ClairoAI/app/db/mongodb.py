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

        try:
            await self.client.admin.command("ping")
            logger.info("MongoDB connection established")
        except Exception as e:
            logger.error(f"MongoDB startup failed: {e}")
            raise RuntimeError(f"MongoDB startup failed: {e}") from e

        try:
            await self._ensure_indexes()
        except Exception as e:
            logger.warning(
                "Mongo index setup failed, continuing startup",
                exc_info=e,
            )

    async def remove_duplicate_repos(self, collection) -> None:
        pipeline = [
            {
                "$match": {
                    "repo_url": {"$exists": True, "$type": "string", "$ne": ""},
                }
            },
            {
                "$sort": {
                    "created_at": -1,
                    "_id": -1,
                }
            },
            {
                "$group": {
                    "_id": "$repo_url",
                    "ids": {"$push": "$_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
        ]

        duplicates = await collection.aggregate(pipeline).to_list(length=None)
        for doc in duplicates:
            ids_to_delete = list(doc.get("ids", []))[1:]
            if not ids_to_delete:
                continue
            result = await collection.delete_many({"_id": {"$in": ids_to_delete}})
            logger.warning(
                "Removed duplicate repo documents before unique index creation",
                extra={
                    "extra_data": {
                        "repo_url": doc.get("_id"),
                        "deleted_count": result.deleted_count,
                    }
                },
            )

    async def _ensure_named_index(self, collection, keys, *, name: str, **options) -> None:
        existing_indexes = {}
        async for index in collection.list_indexes():
            existing_indexes[index.get("name")] = index

        existing = existing_indexes.get(name)
        normalized_keys = list(keys)
        expected_unique = bool(options.get("unique", False))
        expected_sparse = bool(options.get("sparse", False))

        if existing:
            existing_keys = list((existing.get("key") or {}).items())
            existing_unique = bool(existing.get("unique", False))
            existing_sparse = bool(existing.get("sparse", False))
            if (
                existing_keys == normalized_keys
                and existing_unique == expected_unique
                and existing_sparse == expected_sparse
            ):
                return

            logger.warning(
                "Dropping conflicting MongoDB index before recreation",
                extra={"extra_data": {"collection": collection.name, "index": name}},
            )
            await collection.drop_index(name)

        try:
            await collection.create_index(normalized_keys, name=name, **options)
        except Exception as exc:
            logger.warning(
                "Index already exists or conflict detected; attempting recovery",
                extra={"extra_data": {"collection": collection.name, "index": name, "error": str(exc)}},
            )
            if collection.name == "repos" and name == "repo_url_unique_dup_key":
                await self.remove_duplicate_repos(collection)
            try:
                await collection.drop_index(name)
            except Exception:
                pass
            try:
                await collection.create_index(normalized_keys, name=name, **options)
            except Exception as recreate_exc:
                logger.warning(
                    "Mongo index recreation failed; continuing startup",
                    extra={
                        "extra_data": {
                            "collection": collection.name,
                            "index": name,
                            "error": str(recreate_exc),
                        }
                    },
                )

    async def _ensure_indexes(self) -> None:
        """Create indexes for efficient querying."""
        summaries = self.database["summaries"]
        await summaries.create_index("project")
        await summaries.create_index("status")
        await summaries.create_index("flagged_for_review")
        await summaries.create_index("created_at")
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
        await self.remove_duplicate_repos(repos)
        await self._ensure_named_index(
            repos,
            [("repo_url", 1)],
            name="repo_url_unique_dup_key",
            unique=True,
            sparse=True,
        )
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

        sessions = self.database["sessions"]
        await sessions.create_index("type")
        await sessions.create_index("status")
        await sessions.create_index("created_at")
        await self._ensure_named_index(
            sessions,
            [("job_id", 1)],
            name="job_id_unique_sparse",
            unique=True,
            sparse=True,
        )
        await sessions.create_index("source_ref")

        projects = self.database["projects"]
        await self._ensure_named_index(
            projects,
            [("session_id", 1)],
            name="project_session_id_unique",
            unique=True,
        )
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
        await self._ensure_named_index(
            relationships,
            [("session_id", 1)],
            name="relationship_session_id_unique",
            unique=True,
        )
        await relationships.create_index("session_type")

        memory_profiles = self.database["memory_profiles"]
        await self._ensure_named_index(
            memory_profiles,
            [("session_id", 1)],
            name="memory_profile_session_id_unique",
            unique=True,
        )
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


mongodb = MongoDB()
