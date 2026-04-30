"""
Request and response schemas for the API layer.

These Pydantic models define the contract between the API
and its consumers. They are separate from domain models to
allow the API surface to evolve independently.
"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from app.db.models import (
    ConfidenceField,
    SummaryContent,
    JobStatus,
    InputType,
    SessionType,
    SessionStatus,
    SummaryBlocks,
    SystemWorkflow,
    UnifiedResult,
)


LLMMode = Literal["offline", "online", "smart"]


# ── Request Schemas ──────────────────────────────────────────────


class SummarizeTextRequest(BaseModel):
    """Request body for text-based summarization (diff or commit)."""
    input_type: InputType = Field(
        description="Type of input: 'diff', 'commit', or 'project'"
    )
    content: str = Field(
        min_length=1,
        max_length=500_000,
        description="The diff, commit message, or code content to summarize",
    )
    project: str = Field(
        default="default",
        description="Project identifier for grouping summaries",
    )


class QueryRequest(BaseModel):
    """Request body for querying stored summaries."""
    session_id: Optional[str] = Field(
        default=None,
        description="Optional client-provided session identifier",
    )
    question: str = Field(
        min_length=1,
        max_length=2000,
        description="The question to ask about stored knowledge",
    )
    mode: LLMMode = Field(
        default="offline",
        description="LLM routing mode: offline, online, or smart",
    )
    project: Optional[str] = Field(
        default=None,
        description="Filter summaries to a specific project",
    )
    date_from: Optional[datetime] = Field(
        default=None,
        description="Filter summaries created after this date",
    )
    date_to: Optional[datetime] = Field(
        default=None,
        description="Filter summaries created before this date",
    )
    repo_id: Optional[str] = Field(
        default=None,
        description="If provided, routes query exclusively to Repo ingestion collections.",
    )
    max_context_summaries: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of summaries to use as context",
    )

class RepoAnalyzeRequest(BaseModel):
    """Request body for analyzing a GitHub repository."""
    session_id: Optional[str] = Field(
        default=None,
        description="Optional client-provided session identifier",
    )
    repo_url: str = Field(
        pattern=r"^https://github\.com/[\w.-]+/[\w.-]+/?$",
        description="The GitHub repository URL to analyze",
    )
    mode: LLMMode = Field(
        default="offline",
        description="LLM routing mode: offline, online, or smart",
    )


# ── Response Schemas ─────────────────────────────────────────────


class JobResponse(BaseModel):
    """Returned immediately when a summarization job is submitted."""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    message: str = "Job submitted successfully"


class StatusResponse(BaseModel):
    """Returned when checking the status of a job."""
    job_id: str
    status: JobStatus
    result_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SourceReference(BaseModel):
    """A reference to a summary used as context for a query answer."""
    summary_id: str
    project: str
    relevance: float = Field(ge=0.0, le=1.0)
    snippet: str = ""


class QueryResponse(BaseModel):
    """Returned when a query is answered."""
    answer: str
    reasoning: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    sources: List[SourceReference] = []
    rag_used: bool = False


class SummaryResponse(BaseModel):
    """A single summary in the list response."""
    id: str
    project: str
    input_type: InputType
    summary: SummaryContent
    status: JobStatus
    flagged_for_review: bool
    created_at: datetime
    updated_at: datetime
    metadata: dict = {}


class SummaryListResponse(BaseModel):
    """Paginated list of summaries."""
    summaries: List[SummaryResponse]
    total: int
    skip: int
    limit: int


class HealthCheck(BaseModel):
    """Individual health check result."""
    status: str  # "healthy" | "unhealthy" | "degraded"
    details: Optional[str] = None


class HealthResponse(BaseModel):
    """System health check response."""
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str
    checks: dict[str, HealthCheck]
    uptime_seconds: float


class ErrorResponse(BaseModel):
    """Structured error response."""
    error: str
    message: str
    path: Optional[str] = None

# ── Multi-Session Schemas ────────────────────────────────────────


class CodeAnalyzeRequest(BaseModel):
    """Request body for synchronous code analysis."""
    session_id: Optional[str] = Field(
        default=None,
        description="Optional client-provided session identifier",
    )
    code: str = Field(
        min_length=1,
        max_length=500_000,
        description="Raw code or diff to analyze",
    )
    mode: LLMMode = Field(
        default="offline",
        description="LLM routing mode: offline, online, or smart",
    )


class UnifiedResultResponse(BaseModel):
    """Unified analysis result returned by all session types."""
    type: SessionType
    session_id: str
    overview: str = ""
    project_type: str = ""
    tech_stack: List[str] = []
    folder_structure: List[dict] = []
    core_modules: List[dict] = []
    execution_flow: List[str] = []
    dependencies: List[dict] = []
    issues: List[str] = []
    improvements: List[str] = []
    project_goal: str = ""
    architecture_style: str = ""
    domain: str = ""
    purpose: str = ""
    target_users: str = ""
    system_type: str = ""
    core_behavior: str = ""
    key_capabilities: List[str] = []
    workflow_summary: str = ""
    analysis_focus: List[str] = []
    domain_confidence: str = ""
    validated_domain: str = ""
    validated_behavior: str = ""
    verification_confidence: str = ""
    fact_entry_points: List[str] = []
    fact_modules: List[str] = []
    fact_actions: List[str] = []
    fact_flow: str = ""
    project_goal_confidence: str = ""
    key_modules: List[str] = []
    core_features: List[str] = []
    risks: List[str] = []
    system_workflow: SystemWorkflow = Field(default_factory=SystemWorkflow)
    workflows: List[dict] = []
    dependency_graph: dict = {}
    insights: List[dict] = []
    confidence_score: int = 0
    confidence_reasons: List[str] = []
    summary_blocks: SummaryBlocks = Field(default_factory=SummaryBlocks)
    summary: dict = Field(default_factory=lambda: {"what": "", "why": ""})


class SessionStatusResponse(BaseModel):
    """Returned when checking session status."""
    session_id: str
    task_id: Optional[str] = None
    job_id: Optional[str] = None
    type: SessionType
    status: SessionStatus
    progress: int = 0
    stage: str = ""
    title: str = ""
    preview: str = ""
    source_ref: str = ""
    structure: List[str] = []
    result: Optional[UnifiedResult] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionHistoryItem(BaseModel):
    """Single item in the session history list."""
    session_id: str
    type: SessionType
    title: str = ""
    status: SessionStatus
    preview: str = ""
    created_at: datetime


class SessionHistoryResponse(BaseModel):
    """Paginated session history."""
    sessions: List[SessionHistoryItem]
    total: int
    skip: int
    limit: int


class RepoOverviewResponse(BaseModel):
    """Returned for GET /api/v1/repo/{repo_id}/overview."""
    repo_id: str
    repo_url: str
    project_goal: str
    architecture_style: str
    key_modules: List[str]
    risks_count: int
    created_at: datetime
