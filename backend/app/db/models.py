"""ORM models: documents, line_items, anomalies, rag_chunks.

Types are chosen to map cleanly onto both SQLite and PostgreSQL
(Numeric, Date, JSON all work on both engines).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # 'pdf' | 'csv'
    vendor_name = Column(String)
    vendor_normalized = Column(String, index=True)
    invoice_number = Column(String, index=True)
    invoice_date = Column(Date)
    total_amount = Column(Numeric(12, 2))
    currency = Column(String, default="INR")
    category = Column(String, index=True)
    status = Column(String, nullable=False, default="processed")  # processed | failed | needs_review
    extraction_method = Column(String)  # 'csv_parser' | 'llm' | 'regex_fallback'
    raw_text = Column(Text)
    uploaded_at = Column(DateTime, default=utcnow)
    processed_at = Column(DateTime)

    line_items = relationship("LineItem", back_populates="document", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="document", cascade="all, delete-orphan")


class LineItem(Base):
    __tablename__ = "line_items"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    description = Column(Text)
    quantity = Column(Numeric(10, 2))
    unit_price = Column(Numeric(12, 2))
    amount = Column(Numeric(12, 2))

    document = relationship("Document", back_populates="line_items")


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    rule_code = Column(String, nullable=False, index=True)
    # DUPLICATE_INVOICE | AMOUNT_OUTLIER | MISSING_FIELD | DATE_INCONSISTENT | CATEGORY_MISMATCH
    severity = Column(String, nullable=False)  # low | medium | high
    score = Column(Float)  # robust z-score for outliers, NULL for rule hits
    explanation = Column(Text, nullable=False)  # human-readable; indexed by the RAG store
    details = Column(JSON)  # structured evidence (duplicate doc id, stats used, ...)
    status = Column(String, default="open")  # open | reviewed | dismissed
    created_at = Column(DateTime, default=utcnow)

    document = relationship("Document", back_populates="anomalies")


class RagChunk(Base):
    """Text chunks (anomaly explanations, document summaries) with their
    embedding vector, for the Query Agent's retrieval layer."""

    __tablename__ = "rag_chunks"

    id = Column(Integer, primary_key=True)
    source_type = Column(String, nullable=False)  # 'anomaly' | 'document'
    source_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(JSON)  # list[float]; NULL if no embed model was reachable
    created_at = Column(DateTime, default=utcnow)
