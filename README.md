<p align="center">
  <img src="AHAL AI(FE)/AHAL AI After animation/AhalAI(Frontend)/ClairoAI(Frontend)/public/branding/ahal-logo-chatgpt-transparent.png" alt="AHAL AI Logo" width="280" />
</p>

<h1 align="center">AHAL AI</h1>

<p align="center">
  <strong>AI-Powered Developer Intelligence System</strong>
</p>

<p align="center">
  Turn any codebase into structured, queryable knowledge in seconds.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/MongoDB-Async-47A248?style=flat-square&logo=mongodb&logoColor=white" />
  <img src="https://img.shields.io/badge/Gemini-AI--Powered-8E75B2?style=flat-square&logo=google&logoColor=white" />
  <img src="https://img.shields.io/badge/License-Proprietary-red?style=flat-square" />
</p>

---

## 🧠 What is AHAL AI?

**AHAL AI** is an AI-Powered Developer Intelligence System that converts any codebase — a pasted snippet, a zipped project, or a live GitHub repository — into structured, queryable knowledge in seconds.

It eliminates the hours engineers lose to manual code archaeology by using **multi-pass LLM analysis** to extract architecture, trace execution flows, map dependencies, surface risks, and answer natural-language questions grounded in real code evidence.

> **It is the difference between staring at a codebase and understanding it.**

---

## 🎯 Who is it for?

| User | Use Case |
|------|----------|
| **Software Engineers** | Onboarding to unfamiliar codebases without reading every file |
| **Engineering Leads** | Running architecture reviews and spotting structural risks |
| **Development Teams** | Pre-merge risk assessments and code quality analysis |
| **CTOs & Tech Leads** | Instant structural clarity before making technical investment decisions |

---

## ✨ Core Features

### 🔬 Instant Code Intelligence
Paste any code block and receive a structured breakdown of its purpose, architecture pattern, risk profile, and improvement roadmap — within seconds.

### 📦 Full-Stack Project Analysis
Upload a zipped project and get automated architecture decomposition, module responsibility mapping, and cross-file dependency visualization.

### 🔗 GitHub Repository Intelligence
Provide a repo URL and the system downloads, prioritizes files by engineering importance, and runs a **multi-tier AI analysis pipeline** with automatic recovery to guarantee non-empty, investor-grade project understanding.

### 🔄 Execution Workflow Extraction
Automatically traces API routes through handlers, services, and database operations to produce named, confidence-scored execution flows with uncertainty attribution.

### 🕸️ Dependency Graph Construction
Builds directed relationship graphs identifying central coordination nodes, entry points, and coupling hotspots across the entire analyzed system.

### 🏷️ AI Product Domain Inference
Automatically classifies analyzed systems by domain (developer tools, AI verification, healthcare, finance, education, etc.), infers target users, and generates a startup-pitch-quality project goal.

### 💬 Context-Grounded AI Chat
A workspace assistant where every response is anchored in persisted analysis knowledge — stored modules, workflows, dependency graphs, and product profiles — not generic LLM hallucination.

### 🧱 Persistent Knowledge Accumulation
Every analysis session is decomposed into Project, Module, Function, Workflow, and Graph knowledge documents, so intelligence compounds across sessions rather than disappearing.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AHAL AI Frontend                         │
│              Next.js 14 · React 18 · Framer Motion              │
│         TailwindCSS · Zustand · Split-Screen Workspace          │
└────────────────────────────┬─────────────────────────────────────┘
                             │ REST API
┌────────────────────────────▼─────────────────────────────────────┐
│                       FastAPI Backend                            │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐             │
│  │ Code        │  │ Folder      │  │ Repository   │  Analyzers  │
│  │ Analyzer    │  │ Analyzer    │  │ Service      │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘             │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────┐               │
│  │           Intelligence Engine                  │               │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────┐ │               │
│  │  │ Workflow  │ │ Graph     │ │ Product      │ │               │
│  │  │ Engine   │ │ Builder   │ │ Inference    │ │               │
│  │  └──────────┘ └───────────┘ └──────────────┘ │               │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────┐ │               │
│  │  │ Behavior │ │ Verifi-   │ │ Reasoning    │ │               │
│  │  │ Analysis │ │ cation    │ │ Engine       │ │               │
│  │  └──────────┘ └───────────┘ └──────────────┘ │               │
│  └───────────────────────┬───────────────────────┘               │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────┐               │
│  │          Knowledge Store (MongoDB)             │               │
│  │  Projects · Modules · Functions · Workflows   │               │
│  │  Graphs · Chat History · Session State         │               │
│  └───────────────────────┬───────────────────────┘               │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────┐               │
│  │           Chat Service                         │               │
│  │  Context Builder → Reasoning Engine → LLM     │               │
│  │  → Grounded Response with Memory              │               │
│  └───────────────────────────────────────────────┘               │
│                                                                  │
│  LLM Layer: Google Gemini (primary) · Ollama/Gemma (fallback)   │
└──────────────────────────────────────────────────────────────────┘
```

**Architecture Style:** AI-driven layered intelligence pipeline — static extraction → multi-tier LLM enhancement → centralized intelligence enrichment → knowledge persistence → reasoning-grounded chat.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.14 · FastAPI · Pydantic · async/await |
| **Frontend** | TypeScript · Next.js 14 · React 18 · Framer Motion · TailwindCSS · Zustand |
| **Database** | MongoDB (async via Motor) — sessions, chat history, knowledge graphs |
| **AI / LLM** | Google Gemini API (primary) · Ollama/Gemma (local fallback) |
| **External** | GitHub REST API — repo download, branch detection, file prioritization |

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.12+**
- **Node.js 18+**
- **MongoDB** (local or Atlas)
- **Google Gemini API Key** ([Get one here](https://aistudio.google.com/app/apikey))
- **Ollama** (optional, for local LLM fallback)

### 1. Clone the Repository

```bash
git clone https://github.com/bsrikumar855-dot/AHAL-AI.git
cd AHAL-AI
```

### 2. Backend Setup

```bash
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
cd "ClairoAI(Core Backend)/ClairoAI"
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Frontend Setup

```bash
cd "AHAL AI(FE)/AHAL AI After animation/AhalAI(Frontend)/ClairoAI(Frontend)"
npm install
```

### 4. Start the Application

**Terminal 1 — Backend:**
```bash
cd "ClairoAI(Core Backend)/ClairoAI"
python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd "AHAL AI(FE)/AHAL AI After animation/AhalAI(Frontend)/ClairoAI(Frontend)"
npm run dev
```

**Access the application:**
- 🌐 Frontend: [http://localhost:3000](http://localhost:3000)
- 📡 Backend API: [http://localhost:8000](http://localhost:8000)
- 📖 API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/code/analyze` | Analyze a code snippet |
| `POST` | `/api/v1/folder/analyze` | Analyze an uploaded project archive |
| `POST` | `/api/v1/repo/analyze` | Analyze a GitHub repository by URL |
| `POST` | `/api/v1/chat/ask` | Ask a context-grounded question |
| `GET` | `/api/v1/session/{id}` | Get analysis session status |
| `GET` | `/api/v1/session/{id}/status` | Poll live progress updates |
| `GET` | `/api/v1/health` | System health check |
| `GET` | `/api/v1/summaries` | List analysis history |

---

## 🔄 How It Works

```
Developer Input                    Intelligence Output
─────────────────                  ───────────────────

  Paste Code ──┐
               │     ┌──────────────────────────────┐
  Upload ZIP ──┼────►│  Static Extraction            │
               │     │  (functions, classes, routes)  │
  GitHub URL ──┘     └──────────┬───────────────────┘
                                │
                     ┌──────────▼───────────────────┐
                     │  Multi-Tier LLM Enhancement   │
                     │  Full → Fast → Partial        │
                     │  (guaranteed non-empty output) │
                     └──────────┬───────────────────┘
                                │
                     ┌──────────▼───────────────────┐
                     │  Intelligence Enrichment      │
                     │  • Workflow Extraction         │
                     │  • Dependency Graphing         │
                     │  • Domain Inference            │
                     │  • Behavior Analysis           │
                     │  • Verification                │
                     └──────────┬───────────────────┘
                                │
                     ┌──────────▼───────────────────┐
                     │  Knowledge Persistence         │
                     │  (MongoDB: Projects, Modules,  │
                     │   Workflows, Graphs)           │
                     └──────────┬───────────────────┘
                                │
                     ┌──────────▼───────────────────┐
                     │  Context-Grounded AI Chat      │
                     │  Every answer anchored in      │───► Developer
                     │  real code evidence             │     Clarity
                     └─────────────────────────────┘
```

---

## 📁 Project Structure

```
AHAL-AI/
├── AHAL AI(FE)/                          # Frontend Application
│   └── AHAL AI After animation/
│       └── AhalAI(Frontend)/
│           └── ClairoAI(Frontend)/       # Next.js 14 App
│               ├── app/                  # Pages & Routes
│               │   ├── page.tsx          # Landing Page (cinematic)
│               │   └── dashboard/        # Analysis Dashboard
│               │       ├── code/         # Code Analysis View
│               │       ├── folder/       # Folder Analysis View
│               │       ├── api/          # Repo Analysis View
│               │       └── history/      # Session History
│               ├── components/           # Reusable UI Components
│               ├── hooks/                # Custom React Hooks
│               ├── lib/                  # API Client & Store
│               └── styles/               # Global Styles
│
├── ClairoAI(Core Backend)/              # Backend Application
│   └── ClairoAI/
│       ├── app/
│       │   ├── main.py                  # FastAPI Entry Point
│       │   ├── api/v1/                  # Versioned API Routes
│       │   │   ├── code.py              # Code analysis endpoint
│       │   │   ├── folder.py            # Folder analysis endpoint
│       │   │   ├── repo.py              # Repository analysis endpoint
│       │   │   ├── chat.py              # Chat endpoint
│       │   │   └── session.py           # Session management
│       │   ├── core/                    # Config, Logging, Exceptions
│       │   ├── db/                      # MongoDB Models & Repositories
│       │   └── services/                # Core Intelligence Layer
│       │       ├── code_analyzer.py     # Two-phase code analysis
│       │       ├── folder_analyzer.py   # Project archive analysis
│       │       ├── repo_service.py      # GitHub repo intelligence
│       │       ├── intelligence_engine.py # Central enrichment
│       │       ├── product_inference.py # Domain & goal inference
│       │       ├── workflow_engine.py   # Execution flow extraction
│       │       ├── graph_builder.py     # Dependency graphing
│       │       ├── reasoning_engine.py  # Question-aware retrieval
│       │       ├── chat_service.py      # Grounded conversational AI
│       │       ├── knowledge_store.py   # Persistent knowledge layer
│       │       └── llm_handler.py       # LLM abstraction (Gemini/Ollama)
│       └── requirements.txt
│
└── README.md
```

---

## ⚙️ Environment Variables

Create a `.env` file inside `ClairoAI(Core Backend)/ClairoAI/`:

```env
# Required
GEMINI_API_KEY=your_google_gemini_api_key

# MongoDB
MONGODB_URL=mongodb://localhost:27017
DB_NAME=contextbridge

# LLM Configuration
OLLAMA_MODEL=gemma:7b
LLM_MODE=online
ONLINE_ONLY=true

# Application
APP_NAME=AHAL AI
DEBUG=false
LOG_LEVEL=INFO
```

---

## 🧪 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Multi-tier LLM fallback** (Full → Fast → Partial) | Guarantees non-empty structured output even under LLM timeout or failure |
| **Static extraction before LLM** | Compresses prompt context and provides baseline output if AI fails |
| **Decomposed knowledge store** | Enables cross-session retrieval and progressive intelligence accumulation |
| **Confidence scoring + uncertainty attribution** | Every insight carries a trust signal so developers know what's inferred vs. verified |
| **Domain inference pipeline** | Automatically classifies systems so the AI chat responses are domain-aware |

---

## 📊 Intelligence Pipeline Confidence

Every analysis includes a confidence score (45–96%) with transparent reasoning:

| Signal | Impact |
|--------|--------|
| File sampling depth | +1–10 points |
| Dependency graph richness | +10 points (≥8 edges) |
| Explicit workflow detection | +12 points (≥75% confidence) |
| Semantic refinement passes | +8 points (HIGH confidence LLM) |

---

<p align="center">
  <strong>Built by AHAL AI Team</strong><br/>
  <em>Intelligence that brings light to any codebase.</em>
</p>
