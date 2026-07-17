"""RAG store: indexes anomaly explanations and document summaries.

Embeddings live in a plain DB table with cosine similarity in numpy — at
portfolio scale (hundreds of rows) a dedicated vector DB adds ops burden for
zero benefit; the swap point is isolated here if the corpus ever grows.
Degrades to keyword-overlap scoring when no embedding model is reachable.
"""
import logging
import re

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import Anomaly, Document, RagChunk
from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)


def summarize_document(doc: Document) -> str:
    parts = [f"Document #{doc.id} ('{doc.filename}')"]
    if doc.vendor_name:
        parts.append(f"from vendor {doc.vendor_name}")
    if doc.invoice_number:
        parts.append(f"invoice number {doc.invoice_number}")
    if doc.invoice_date:
        parts.append(f"dated {doc.invoice_date.isoformat()}")
    if doc.total_amount is not None:
        parts.append(f"amount {float(doc.total_amount):,.2f} {doc.currency or 'INR'}")
    if doc.category:
        parts.append(f"category {doc.category}")
    return ", ".join(parts) + "."


class RagStore:
    def index_document(self, db: Session, doc: Document):
        self._add(db, "document", doc.id, summarize_document(doc))

    def index_anomaly(self, db: Session, anomaly: Anomaly):
        self._add(db, "anomaly", anomaly.id, f"[{anomaly.rule_code}, {anomaly.severity}] {anomaly.explanation}")

    def _add(self, db: Session, source_type: str, source_id: int, text: str):
        embedding = get_llm_client().embed(text)
        db.add(RagChunk(source_type=source_type, source_id=source_id, text=text, embedding=embedding))

    def search(self, db: Session, query: str, k: int = 6) -> list[RagChunk]:
        chunks = db.query(RagChunk).all()
        if not chunks:
            return []

        query_emb = get_llm_client().embed(query)
        embedded = [c for c in chunks if c.embedding]
        if query_emb and embedded:
            q = np.array(query_emb)
            matrix = np.array([c.embedding for c in embedded])
            sims = matrix @ q / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q) + 1e-9)
            ranked = sorted(zip(sims.tolist(), embedded), key=lambda p: p[0], reverse=True)
            return [c for _, c in ranked[:k]]

        # keyword-overlap fallback
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        scored = [
            (len(terms & set(re.findall(r"[a-z0-9]+", c.text.lower()))), c) for c in chunks
        ]
        scored.sort(key=lambda p: p[0], reverse=True)
        return [c for score, c in scored[:k] if score > 0]


rag_store = RagStore()
