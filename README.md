# FinAudit AI

**Live demo:** [fin-audit-ai.vercel.app](https://fin-audit-ai.vercel.app) ·
[API docs](https://finaudit-api-dud4.onrender.com/docs)
*(free-tier hosting — the first request after idle takes ~1 minute to wake the API)*

AI-powered financial document audit and anomaly detection. Upload invoices (PDF) or
expense reports (CSV); a pipeline of small, single-purpose agents extracts structured
data, flags anomalies with rule-based **and** statistical checks, stores everything in
a relational database, and answers natural-language questions about it — all runnable
locally on free, open models.

```
 React frontend (Vercel)┌──────────────────────── FastAPI backend ────────────────────────┐
 ┌────────────────┐     │                                                                 │
 │ upload · charts│HTTP │   ┌──────────────┐    ┌─────────────────┐   ┌───────────────┐   │
 │ tables · triage├────▶│   │ Orchestrator │───▶│ Extraction Agent │──▶│ SQLite/       │  │
 │ chatbot        │     │   │  (pipeline)  │    │ pdfplumber + LLM │   │ PostgreSQL    │  │
 └────────────────┘     │   │              │───▶│ Validation Agent │──▶│ (SQLAlchemy)  │  │
                        │   └──────────────┘    │ rules + z-score  │   └──────┬────────┘  │
                        │                       └─────────────────┘           │           │
                        │   ┌──────────────┐    ┌──────────────────┐          │           │
                        │   │ /query       │───▶│ Query Agent      │◀─────────┘           │
                        │   └──────────────┘    │ SQL tools + RAG  │                      │
                        │                       └────────┬─────────┘                      │
                        │                          ┌─────┴──────┐                         │
                        │                          │ LLM client │ Ollama ⇄ Gemini         │
                        │                          └────────────┘ (env-var swap)          │
                        └─────────────────────────────────────────────────────────────────┘
```

The React frontend talks to the API exclusively over HTTP (it never imports backend
code), so the two halves deploy and scale independently. An always-available chatbot
widget fronts the Query Agent from any tab.

## The three agents

**Extraction Agent** (`backend/app/agents/extraction.py`)
Turns an uploaded file into structured records. CSV rows are already structured, so
they go through a deterministic parser — using an LLM there would only add cost and
failure modes. PDFs go `pdfplumber → LLM with a strict JSON prompt → field validation`,
with a regex extractor that (a) fills any field the LLM missed and (b) is the full
fallback when no LLM is reachable. Every document records its `extraction_method`,
so field provenance is auditable.

**Validation Agent** (`backend/app/agents/validation.py`)
Runs five checks against each new document and writes an `anomalies` row per hit,
each with a human-readable explanation and structured JSON evidence:

| Rule | How it works |
|---|---|
| `DUPLICATE_INVOICE` | exact: same vendor + invoice number; fuzzy: same vendor + amount within 3 days under a different reference |
| `AMOUNT_OUTLIER` | robust z-score (median/MAD, not mean/σ, so one earlier outlier can't mask the next) against that vendor+category's history, with a dispersion floor on the MAD so a small tightly-clustered history doesn't produce cold-start false positives; falls back to category-wide stats when vendor history < 5 documents |
| `MISSING_FIELD` | vendor, invoice number, date or amount absent |
| `DATE_INCONSISTENT` | future-dated, or > 3 years stale |
| `CATEGORY_MISMATCH` | keyword vote over line-item descriptions vs the declared category |

**Query Agent** (`backend/app/agents/query_agent.py`)
Natural language in, grounded answer out — but the LLM **never writes SQL**. Small
local models hallucinate SQL far too often to trust, so the agent routes each
question to one of six vetted, parameterized query tools (a small semantic layer):
numeric answers are always computed by real SQL. "Why was X flagged?" questions go
through the RAG layer instead: anomaly explanations and document summaries are
embedded (`nomic-embed-text` locally) into a `rag_chunks` table, retrieved by cosine
similarity, and the LLM answers strictly from that context. A deterministic keyword
router takes over whenever the LLM is down or returns unparseable JSON — the app
degrades, never dies.

The **Orchestrator** (`backend/app/agents/orchestrator.py`) is the only component
that knows the pipeline order (extract → persist → validate → index for RAG).
Agents never call each other, so each is testable in isolation.

## Why FastAPI (vs Flask)

- **Pydantic contracts**: every request/response is validated against typed models
  (`app/schemas.py`) — malformed input is rejected before handler code runs.
- **Dependency injection**: `db: Session = Depends(get_db)` gives each request its
  own DB session, closed automatically (Flask's `g` + teardown, but explicit and testable).
- **Auto-generated docs**: `/docs` serves a live Swagger UI derived from the code —
  great for demos.
- **ASGI**: async handlers (used for file upload) and production-grade serving via uvicorn.

## Run it locally

Prereqs: Python 3.11+, [Ollama](https://ollama.com) with two small models:

```bash
ollama pull llama3.2:3b        # extraction + query routing (~2 GB)
ollama pull nomic-embed-text   # embeddings for the RAG layer (~274 MB)
```

```bash
# 1. install
python -m venv .venv
.venv\Scripts\activate                      # (Windows; source .venv/bin/activate elsewhere)
pip install -r backend/requirements.txt -r dashboard/requirements.txt

# 2. generate demo data (30 invoice PDFs + expenses.csv, with planted anomalies —
#    see sample_data/PLANTED_ANOMALIES.md for the answer key)
python sample_data/generate_samples.py

# 3. start the API (terminal 1)
cd backend
uvicorn app.main:app --reload --port 8000

# 4. start the React frontend (terminal 2)
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Then upload the files from `sample_data/invoices/` + `sample_data/expenses.csv` from
the Documents tab and watch the detectors fire. Ask the chatbot (bottom-right):

- *"Which vendor had the most flagged invoices this month?"*
- *"Show me all anomalies above ₹50,000"*
- *"Why was Acme IT Solutions flagged?"* (RAG path)

No Ollama running? Everything still works — extraction falls back to regex,
routing falls back to keywords; `/health` reports which mode you're in.

Tests: `cd backend && pytest` (validation rules, extraction, query routing).
CI runs the same suite on every push (`.github/workflows/ci.yml`).

**Measuring quality — both layers**: the generator writes two machine-readable
answer keys, and after uploading the samples

```bash
python sample_data/evaluate.py
```

scores (1) **detection** — precision/recall of anomaly flags vs `planted.json`,
every miss and extra flag listed — and (2) **extraction** — field-level accuracy
(vendor, invoice number, date, amount, category) vs `ground_truth.json`. The sample
set includes three deliberately messy invoice layouts ('Bill No', 'Amount Due',
spelled-out dates, no category line) that the deterministic parser cannot handle,
so the LLM extraction path is exercised and measured, not assumed.

Anomalies are triaged from the dashboard (reviewed / dismissed via
`PATCH /anomalies/{id}`), giving flags a proper audit lifecycle instead of being a
write-only report.

Prefer containers? `docker compose up` starts API + frontend (Ollama stays on the
host).

## Swapping providers (the point of the abstractions)

| Swap | Change |
|---|---|
| SQLite → PostgreSQL | `DATABASE_URL=postgresql+psycopg2://...` in `.env` (+ `pip install psycopg2-binary`) |
| Ollama → Gemini | `LLM_PROVIDER=gemini` + `GEMINI_API_KEY=...` (free key from AI Studio) |
| Add OpenAI/Anthropic | subclass `LLMClient` in `app/llm/client.py` (~40 lines), register in `get_llm_client` |

## Deploying a live demo

Free hosts can't run Ollama (no GPU, ~512 MB RAM), which is exactly why the LLM
client is provider-agnostic:

1. **API on Render** (free tier): root dir `backend`, build `pip install -r
   requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   Env: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...`. Note: on the free tier the
   SQLite file is wiped on redeploy — fine for a demo; attach Render Postgres and
   set `DATABASE_URL` for persistence.
2. **Frontend on Vercel**: import the repo, set the root directory to `frontend`
   (Vite is auto-detected), add env var `VITE_API_URL=https://<your-api>.onrender.com`.
   (Vercel can't host the API itself: serverless functions have no persistent disk
   for SQLite, and Streamlit doesn't run on Vercel at all.)
3. Upload the sample data once after deploy so visitors see a populated dashboard.
   First request after idle takes ~50s (Render free tier cold start) — mention it
   next to the demo link.

## Honest limitations (also: interview talking points)

- **Scanned invoices are out of scope** — extraction needs a text layer in the PDF.
  Adding OCR (Tesseract/PaddleOCR) in front of the extractor is the natural next step.
- **The vector store is a table + numpy cosine similarity**, deliberately: at
  hundreds of rows a dedicated vector DB is ops burden with zero benefit. The swap
  point is isolated in `app/rag/store.py` if the corpus grows.
- **Anomaly thresholds** (z ≥ 2.5/3.5, history minimums) are constants in
  `validation.py`; a real deployment would tune them per client and add reviewer
  feedback loops (the `anomalies.status` column is already there for it).
