"""
Data access layer (Repository pattern) for MongoDB.

All database operations are encapsulated here so that
business logic in the services layer never touches the
database driver directly.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import uuid
from pydantic import ValidationError

from app.db.mongodb import mongodb
from app.db.models import (
    SummaryDocument,
    JobRecord,
    JobStatus,
    RepoDocument,
    RepoFileDocument,
    RiskDocument,
    SessionDocument,
    SessionStatus,
    ProjectKnowledgeDocument,
    ModuleKnowledgeDocument,
    FunctionKnowledgeDocument,
    WorkflowKnowledgeDocument,
    RelationshipGraphDocument,
    MemoryProfileDocument,
)
from app.core.logging import get_logger

logger = get_logger("db.repository")
_INVALID_SESSION_IDS = {"", "error-no-db", "fallback-session", "default", "error", "none", "null"}
_WORKFLOW_FIELDS = ("initialization", "request_flow", "processing_flow", "response_flow")


def ensure_valid_session_id(session_id: Optional[str]) -> str:
    """Return a usable session id, replacing known bad placeholders."""
    candidate = (session_id or "").strip()
    if candidate.lower() in _INVALID_SESSION_IDS:
        return str(uuid.uuid4())
    return candidate


def _ensure_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return []


def _coerce_session_workflow_shape(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Repair legacy session payloads that stored workflow stages as strings."""
    repaired = dict(doc)
    result = repaired.get("result")
    if not isinstance(result, dict):
        return repaired

    workflow = result.get("system_workflow")
    workflow_dict = workflow if isinstance(workflow, dict) else {}
    result["system_workflow"] = {
        field: _ensure_str_list(workflow_dict.get(field))
        for field in _WORKFLOW_FIELDS
    }
    repaired["result"] = result
    return repaired


def _parse_session_document(doc: Dict[str, Any]) -> SessionDocument:
    try:
        return SessionDocument(**doc)
    except ValidationError as exc:
        logger.warning(f"Repairing legacy workflow shape for session {doc.get('session_id')}: {exc.errors()}")
        repaired = _coerce_session_workflow_shape(doc)
        return SessionDocument(**repaired)


class SummaryRepository:
    """CRUD operations for the 'summaries' collection."""

    COLLECTION = "summaries"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, summary: SummaryDocument) -> str:
        """Insert a new summary document. Returns its ID."""
        doc = summary.model_dump()
        doc["_id"] = doc.pop("id")
        await cls._collection().insert_one(doc)
        logger.info(f"Created summary {doc['_id']}")
        return doc["_id"]

    @classmethod
    async def get_by_id(cls, summary_id: str) -> Optional[SummaryDocument]:
        """Retrieve a summary by its ID."""
        doc = await cls._collection().find_one({"_id": summary_id})
        if doc is None:
            return None
        doc["id"] = doc.pop("_id")
        return SummaryDocument(**doc)

    @classmethod
    async def list_summaries(
        cls,
        project: Optional[str] = None,
        status: Optional[str] = None,
        flagged: Optional[bool] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[SummaryDocument], int]:
        """
        List summaries with optional filters and pagination.
        Returns (list_of_summaries, total_count).
        """
        query: Dict[str, Any] = {}
        if project:
            query["project"] = project
        if status:
            query["status"] = status
        if flagged is not None:
            query["flagged_for_review"] = flagged

        total = await cls._collection().count_documents(query)
        cursor = (
            cls._collection()
            .find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

        summaries = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            summaries.append(SummaryDocument(**doc))

        return summaries, total

    @classmethod
    async def update(cls, summary_id: str, updates: dict) -> bool:
        """
        Partially update a summary document.
        Returns True if a document was modified.
        """
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await cls._collection().update_one(
            {"_id": summary_id},
            {"$set": updates},
        )
        return result.modified_count > 0

    @classmethod
    async def search_by_text(
        cls,
        query_text: str,
        project: Optional[str] = None,
        limit: int = 5,
    ) -> List[SummaryDocument]:
        """
        Full-text search across summary fields.
        Returns summaries sorted by text relevance score.
        """
        search_filter: Dict[str, Any] = {
            "$text": {"$search": query_text}
        }
        if project:
            search_filter["project"] = project

        # Only return completed summaries
        search_filter["status"] = JobStatus.COMPLETED.value

        cursor = (
            cls._collection()
            .find(
                search_filter,
                {"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )

        summaries = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            doc.pop("score", None)
            summaries.append(SummaryDocument(**doc))

        return summaries

    @classmethod
    async def find_recent(
        cls,
        project: Optional[str] = None,
        limit: int = 5,
    ) -> List[SummaryDocument]:
        """Get the most recent completed summaries."""
        query: Dict[str, Any] = {"status": JobStatus.COMPLETED.value}
        if project:
            query["project"] = project

        cursor = (
            cls._collection()
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )

        summaries = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            summaries.append(SummaryDocument(**doc))

        return summaries


class JobRepository:
    """CRUD operations for the 'jobs' collection."""

    COLLECTION = "jobs"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, job: JobRecord) -> str:
        """Insert a new job record. Returns the job_id."""
        logger.info(f"Creating job record in MongoDB for job_id: {job.job_id}")
        doc = job.model_dump()
        doc["_id"] = doc.pop("job_id")
        
        # Ensure enums are converted to values to prevent BSON encoding issues
        if hasattr(job.status, "value"):
            doc["status"] = job.status.value
        if hasattr(job.input_type, "value"):
            doc["input_type"] = job.input_type.value

        try:
            await cls._collection().insert_one(doc)
            logger.info(f"Successfully created job {doc['_id']} with status {doc['status']}")
            return doc["_id"]
        except Exception as e:
            logger.error(f"Failed to persist job {doc['_id']} to MongoDB: {e}")
            raise

    @classmethod
    async def get_by_id(cls, job_id: str) -> Optional[JobRecord]:
        """Retrieve a job by its ID."""
        logger.info(f"Fetching job_id: {job_id} from MongoDB collection {cls.COLLECTION}")
        try:
            doc = await cls._collection().find_one({"_id": job_id})
            if doc is None:
                logger.warning(f"Job {job_id} not found in database.")
                return None
            doc["job_id"] = doc.pop("_id")
            logger.info(f"Successfully fetched job {job_id} with status {doc.get('status')}")
            return JobRecord(**doc)
        except Exception as e:
            logger.error(f"Error fetching job {job_id} from MongoDB: {e}")
            raise

    @classmethod
    async def update_status(
        cls,
        job_id: str,
        status: JobStatus,
        result_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update the status of a job."""
        updates: Dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(timezone.utc),
        }
        if result_id is not None:
            updates["result_id"] = result_id
        if error is not None:
            updates["error"] = error

        result = await cls._collection().update_one(
            {"_id": job_id},
            {"$set": updates},
        )
        logger.info(f"Job {job_id} -> {status.value}")
        return result.modified_count > 0

class RepoRepository:
    """CRUD operations for the 'repos' collection."""
    COLLECTION = "repos"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, repo: RepoDocument) -> str:
        doc = repo.model_dump()
        repo_id = doc.pop("repo_id")
        repo_url = str(doc.get("repo_url", "")).strip()
        doc["updated_at"] = datetime.now(timezone.utc)

        existing = await cls._collection().find_one({"repo_url": repo_url}) if repo_url else None
        if existing:
            await cls._collection().update_one(
                {"_id": existing["_id"]},
                {
                    "$set": doc,
                    "$setOnInsert": {"created_at": doc.get("created_at", datetime.now(timezone.utc))},
                },
                upsert=False,
            )
            logger.info(f"Updated existing repo for repo_url: {repo_url}")
            return str(existing["_id"])

        doc["_id"] = repo_id
        await cls._collection().update_one(
            {"repo_url": repo_url},
            {
                "$set": doc,
                "$setOnInsert": {
                    "_id": repo_id,
                    "created_at": doc.get("created_at", datetime.now(timezone.utc)),
                },
            },
            upsert=True,
        )
        logger.info(f"Created repo {repo_id}")
        return repo_id

    @classmethod
    async def get_by_id(cls, repo_id: str) -> Optional[RepoDocument]:
        doc = await cls._collection().find_one({"_id": repo_id})
        if doc is None:
            return None
        doc["repo_id"] = doc.pop("_id")
        return RepoDocument(**doc)

class RepoFileRepository:
    """CRUD operations for the 'files' collection."""
    COLLECTION = "files"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, file_doc: RepoFileDocument) -> str:
        doc = file_doc.model_dump()
        doc["_id"] = doc.pop("id")
        await cls._collection().insert_one(doc)
        return doc["_id"]
        
    @classmethod
    async def count_by_repo(cls, repo_id: str) -> int:
        return await cls._collection().count_documents({"repo_id": repo_id})

    @classmethod
    async def search_by_keywords(cls, query_text: str, repo_id: str, limit: int = 5) -> List[RepoFileDocument]:
        """Search files within a repo including keyword match + importance weight."""
        search_filter = {
            "repo_id": repo_id,
            "$text": {"$search": query_text}
        }

        try:
            cursor = (
                cls._collection()
                .find(search_filter, {"score": {"$meta": "textScore"}})
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit * 2) # Fetch extra so we can re-sort locally
            )
        except Exception:
            return []

        files = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            keyword_match = doc.pop("score", 0.0)
            
            # Calculate file_importance_weight based on critical keywords
            importance = 0.0
            role = doc.get("module_role", "").lower()
            path = doc.get("file_path", "").lower()
            if any(x in role or x in path for x in ["core", "main", "auth", "db", "api", "config", "security"]):
                importance = 1.5
                
            doc["_computed_score"] = keyword_match + importance
            files.append(doc)
            
        # Re-sort locally with combined score
        files.sort(key=lambda x: x["_computed_score"], reverse=True)
        
        results = []
        for d in files[:limit]:
            d.pop("_computed_score", None)
            results.append(RepoFileDocument(**d))
            
        return results
class RiskRepository:
    """CRUD operations for the 'risks' collection."""
    COLLECTION = "risks"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, risk_doc: RiskDocument) -> str:
        doc = risk_doc.model_dump()
        doc["_id"] = doc.pop("id")
        await cls._collection().insert_one(doc)
        return doc["_id"]
        
    @classmethod
    async def count_by_repo(cls, repo_id: str) -> int:
        return await cls._collection().count_documents({"repo_id": repo_id})

    @classmethod
    async def search_by_keywords(cls, query_text: str, repo_id: str, limit: int = 5) -> List[RiskDocument]:
        """Search risks within a repo matching keywords."""
        search_filter = {
            "repo_id": repo_id,
            "$text": {"$search": query_text}
        }
        
        try:
            cursor = (
                cls._collection()
                .find(search_filter, {"score": {"$meta": "textScore"}})
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit)
            )
        except Exception:
            return []
            
        risks = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            doc.pop("score", None)
            risks.append(RiskDocument(**doc))
            
        return risks


class SessionRepository:
    """CRUD operations for the 'sessions' collection."""

    COLLECTION = "sessions"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def create(cls, session: SessionDocument) -> str:
        """Create a session safely. Returns the session_id."""
        doc = session.model_dump()
        session_id = ensure_valid_session_id(doc.pop("session_id", None))
        doc["_id"] = session_id
        doc["session_id"] = session_id
        # Ensure enums serialize as values
        if hasattr(session.type, "value"):
            doc["type"] = session.type.value
        if hasattr(session.status, "value"):
            doc["status"] = session.status.value
        await cls._collection().update_one(
            {"_id": session_id},
            {"$setOnInsert": {k: v for k, v in doc.items() if k != "session_id"}},
            upsert=True,
        )
        logger.info(f"Created or reused session {session_id} (type={doc['type']})")
        return session_id

    @classmethod
    async def get_by_id(cls, session_id: str) -> Optional[SessionDocument]:
        """Retrieve a session by its ID."""
        doc = await cls._collection().find_one({"_id": session_id})
        if doc is None:
            return None
        doc["session_id"] = doc.pop("_id")
        return _parse_session_document(doc)

    @classmethod
    async def get_by_job_id(cls, job_id: str) -> Optional[SessionDocument]:
        """Retrieve a session by its associated job_id (repo sessions)."""
        doc = await cls._collection().find_one({"job_id": job_id})
        if doc is None:
            return None
        doc["session_id"] = doc.pop("_id")
        return _parse_session_document(doc)

    @classmethod
    async def update_status(
        cls,
        session_id: str,
        status: SessionStatus,
        progress: Optional[int] = None,
        stage: Optional[str] = None,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update session status and optionally attach result or error."""
        updates: Dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(timezone.utc),
        }
        if progress is not None:
            updates["progress"] = max(0, min(100, int(progress)))
        if stage is not None:
            updates["stage"] = str(stage)
        if result is not None:
            updates["result"] = result
        if error is not None:
            updates["error"] = error
        res = await cls._collection().update_one(
            {"_id": session_id},
            {"$set": updates},
        )
        logger.info(f"Session {session_id} -> {status.value}")
        return res.modified_count > 0

    @classmethod
    async def update_fields(cls, session_id: str, **updates: Any) -> bool:
        sanitized_session_id = ensure_valid_session_id(session_id)
        if not updates:
            return False
        updates["updated_at"] = datetime.now(timezone.utc)
        if "status" in updates and hasattr(updates["status"], "value"):
            updates["status"] = updates["status"].value
        res = await cls._collection().update_one(
            {"_id": sanitized_session_id},
            {"$set": updates},
        )
        logger.info(f"Session {sanitized_session_id} fields updated")
        return res.modified_count > 0

    @classmethod
    async def update_progress(
        cls,
        session_id: str,
        progress: int,
        stage: str,
        result: Optional[dict] = None,
    ) -> bool:
        updates: Dict[str, Any] = {
            "progress": max(0, min(100, int(progress))),
            "stage": str(stage),
            "updated_at": datetime.now(timezone.utc),
        }
        if result is not None:
            updates["result"] = result
        res = await cls._collection().update_one(
            {"_id": session_id},
            {"$set": updates},
        )
        logger.info(f"Session {session_id} progress -> {updates['progress']} ({stage})")
        return res.modified_count > 0

    @classmethod
    async def list_sessions(
        cls,
        type_filter: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[SessionDocument], int]:
        """Paginated session list with optional type filter."""
        query: Dict[str, Any] = {}
        if type_filter:
            query["type"] = type_filter

        total = await cls._collection().count_documents(query)
        cursor = (
            cls._collection()
            .find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

        sessions = []
        async for doc in cursor:
            doc["session_id"] = doc.pop("_id")
            sessions.append(_parse_session_document(doc))

        return sessions, total

    @classmethod
    async def delete_by_id(cls, session_id: str) -> bool:
        """Delete a session by ID."""
        res = await cls._collection().delete_one({"_id": session_id})
        logger.info(f"Session {session_id} deleted")
        return res.deleted_count > 0


class ProjectKnowledgeRepository:
    COLLECTION = "projects"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def upsert(cls, document: ProjectKnowledgeDocument) -> str:
        doc = document.model_dump()
        project_id = doc.pop("project_id")
        doc["_id"] = project_id
        if hasattr(document.session_type, "value"):
            doc["session_type"] = document.session_type.value
        if hasattr(document.status, "value"):
            doc["status"] = document.status.value
        update_doc = {k: v for k, v in doc.items() if k != "_id"}
        await cls._collection().update_one(
            {"session_id": document.session_id},
            {"$set": update_doc, "$setOnInsert": {"_id": project_id}},
            upsert=True,
        )
        return project_id

    @classmethod
    async def get_by_session_id(cls, session_id: str) -> Optional[ProjectKnowledgeDocument]:
        doc = await cls._collection().find_one({"session_id": session_id})
        if doc is None:
            return None
        doc["project_id"] = doc.pop("_id")
        return ProjectKnowledgeDocument(**doc)


class ModuleKnowledgeRepository:
    COLLECTION = "modules"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def replace_for_session(cls, session_id: str, documents: List[ModuleKnowledgeDocument]) -> None:
        await cls._collection().delete_many({"session_id": session_id})
        if not documents:
            return
        payload = []
        for document in documents:
            doc = document.model_dump()
            doc["_id"] = doc.pop("module_id")
            if hasattr(document.session_type, "value"):
                doc["session_type"] = document.session_type.value
            payload.append(doc)
        await cls._collection().insert_many(payload)

    @classmethod
    async def list_for_session(cls, session_id: str, limit: int = 20) -> List[ModuleKnowledgeDocument]:
        cursor = cls._collection().find({"session_id": session_id}).sort("importance", -1).limit(limit)
        items: List[ModuleKnowledgeDocument] = []
        async for doc in cursor:
            doc["module_id"] = doc.pop("_id")
            items.append(ModuleKnowledgeDocument(**doc))
        return items


class FunctionKnowledgeRepository:
    COLLECTION = "functions"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def replace_for_session(cls, session_id: str, documents: List[FunctionKnowledgeDocument]) -> None:
        await cls._collection().delete_many({"session_id": session_id})
        if not documents:
            return
        payload = []
        for document in documents:
            doc = document.model_dump()
            doc["_id"] = doc.pop("function_id")
            if hasattr(document.session_type, "value"):
                doc["session_type"] = document.session_type.value
            payload.append(doc)
        await cls._collection().insert_many(payload)

    @classmethod
    async def list_for_session(cls, session_id: str, limit: int = 40) -> List[FunctionKnowledgeDocument]:
        cursor = cls._collection().find({"session_id": session_id}).sort("name", 1).limit(limit)
        items: List[FunctionKnowledgeDocument] = []
        async for doc in cursor:
            doc["function_id"] = doc.pop("_id")
            items.append(FunctionKnowledgeDocument(**doc))
        return items


class WorkflowKnowledgeRepository:
    COLLECTION = "workflows"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def replace_for_session(cls, session_id: str, documents: List[WorkflowKnowledgeDocument]) -> None:
        await cls._collection().delete_many({"session_id": session_id})
        if not documents:
            return
        payload = []
        for document in documents:
            doc = document.model_dump()
            doc["_id"] = doc.pop("workflow_id")
            if hasattr(document.session_type, "value"):
                doc["session_type"] = document.session_type.value
            payload.append(doc)
        await cls._collection().insert_many(payload)

    @classmethod
    async def list_for_session(cls, session_id: str, limit: int = 10) -> List[WorkflowKnowledgeDocument]:
        cursor = cls._collection().find({"session_id": session_id}).sort("created_at", -1).limit(limit)
        items: List[WorkflowKnowledgeDocument] = []
        async for doc in cursor:
            doc["workflow_id"] = doc.pop("_id")
            items.append(WorkflowKnowledgeDocument(**doc))
        return items


class RelationshipGraphRepository:
    COLLECTION = "relationships"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def upsert(cls, document: RelationshipGraphDocument) -> str:
        doc = document.model_dump()
        graph_id = doc.pop("graph_id")
        doc["_id"] = graph_id
        if hasattr(document.session_type, "value"):
            doc["session_type"] = document.session_type.value
        update_doc = {k: v for k, v in doc.items() if k != "_id"}
        await cls._collection().update_one(
            {"session_id": document.session_id},
            {"$set": update_doc, "$setOnInsert": {"_id": graph_id}},
            upsert=True,
        )
        return graph_id

    @classmethod
    async def get_by_session_id(cls, session_id: str) -> Optional[RelationshipGraphDocument]:
        doc = await cls._collection().find_one({"session_id": session_id})
        if doc is None:
            return None
        doc["graph_id"] = doc.pop("_id")
        return RelationshipGraphDocument(**doc)


class MemoryProfileRepository:
    COLLECTION = "memory_profiles"

    @classmethod
    def _collection(cls):
        return mongodb.get_collection(cls.COLLECTION)

    @classmethod
    async def upsert(cls, document: MemoryProfileDocument) -> str:
        doc = document.model_dump()
        memory_id = doc.pop("memory_id")
        doc["_id"] = memory_id
        if hasattr(document.session_type, "value"):
            doc["session_type"] = document.session_type.value
        update_doc = {k: v for k, v in doc.items() if k != "_id"}
        await cls._collection().update_one(
            {"session_id": document.session_id},
            {"$set": update_doc, "$setOnInsert": {"_id": memory_id}},
            upsert=True,
        )
        return memory_id

    @classmethod
    async def get_by_session_id(cls, session_id: str) -> Optional[MemoryProfileDocument]:
        doc = await cls._collection().find_one({"session_id": session_id})
        if doc is None:
            return None
        doc["memory_id"] = doc.pop("_id")
        return MemoryProfileDocument(**doc)
