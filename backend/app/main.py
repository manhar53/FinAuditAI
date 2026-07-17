"""FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload --port 8000   (from backend/)
Interactive API docs are auto-generated at http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import anomalies, documents, query, stats
from app.db import models  # noqa: F401  (registers tables with Base before create_all)
from app.db.database import Base, engine
from app.llm.client import get_llm_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="FinAudit AI",
    description="AI-powered financial document audit and anomaly detection",
    version="1.0.0",
)

# The Streamlit dashboard is a separate origin (different port / host),
# so the browser-facing API must allow cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(anomalies.router)
app.include_router(query.router)
app.include_router(stats.router)


@app.get("/health")
def health():
    client = get_llm_client(refresh=True)
    return {"status": "ok", "llm_provider": client.name, "llm_available": client.available()}
