// ── Analysis Result (matches backend UnifiedResultResponse) ────

export interface SummaryBlocks {
  what: string;
  why: string;
  remaining: string[]; 
  issues: string[];
}

export interface SummaryPayload {
  what: string;
  why: string;
}

export interface SystemWorkflow {
  initialization?: string | string[];
  request_flow?: string | string[];
  processing_flow?: string | string[];
  response_flow?: string | string[];
}

export interface AnalysisResult {
  type: "code" | "folder" | "repo";
  session_id: string;
  project_goal: string;
  architecture_style: string;
  domain?: string;
  purpose?: string;
  target_users?: string;
  system_type?: string;
  core_behavior?: string;
  key_capabilities?: string[];
  workflow_summary?: string;
  analysis_focus?: string[];
  domain_confidence?: string;
  validated_domain?: string;
  validated_behavior?: string;
  verification_confidence?: string;
  key_modules: string[];
  core_features: string[];
  risks: string[];
  system_workflow?: SystemWorkflow;
  workflows?: WorkflowInsight[];
  dependency_graph?: RelationshipGraph;
  insights?: string[];
  confidence_score?: number;
  confidence_reasons?: string[];
  summary_blocks: SummaryBlocks;
  summary?: SummaryPayload;
}

export interface ChatResponse {
  answer: string;
  source: "code" | "folder" | "repo" | "none" | string;
  related_files?: string[];
  modules_involved?: string[];
  session_id: string;
  suggested_questions?: string[];
}

export interface ChatHistoryItem {
  question: string;
  answer: string;
  timestamp: string;
}

export interface ChatHistoryResponse {
  session_id: string;
  history: ChatHistoryItem[];
  count: number;
}

export interface ChatContextSyncResponse {
  ok: boolean;
  focus: string;
  modules_viewed: string[];
  workflows_viewed: string[];
  files_viewed: string[];
}

// ── Session History ────────────────────────────────────────────

export interface SessionHistoryItem {
  session_id: string;
  type: "code" | "folder" | "repo";
  title: string;
  status: "processing" | "completed" | "failed";
  preview: string;
  created_at: string;
}

export interface SessionHistoryResponse {
  sessions: SessionHistoryItem[];
  total: number;
  skip: number;
  limit: number;
}

// ── Session Status (full result) ───────────────────────────────

export interface SessionStatusResponse {
  session_id: string;
  task_id?: string | null;
  job_id?: string | null;
  type: "code" | "folder" | "repo";
  status: "processing" | "completed" | "failed";
  title: string;
  preview: string;
  progress: number;
  stage: string;
  source_ref?: string;
  structure?: string[];
  result: {
    project_goal: string;
    architecture_style: string;
    domain?: string;
    purpose?: string;
    target_users?: string;
    system_type?: string;
    core_behavior?: string;
    key_capabilities?: string[];
    workflow_summary?: string;
    analysis_focus?: string[];
    domain_confidence?: string;
    validated_domain?: string;
    validated_behavior?: string;
    verification_confidence?: string;
    key_modules: string[];
    core_features: string[];
    risks: string[];
    workflows?: WorkflowInsight[];
    dependency_graph?: RelationshipGraph;
    insights?: string[];
    confidence_score?: number;
    confidence_reasons?: string[];
    summary_blocks: SummaryBlocks;
    summary?: SummaryPayload;
  } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionResultResponse {
  session_id: string;
  task_id?: string | null;
  job_id?: string | null;
  type: "code" | "folder" | "repo";
  status: "processing" | "completed" | "failed";
  progress: number;
  stage: string;
  result: AnalysisResult | null;
  error: string | null;
}

export interface SessionReportResponse {
  session_id: string;
  type: "code" | "folder" | "repo" | string;
  report: string;
}

export interface WorkflowInsight {
  name: string;
  steps: string[];
  summary?: string;
  confidence?: string;
  confidence_percent?: number;
  entry_point?: string;
  modules?: string[];
  message?: string;
  uncertainty_reasons?: string[];
}

export interface RelationshipGraph {
  nodes?: Array<{ id: string; type: string; label: string; importance?: number; role?: string }>;
  edges?: Array<{ source: string; target: string; relation: string }>;
  dependencies?: Record<string, string[]>;
  central_nodes?: string[];
  summary?: string;
  confidence?: string;
  confidence_percent?: number;
  uncertainty_reasons?: string[];
}

export interface SessionIntelligenceResponse {
  session_id: string;
  project?: {
    project_goal?: string;
    architecture_style?: string;
    domain?: string;
    purpose?: string;
    target_users?: string;
    system_type?: string;
    core_behavior?: string;
    key_capabilities?: string[];
    workflow_summary?: string;
    analysis_focus?: string[];
    domain_confidence?: string;
    validated_domain?: string;
    validated_behavior?: string;
    verification_confidence?: string;
    summary?: string;
    summary_payload?: SummaryPayload;
    key_modules?: string[];
    core_features?: string[];
    risks?: string[];
    insights?: string[];
    confidence_score?: number;
    confidence_reasons?: string[];
  };
  workflows: WorkflowInsight[];
  graph: RelationshipGraph;
  memory_profile: {
    focus?: string;
    modules_viewed?: string[];
    workflows_viewed?: string[];
    files_viewed?: string[];
    previous_questions?: string[];
  };
}

// ── API Error ──────────────────────────────────────────────────

export interface ApiError {
  error: string;
  message: string;
  path?: string;
}
