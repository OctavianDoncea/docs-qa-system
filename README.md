# docs-qa

Ask natural language questions about any public GitHub repository and get cited answers sourced directly from the documentation.

---

## How it works

1. Paste a GitHub URL and click **Load docs**. The backend fetches every `.md`, `.rst`, and `.txt` file, splits them into overlapping chunks, and stores 768-dimensional embeddings in PostgreSQL with pgvector.
2. Ask a question. The question is embedded with the same model, the top most similar chunks are retrieved by cosine search, and Groq's LLM generates an answer with instructions to cite every claim.
3. The answer arrives with inline citations `[1]` `[2]` that map to collapsible source cards showing the exact chunk behind each claim.

---

## Architecture

```
Browser
   │
   ▼
nginx (frontend) :80
   ├── static assets
   └── /repos, /query, /health ──► FastAPI (backend)
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
                    Ollama (host)   PostgreSQL      Groq (cloud)
                    embeddinggemma  + pgvector     llama-3.1-8b
                    :300m           vector(768)     free tier
                    embed
```

---

## Quick start

### Prerequisites

- Docker and Docker Compose
- [Ollama](https://ollama.com) installed and running, with the model pulled:

  ```bash
  ollama pull embeddinggemma:300m
  ```

- A free Groq API key from [console.groq.com](https://console.groq.com)

### Run

```bash
git clone https://github.com/OctavianDoncea/docs-qa-system
cd docs-qa-system

cp .env.example .env
# Open .env and set GROQ_API_KEY=gsk_...

docker compose up --build
```

Open [http://localhost:5173](http://localhost:5173).

First build takes 3–5 minutes (Python deps + Node build). Subsequent starts are fast.

### Local development (no Docker)

```bash
# Terminal 1 — database only
docker compose up db -d

# Terminal 2 — backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # set GROQ_API_KEY
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 3 — frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

---

## API

Full interactive docs at [http://localhost:8000/docs](http://localhost:8000/docs).

**Ingest a repository**

```
POST /repos
{"url": "https://github.com/owner/repo", "reingest": false}
→ {"id": 1, "name": "owner/repo", "chunk_count": 312}
```

**Ask a question**

```
POST /query
{"question": "How do I add middleware?", "repo_id": 1}
→ {"answer": "...[1]...", "sources": [{"index": 1, "file_path": "...", "score": 0.87}]}
```

**List / delete repositories**

```
GET /repos
DELETE /repos/{id}
```

---

## Design decisions

**pgvector over Pinecone or Chroma**

Pinecone is managed but adds an external paid dependency. Chroma is simple to prototype but runs as a separate process and loses ACID guarantees for the metadata. pgvector gives vector search inside the same PostgreSQL instance that already holds the chunk text, which means chunk retrieval is a single indexed query rather than a vector search followed by a metadata lookup. The HNSW index keeps latency under 20 ms for corpora up to tens of millions of vectors.

**Ollama + embeddinggemma:300m over OpenAI embeddings**

Completely free, runs offline, no rate limits during ingestion of large repos. embeddinggemma is an asymmetric model that distinguishes between document encoding and query encoding at the architecture level, which in principle improves retrieval precision compared to symmetric models. Moving embedding computation into a sidecar process (Ollama) rather than loading the model inside FastAPI also keeps the Python process lean.

**Groq over OpenAI or Anthropic for LLM inference**

Groq's free tier provides 14,400 requests/day at roughly 100 tokens/second. For a documentation Q&A task where the model is given the full context and asked only to synthesize and cite it, llama-3.1-8b-instant is accurate enough and fast enough that latency is dominated by the embedding call, not the generation.

**Markdown-aware chunking over fixed-size splitting**

Splitting on heading boundaries means each chunk starts at a logical section. This has two practical effects: the source cards in the UI show readable, coherent sections rather than mid-sentence fragments, and the LLM has better context for citation because each retrieved chunk is a complete thought. Paragraph and sentence splitting only trigger when a section exceeds the character limit, preserving structure at every level.

**Raw SQL for vector search**

Using `text()` with `::vector` cast in the similarity query is more reliable with asyncpg than ORM-level operators. The explicit SQL is also easier to profile and index-hint when the corpus grows.

**Latency profile per query**

| Step | Typical |
| --- | --- |
| Embed query (Ollama, warm) | ~50 ms |
| pgvector HNSW search | ~15 ms |
| Groq LLM call | ~500 ms |
| **Total** | **~600 ms** |

---

## Stack

| Layer | Technology |
| --- | --- |
| **Frontend** | React 18 + Vite, plain CSS |
| **Backend** | FastAPI, SQLAlchemy 2 async, Alembic |
| **Database** | PostgreSQL 16 + pgvector (HNSW index) |
| **Embeddings** | Ollama – embeddinggemma:300m (768-dim) |
| **LLM** | Groq free tier – llama-3.1-8b-instant |
| **Serving** | nginx (SPA + reverse proxy) |
| **Infra** | Docker Compose |
