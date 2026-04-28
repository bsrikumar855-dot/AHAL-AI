"""
Domain models for ContextBridge AI.

These Pydantic models represent the core data structures used
throughout the application. They are NOT tied to any specific
database or API schema — those are in schemas.py and repository.py.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ── Enums ────────────────────────────────────────────────────────


class InputType(str, Enum):
    """Type of input provided for summarization."""
    DIFF = "diff"
    COMMIT = "commit"
    PROJECT = "project"


class JobStatus(str, Enum):
    """Status of an async processing job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Value Objects ────────────────────────────────────────────────


class ConfidenceField(BaseModel):
    """A text field paired with its AI-generated confidence score."""
    text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SummaryContent(BaseModel):
    """Structured AI-generated summary with four key dimensions."""
    what_done: ConfidenceField = Field(default_factory=ConfidenceField)
    why_done: ConfidenceField = Field(default_factory=ConfidenceField)
    what_remains: ConfidenceField = Field(default_factory=ConfidenceField)
    potential_issues: ConfidenceField = Field(default_factory=ConfidenceField)


# ── Documents ────────────────────────────────────────────────────


def _generate_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SummaryDocument(BaseModel):
    """
    Represents a stored summarization result.

    This is the primary data object persisted in MongoDB.
    """
    id: str = Field(default_factory=_generate_id)
    project: str = Field(default="default", description="Project identifier")
    input_type: InputType = Field(description="Type of input that was summarized")
    input_content: str = Field(description="Original input (truncated if large)")
    summary: SummaryContent = Field(default_factory=SummaryContent)
    status: JobStatus = Field(default=JobStatus.PENDING)
    flagged_for_review: bool = Field(
        default=False,
        description="True if any confidence score is below threshold",
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary metadata (chunk count, model used, etc.)",
    )


class JobRecord(BaseModel):
    """
    Tracks the status of an async processing job.

    Decoupled from SummaryDocument so a job can exist before
    the summary is created (e.g., while processing).
    """
    job_id: str = Field(default_factory=_generate_id)
    status: JobStatus = Field(default=JobStatus.PENDING)
    input_type: InputType = Field(description="Type of input submitted")
    project: str = Field(default="default")
    result_id: Optional[str] = Field(
        default=None,
        description="ID of the resulting SummaryDocument (set on completion)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the job failed",
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class RepoDocument(BaseModel):
    """Stores repo-level metadata and parsed intent."""
    repo_id: str = Field(default_factory=_generate_id)
    repo_url: str
    project_goal: str = ""
    target_users: str = ""
    core_features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    architecture_style: str = ""
    entry_points: list[str] = Field(default_factory=list)
    core_modules: list[str] = Field(default_factory=list)
    execution_flow: str = ""
    created_at: datetime = Field(default_factory=_utc_now)

class RepoFileDocument(BaseModel):
    """File-level intelligence extracted from the repository."""
    id: str = Field(default_factory=_generate_id)
    repo_id: str = Field(description="Foreign key to RepoDocument.repo_id")
    file_path: str
    summary: str
    module_role: str
    created_at: datetime = Field(default_factory=_utc_now)

class RiskDocument(BaseModel):
    """Security or performance risk identified in the Repo."""
    id: str = Field(default_factory=_generate_id)
    repo_id: str = Field(description="Foreign key to RepoDocument.repo_id")
    type: str = Field(description="e.g. security, performance, anti-pattern")
    description: str
    file_path: str
    created_at: datetime = Field(default_factory=_utc_now)


# ── Multi-Session Architecture ──────────────────────────────────


class SessionType(str, Enum):
    """Type of analysis session."""
    CODE = "code"
    FOLDER = "folder"
    REPO = "repo"


class SessionStatus(str, Enum):
    """Status of a session."""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SummaryBlocks(BaseModel):
    """Structured breakdown of what/why/remaining/issues."""
    what: str = ""
    why: str = ""
    remaining: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class UnifiedResult(BaseModel):
    """Unified output schema for all session types."""
    project_goal: str = ""
    architecture_style: str = ""
    domain: str = ""
    purpose: str = ""
    target_users: str = ""
    system_type: str = ""
    core_behavior: str = ""
    key_capabilities: list[str] = Field(default_factory=list)
    workflow_summary: str = ""
    analysis_focus: list[str] = Field(default_factory=list)
    domain_confidence: str = ""
    validated_domain: str = ""
    validated_behavior: str = ""
    verification_confidence: str = ""
    fact_entry_points: list[str] = Field(default_factory=list)
    fact_modules: list[str] = Field(default_factory=list)
    fact_actions: list[str] = Field(default_factory=list)
    fact_flow: str = ""
    project_type: str = ""
    project_goal_confidence: str = ""
    key_modules: list[str] = Field(default_factory=list)
    core_features: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    workflows: list[dict] = Field(default_factory=list)
    dependency_graph: dict = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    confidence_score: int = Field(default=0, ge=0, le=100)
    confidence_reasons: list[str] = Field(default_factory=list)
    summary_blocks: SummaryBlocks = Field(default_factory=SummaryBlocks)


class SessionDocument(BaseModel):
    """Tracks an analysis session across all modes."""
    session_id: str = Field(default_factory=_generate_id)
    type: SessionType
    title: str = ""
    status: SessionStatus = SessionStatus.PROCESSING
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "Queued"
    preview: str = ""
    source_ref: str = Field(default="", description="Source reference such as repo URL or uploaded filename")
    structure: list[str] = Field(default_factory=list, description="Fast-scan structure snapshot")
    summary: str = Field(default="", description="Short persisted summary for quick reads")
    result: Optional[UnifiedResult] = None
    error: Optional[str] = None
    job_id: Optional[str] = Field(
        default=None,
        description="Associated async job ID",
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class ProjectKnowledgeDocument(BaseModel):
    """Session-scoped project knowledge persisted for chat and reporting."""
    project_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    title: str = ""
    source_ref: str = ""
    project_goal: str = ""
    architecture_style: str = ""
    domain: str = ""
    purpose: str = ""
    target_users: str = ""
    system_type: str = ""
    core_behavior: str = ""
    key_capabilities: list[str] = Field(default_factory=list)
    workflow_summary: str = ""
    analysis_focus: list[str] = Field(default_factory=list)
    domain_confidence: str = ""
    validated_domain: str = ""
    validated_behavior: str = ""
    verification_confidence: str = ""
    fact_entry_points: list[str] = Field(default_factory=list)
    fact_modules: list[str] = Field(default_factory=list)
    fact_actions: list[str] = Field(default_factory=list)
    fact_flow: str = ""
    project_type: str = ""
    project_goal_confidence: str = ""
    summary: str = ""
    structure: list[str] = Field(default_factory=list)
    key_modules: list[str] = Field(default_factory=list)
    core_features: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    confidence_score: int = Field(default=0, ge=0, le=100)
    confidence_reasons: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.PROCESSING
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class ModuleKnowledgeDocument(BaseModel):
    """Persisted module-level intelligence for a session."""
    module_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    name: str
    file_path: str = ""
    role: str = ""
    summary: str = ""
    importance: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class FunctionKnowledgeDocument(BaseModel):
    """Persisted function or class signatures detected during analysis."""
    function_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    module_name: str = ""
    name: str
    kind: str = "function"
    signature: str = ""
    summary: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class WorkflowKnowledgeDocument(BaseModel):
    """Persisted workflow / execution flow intelligence for a session."""
    workflow_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    name: str
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    confidence_percent: int = Field(default=0, ge=0, le=100)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    entry_point: str = ""
    modules: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class RelationshipGraphDocument(BaseModel):
    """Persisted relationship graph for a session."""
    graph_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    nodes: list[dict[str, str]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    central_nodes: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: str = "medium"
    confidence_percent: int = Field(default=0, ge=0, le=100)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class MemoryProfileDocument(BaseModel):
    """Persistent memory and focus profile for a session."""
    memory_id: str = Field(default_factory=_generate_id)
    session_id: str
    session_type: SessionType
    focus: str = ""
    modules_viewed: list[str] = Field(default_factory=list)
    workflows_viewed: list[str] = Field(default_factory=list)
    files_viewed: list[str] = Field(default_factory=list)
    previous_questions: list[str] = Field(default_factory=list)
    previous_answers: list[str] = Field(default_factory=list)
    important_modules: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_utc_now)
    created_at: datetime = Field(default_factory=_utc_now)
