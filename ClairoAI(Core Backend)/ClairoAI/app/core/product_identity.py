"""
AHAL AI — Product Identity Module.

This module defines the canonical, system-wide product identity used
across API responses, self-description endpoints, and knowledge persistence.

It is the SINGLE SOURCE OF TRUTH for how AHAL AI describes itself.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ── Product Identity ────────────────────────────────────────────────
PRODUCT_NAME = "AHAL AI"
PRODUCT_TAGLINE = "AI-Powered Developer Intelligence System"
PRODUCT_VERSION = "1.0.0"

PRODUCT_GOAL = (
    "AHAL AI is an AI-Powered Developer Intelligence System that transforms "
    "any codebase — pasted code, uploaded projects, or live GitHub repositories "
    "— into structured, queryable knowledge in seconds. It replaces manual code "
    "archaeology with multi-pass LLM analysis that extracts architecture, traces "
    "execution flows, maps dependencies, surfaces risks, and answers natural-language "
    "questions grounded entirely in verified code evidence."
)

TARGET_USERS = (
    "Software engineers onboarding to unfamiliar codebases, engineering leads "
    "conducting architecture reviews, development teams performing pre-merge "
    "risk assessments, and technical decision-makers who need instant structural "
    "clarity before committing engineering resources."
)

CORE_FEATURES: List[str] = [
    "Instant Code Intelligence — paste any code block and receive a structured breakdown "
    "of purpose, architecture pattern, risk profile, and improvement roadmap",
    "GitHub Repository Intelligence — provide a repo URL for automated file prioritization "
    "and multi-tier AI analysis with guaranteed non-empty output",
    "Full-Stack Project Analysis — upload a zipped project for architecture decomposition, "
    "module responsibility mapping, and dependency visualization",
    "Execution Workflow Extraction — automatic tracing of API routes through handlers, "
    "services, and database operations into confidence-scored execution flows",
    "Dependency Graph Construction — directed relationship graphs identifying central nodes, "
    "entry points, and coupling hotspots",
    "AI Product Domain Inference — automatic system classification by domain with target user "
    "inference and investor-grade project goal generation",
    "Context-Grounded AI Chat — workspace assistant anchored in persisted analysis knowledge "
    "including modules, workflows, graphs, and product profiles",
    "Persistent Knowledge Accumulation — analysis sessions decomposed into Project, Module, "
    "Function, Workflow, and Graph knowledge documents for cross-session retrieval",
]

TECH_STACK: List[str] = [
    "Python 3.14 — FastAPI, Pydantic, async/await",
    "TypeScript — Next.js 14, React 18, Framer Motion, TailwindCSS, Zustand",
    "MongoDB — async Motor driver for sessions, chat history, knowledge persistence",
    "Google Gemini API — primary LLM with Ollama/Gemma local fallback",
    "GitHub REST API — repository download, branch detection, file prioritization",
]

ARCHITECTURE_STYLE = (
    "AI-driven layered intelligence pipeline — three specialized analyzers feed "
    "raw signals into a centralized Intelligence Engine orchestrating five parallel "
    "enrichment layers (workflow extraction, dependency graphing, domain inference, "
    "behavior analysis, verification), persisting decomposed knowledge into MongoDB, "
    "and surfacing it through a Reasoning Engine that grounds every conversational "
    "response in verified code evidence."
)

CORE_MODULES: List[Dict[str, str]] = [
    {"name": "repo_service", "role": "GitHub repository intelligence pipeline"},
    {"name": "code_analyzer", "role": "Two-phase code intelligence engine"},
    {"name": "folder_analyzer", "role": "Project archive intelligence"},
    {"name": "intelligence_engine", "role": "Central enrichment orchestrator"},
    {"name": "product_inference", "role": "Domain classification and goal synthesis"},
    {"name": "workflow_engine", "role": "Execution flow extraction"},
    {"name": "chat_service", "role": "Context-grounded conversational AI"},
    {"name": "reasoning_engine", "role": "Question intent detection and knowledge retrieval"},
    {"name": "knowledge_store", "role": "Persistent knowledge decomposition"},
    {"name": "graph_builder", "role": "Dependency graph construction"},
]

EXECUTION_FLOW = (
    "A developer opens the AHAL AI dashboard and selects an intelligence mode: "
    "paste code for instant analysis, upload a project archive for full-stack "
    "decomposition, or connect a GitHub repository for deep multi-file intelligence. "
    "The system runs a two-phase AI pipeline — static extraction captures structural "
    "signals as a guaranteed baseline, then a multi-tier LLM cascade through Google "
    "Gemini generates structured analysis with automatic fallback ensuring output is "
    "never empty. The Intelligence Engine enriches the result across five parallel "
    "layers: workflow extraction traces execution paths, dependency graphing maps "
    "module relationships, domain inference classifies system purpose, behavior "
    "analysis identifies runtime intent, and verification cross-checks consistency. "
    "The enriched payload is decomposed into MongoDB as reusable knowledge documents. "
    "When the developer asks follow-up questions through the workspace chat, the "
    "Reasoning Engine retrieves stored knowledge, detects question intent, selects "
    "relevant modules and workflows, and generates responses grounded in real code "
    "evidence — closing a continuous intelligence loop where each analysis deepens "
    "understanding and each conversation is anchored in verified truth."
)


def get_product_identity() -> Dict[str, Any]:
    """Return the full product identity as a dictionary."""
    return {
        "name": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": PRODUCT_VERSION,
        "project_goal": PRODUCT_GOAL,
        "target_users": TARGET_USERS,
        "core_features": CORE_FEATURES,
        "tech_stack": TECH_STACK,
        "architecture_style": ARCHITECTURE_STYLE,
        "core_modules": CORE_MODULES,
        "execution_flow": EXECUTION_FLOW,
    }


def get_product_summary() -> str:
    """Return a compact product summary for API health endpoints."""
    return f"{PRODUCT_NAME} — {PRODUCT_TAGLINE} (v{PRODUCT_VERSION})"
