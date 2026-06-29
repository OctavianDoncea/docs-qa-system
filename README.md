# docs-qa

Ask natural-language questions about any public GitHub repository and get cited answers sourced directly from its documentation.

Paste a repo URL, wait for ingestion, then chat. Answers stream in real time with inline citations that expand to show the exact doc chunks used.

---

## Features

| Feature | Description |
| --- | --- |
| **GitHub ingestion** | Fetches documentation from public repos via the GitHub API. Supports `.md`, `.mdx`, `.rst`, `.txt`, and Python `.py` files (docstrings). Skips test folders, vendor code, and `node_modules`. |
| **Background ingest jobs** | Ingestion runs asynchronously with live progress (fetching → chunking → embedding → saving). Poll job status from the UI or API. |
| **Multi-repo support** | Load and switch between multiple repositories. Each repo is stored independently with its own chunk index. |
| **Markdown-aware chunking** | Splits docs on heading boundaries first, then paragraphs and sentences, with configurable size and overlap. Keeps sections coherent for better retrieval and readable source cards. |
| **Python docstring extraction** | Parses `.py` files with AST to extract module, class, and function docstrings as searchable chunks. |
| **Hybrid search** | Combines pgvector cosine similarity with PostgreSQL full-text search, fused via Reciprocal Rank Fusion (RRF). Catches both semantic and keyword matches. |
| **LLM reranking** | Optionally re-scores hybrid-search candidates with the LLM before answering, improving precision on ambiguous queries. |
| **Confidence gating** | Declines to answer when the best match score is below a configurable threshold, instead of hallucinating. |
| **Streaming answers** | Responses stream token-by-token over Server-Sent Events (SSE) for low perceived latency. |
| **Conversational follow-ups** | Keeps the last few turns of chat history. Follow-up questions are rewritten into standalone search queries so "what about that?" still retrieves the right docs. |
| **Inline citations** | Every factual claim is cited with `[1]`, `[2]`, etc. Source cards show file path, similarity score, and the full chunk text. |
| **Groq + Ollama LLM fallback** | Uses Groq for fast cloud inference by default. Falls back to a local Ollama model if Groq is unavailable. |
| **Local embeddings** | Embeddings run through Ollama (`embeddinggemma:300m`, 768-dim) — free, offline-capable, no API rate limits during ingestion. |
| **GitHub token support** | Optional `GITHUB_TOKEN` raises the GitHub API rate limit from 60 to 5,000 requests/hour for large repos. |
| **Evaluation toolkit** | Scripts under `backend/eval/` measure retrieval hit rate, keyword recall, and refusal accuracy against a test dataset. |

---

## How it works

1. **Ingest** — Paste a GitHub URL and click **Load docs**. The backend fetches doc files, chunks them, embeds each chunk with Ollama, and stores vectors in PostgreSQL (pgvector).
2. **Retrieve** — Your question is embedded, condensed if it's a follow-up, then matched via hybrid search. Top candidates are optionally reranked by the LLM.
3. **Answer** — Groq (or Ollama) generates a cited answer from the retrieved chunks. Citations map to collapsible source cards in the UI.

---

## Architecture

```
Browser
   │
   ▼
nginx (frontend) :5173
   ├── static React SPA
   └── /repos, /query, /health ──► FastAPI (backend) :8000
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
                    Ollama (host)   PostgreSQL      Groq (cloud)
                    embeddinggemma  + pgvector     llama / gpt-oss
                    :300m           vector(768)     free tier
                    embed + fallback LLM
```

---

## Installation (Docker)

### Prerequisites

Install these before running the stack:

1. **[Docker Desktop](https://docs.docker.com/get-docker/)** (includes Docker Compose)
2. **[Ollama](https://ollama.com)** — must be running on the host machine (not inside Docker)
3. **Groq API key** — free at [console.groq.com](https://console.groq.com)
4. **(Recommended) GitHub personal access token** — avoids the 60 req/hr unauthenticated API limit. Create one at GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic). No scopes required for public repos.

Pull the embedding model once Ollama is installed:

```bash
ollama pull embeddinggemma:300m
```

If you plan to use the Ollama LLM fallback, also pull a chat model:

```bash
ollama pull llama3.1:8b
```

### Setup

```bash
git clone https://github.com/OctavianDoncea/docs-qa-system
cd docs-qa-system

cp .env.example .env
```

Edit `.env` and set at minimum:

```env
GROQ_API_KEY=gsk_your_key_here
GITHUB_TOKEN=ghp_your_token_here   # recommended
```

### Run

```bash
docker compose up --build
```

Wait until all three services are healthy:

| Service | URL | Purpose |
| --- | --- | --- |
| **Frontend** | [http://localhost:5173](http://localhost:5173) | Web UI |
| **Backend API** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive API docs |
| **PostgreSQL** | `localhost:5432` | Database (internal + exposed) |

The first build takes 3–5 minutes (Python deps + Node build). Subsequent starts are fast.

### Stop and reset

```bash
# Stop containers
docker compose down

# Stop and delete all ingested data
docker compose down -v
```

### Docker notes

- **Ollama runs on the host.** The backend container reaches it via `host.docker.internal:11434`. Make sure Ollama is running (`ollama serve`) before starting the stack.
- **Migrations run automatically** on backend startup (`alembic upgrade head`).
- **Data persists** in the `pgdata` Docker volume between restarts.

---

## Configuration

All settings live in `.env`. Key variables:

| Variable | Default | Description |
| --- | --- | --- |
| `GROQ_API_KEY` | — | Required for LLM answers and reranking |
| `GROQ_LLM_MODEL` | `openai/gpt-oss-20b` | Groq model for generation and reranking |
| `GITHUB_TOKEN` | — | GitHub PAT to avoid API rate limits |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint (overridden in Docker to `host.docker.internal`) |
| `EMBEDDING_MODEL` | `embeddinggemma:300m` | Ollama embedding model |
| `LLM_MODEL` | `llama3.1:8b` | Ollama fallback chat model |
| `CHUNK_SIZE` | `1500` | Max characters per chunk |
| `CHUNK_OVERLAP` | `200` | Overlap between consecutive chunks |
| `TOP_K` | `5` | Number of chunks sent to the LLM |
| `CONFIDENCE_THRESHOLD` | `0.45` | Minimum similarity score to attempt an answer |
| `RERANK_ENABLED` | `true` | Enable LLM reranking of search candidates |
| `RERANK_CANDIDATES` | `12` | Candidates fetched before reranking |

---

## Local development (without Docker)

Run only the database in Docker; start backend and frontend natively for hot reload.

```bash
# Terminal 1 — database
docker compose up db -d

# Terminal 2 — backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate  |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # set GROQ_API_KEY and GITHUB_TOKEN
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 3 — frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The Vite dev server proxies API calls to the backend on port 8000.

---

## API

Full interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

**Start ingestion (async)**

```
POST /repos
{"url": "https://github.com/owner/repo", "reingest": false}
→ {"job_id": 1, "status": "pending"}
```

**Poll ingest job**

```
GET /repos/jobs/{job_id}
→ {"job_id": 1, "status": "completed", "phase": "done", "progress": 100, "repo_id": 1, "error": null}
```

**Ask a question (SSE stream)**

```
POST /query
{"question": "How do I add middleware?", "repo_id": 1, "history": []}
→ text/event-stream: {"content": "...", "done": false}
                     {"content": "", "done": true, "sources": [...]}
```

**List / delete repositories**

```
GET  /repos
DELETE /repos/{id}
```

**Health check**

```
GET /health
→ {"status": "ok"}
```

---

## Evaluation

The `backend/eval/` directory contains scripts to benchmark retrieval quality:

```bash
cd backend
python -m eval.generate_dataset   # create test Q&A pairs
python -m eval.run_eval           # run metrics against a live backend
```

Metrics include retrieval hit rate, keyword recall in answers, and correct refusal on out-of-scope questions.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `GitHub API rate limit reached` | Add `GITHUB_TOKEN` to `.env` and restart the backend |
| `Cannot connect to Ollama` | Start Ollama on the host: `ollama serve`. In Docker, confirm `host.docker.internal` resolves (Docker Desktop on Windows/macOS handles this automatically) |
| `Model not found in Ollama` | Pull the model: `ollama pull embeddinggemma:300m` |
| Frontend loads but API calls fail | Check backend health at [http://localhost:8000/health](http://localhost:8000/health) |
| Ingest finds no files | Repo may be private, empty, or contain no supported file types |
| Low-quality or refused answers | Try rephrasing, lowering `CONFIDENCE_THRESHOLD`, or loading a repo with more relevant docs |

---

## Stack

| Layer | Technology |
| --- | --- |
| **Frontend** | React 18, Vite, react-markdown |
| **Backend** | FastAPI, SQLAlchemy 2 async, Alembic |
| **Database** | PostgreSQL 16 + pgvector (HNSW index) + full-text search |
| **Embeddings** | Ollama — embeddinggemma:300m (768-dim) |
| **LLM** | Groq (primary) / Ollama (fallback) |
| **Serving** | nginx (SPA + reverse proxy) |
| **Infra** | Docker Compose |
