# 🚀 ContextBridge AI

**AI-powered developer tool that transforms code changes into structured, queryable knowledge using Gemma models.**

ContextBridge converts diffs, commit messages, and project uploads into structured summaries with confidence scores, stores them in MongoDB, and enables conversational querying over your codebase history.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI                              │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌──────┐ │
│  │summarize │ │ status   │ │ query  │ │summaries│ │health│ │
│  └────┬─────┘ └────┬─────┘ └───┬────┘ └───┬────┘ └──┬───┘ │
│       │             │           │           │         │     │
│  ┌────▼─────────────▼───────────▼───────────▼─────────▼──┐ │
│  │              Services Layer                           │ │
│  │  ┌────────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐  │ │
│  │  │ Summarizer │ │  Query   │ │  File   │ │  RAG   │  │ │
│  │  │  Service   │ │  Engine  │ │ Handler │ │Service │  │ │
│  │  └─────┬──────┘ └────┬─────┘ └─────────┘ └────────┘  │ │
│  │        │              │                                │ │
│  │  ┌─────▼──────────────▼─────┐                         │ │
│  │  │   LLM Provider (Gemma)   │                         │ │
│  │  │   ┌─────┐    ┌─────┐    │                         │ │
│  │  │   │ 7B  │    │ 2B  │    │                         │ │
│  │  │   └─────┘    └─────┘    │                         │ │
│  │  └──────────────────────────┘                         │ │
│  └───────────────────────────────────────────────────────┘ │
│                           │                                 │
│  ┌────────────────────────▼─────────────────────────────┐  │
│  │              MongoDB (Motor Async)                   │  │
│  │  ┌──────────────┐     ┌──────────────┐               │  │
│  │  │  summaries   │     │    jobs       │               │  │
│  │  └──────────────┘     └──────────────┘               │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- MongoDB (local or Docker)
- Ollama with Gemma models

### 1. Clone & Install

```bash
cd ClairoAI
pip install -r requirements.txt
cp .env.example .env
```

### 2. Start MongoDB

```bash
# Option A: Docker
docker run -d -p 27017:27017 --name mongodb mongo:7

# Option B: Local install
mongod --dbpath ./data
```

### 3. Start Ollama & Pull Models

```bash
ollama serve
ollama pull gemma2:7b
ollama pull gemma2:2b
```

### 4. Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Open API Docs

Visit: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Docker Compose (Full Stack)

```bash
docker compose up -d

# Pull Gemma models into Ollama container
docker exec -it contextbridge-ollama ollama pull gemma2:7b
docker exec -it contextbridge-ollama ollama pull gemma2:2b
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/summarize` | Submit diff/commit for summarization |
| `POST` | `/api/v1/summarize/upload` | Upload .zip project for summarization |
| `GET` | `/api/v1/status/{job_id}` | Check job processing status |
| `POST` | `/api/v1/query` | Ask questions over stored summaries |
| `GET` | `/api/v1/summaries` | List stored summaries (with filters) |
| `GET` | `/api/v1/health` | System health check |

### Example: Summarize a Diff

```bash
curl -X POST http://localhost:8000/api/v1/summarize \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "diff",
    "content": "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,5 @@\n+import logging\n+logger = logging.getLogger(__name__)\n def main():\n-    print(\"hello\")\n+    logger.info(\"Application started\")\n     return True",
    "project": "my-project"
  }'
```

### Example: Query Knowledge

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What logging changes were made recently?",
    "project": "my-project"
  }'
```

### Example: Upload Project

```bash
curl -X POST http://localhost:8000/api/v1/summarize/upload \
  -F "file=@my-project.zip" \
  -F "project=my-project"
```

---

## Configuration

All settings are managed via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `GEMMA_SUMMARIZE_MODEL` | `gemma2:7b` | Model for summarization |
| `GEMMA_QUERY_MODEL` | `gemma2:2b` | Model for queries |
| `RAG_ENABLED` | `false` | Enable RAG retrieval layer |
| `CONFIDENCE_THRESHOLD` | `0.6` | Below this, fields are flagged |

---

## Project Structure

```
app/
├── api/v1/           # Versioned HTTP endpoints
├── core/             # Config, logging, exceptions
├── services/         # Business logic
│   └── llm/          # Pluggable LLM providers
├── db/               # MongoDB models, schemas, repository
├── workers/          # Background task processing
└── main.py           # App factory & middleware
```

---

## Design Decisions

1. **Repository Pattern** — DB operations are encapsulated, making it easy to swap MongoDB for another store
2. **Factory Pattern for LLM** — Add new providers (OpenAI, HuggingFace) without touching service code
3. **Circuit Breaker for RAG** — External service failures don't cascade into the main pipeline
4. **BackgroundTasks over Celery** — Simpler deployment for single-node; worker interface supports upgrade path
5. **Pydantic v2** — Used for validation, serialization, and settings management throughout

---

## License

MIT
