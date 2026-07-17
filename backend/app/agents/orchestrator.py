"""Orchestrator: the only component that knows the pipeline order.

upload -> ExtractionAgent -> persist document -> ValidationAgent ->
persist anomalies -> index both into the RAG store. Agents never call each
other directly, which keeps each one testable in isolation.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.extraction import ExtractedDoc, ExtractionAgent, normalize_vendor
from app.agents.validation import ValidationAgent
from app.db.models import Document, LineItem
from app.rag.store import rag_store

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self):
        self.extraction_agent = ExtractionAgent()
        self.validation_agent = ValidationAgent()

    def process_upload(self, db: Session, filename: str, content: bytes) -> dict:
        extracted = self.extraction_agent.extract(filename, content)

        document_ids: list[int] = []
        anomaly_summaries: list[str] = []
        total_anomalies = 0

        for ex in extracted:
            doc = self._persist_document(db, filename, ex)
            db.flush()  # assigns doc.id, needed by validation + FK rows

            anomalies = self.validation_agent.run(db, doc)
            if anomalies:
                doc.status = "needs_review"
            for anomaly in anomalies:
                db.add(anomaly)
            db.flush()

            rag_store.index_document(db, doc)
            for anomaly in anomalies:
                rag_store.index_anomaly(db, anomaly)
                anomaly_summaries.append(anomaly.explanation)

            document_ids.append(doc.id)
            total_anomalies += len(anomalies)

        db.commit()
        logger.info("Processed %s: %d document(s), %d anomaly(ies)",
                    filename, len(document_ids), total_anomalies)
        return {
            "documents_created": len(document_ids),
            "anomalies_flagged": total_anomalies,
            "document_ids": document_ids,
            "anomaly_summaries": anomaly_summaries,
        }

    def _persist_document(self, db: Session, filename: str, ex: ExtractedDoc) -> Document:
        doc = Document(
            filename=filename,
            file_type=ex.file_type,
            vendor_name=ex.vendor_name,
            vendor_normalized=normalize_vendor(ex.vendor_name),
            invoice_number=ex.invoice_number,
            invoice_date=ex.invoice_date,
            total_amount=ex.total_amount,
            currency=ex.currency,
            category=ex.category,
            status="processed",
            extraction_method=ex.extraction_method,
            raw_text=ex.raw_text,
            processed_at=datetime.now(timezone.utc),
        )
        db.add(doc)
        for item in ex.line_items:
            doc.line_items.append(
                LineItem(
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
            )
        return doc


orchestrator = Orchestrator()
