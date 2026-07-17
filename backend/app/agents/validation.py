"""Validation Agent: runs every check against a freshly extracted document
and returns Anomaly rows (unsaved — the orchestrator owns the transaction).

Two kinds of checks:
  - deterministic rules: duplicates, missing fields, date logic, category keywords
  - statistical: robust z-score (median/MAD) of the amount against that
    vendor+category's history. Median/MAD instead of mean/std so one earlier
    outlier can't inflate sigma and mask the next one.
"""
from datetime import date, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Anomaly, Document

MIN_VENDOR_HISTORY = 5   # need this many prior amounts before vendor-level z-scores
MIN_CATEGORY_HISTORY = 8 # fallback pool: category-wide across vendors
Z_MEDIUM = 2.5
Z_HIGH = 3.5
MAD_FLOOR_RATIO = 0.075  # assume at least this much relative dispersion; a small,
                         # tightly-clustered history otherwise turns normal
                         # variation into cold-start false positives
STALE_YEARS = 3

from app.agents.extraction import CATEGORY_KEYWORDS  # single source for both agents

REQUIRED_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "total_amount")


def _anomaly(doc: Document, rule: str, severity: str, explanation: str,
             score: Optional[float] = None, details: Optional[dict] = None) -> Anomaly:
    return Anomaly(document_id=doc.id, rule_code=rule, severity=severity,
                   explanation=explanation, score=score, details=details or {})


class ValidationAgent:
    def run(self, db: Session, doc: Document) -> list[Anomaly]:
        anomalies = []
        anomalies += self._check_missing_fields(doc)
        anomalies += self._check_duplicates(db, doc)
        anomalies += self._check_dates(doc)
        anomalies += self._check_category(db, doc)
        anomalies += self._check_amount_outlier(db, doc)
        return anomalies

    def _check_missing_fields(self, doc: Document) -> list[Anomaly]:
        missing = [f for f in REQUIRED_FIELDS if getattr(doc, f) in (None, "")]
        if not missing:
            return []
        severity = "high" if "total_amount" in missing else "medium"
        return [_anomaly(
            doc, "MISSING_FIELD", severity,
            f"'{doc.filename}' is missing required field(s): {', '.join(missing)}.",
            details={"missing_fields": missing},
        )]

    def _check_duplicates(self, db: Session, doc: Document) -> list[Anomaly]:
        anomalies = []
        if doc.invoice_number and doc.vendor_normalized:
            twin = (
                db.query(Document)
                .filter(
                    Document.id != doc.id,
                    Document.vendor_normalized == doc.vendor_normalized,
                    Document.invoice_number == doc.invoice_number,
                )
                .first()
            )
            if twin:
                anomalies.append(_anomaly(
                    doc, "DUPLICATE_INVOICE", "high",
                    f"Invoice {doc.invoice_number} from {doc.vendor_name} was already recorded "
                    f"(document #{twin.id}, file '{twin.filename}'). Possible double billing.",
                    details={"duplicate_of_document_id": twin.id},
                ))

        # fuzzy: same vendor, same amount, dates within 3 days, different number
        if not anomalies and doc.vendor_normalized and doc.total_amount and doc.invoice_date:
            near = (
                db.query(Document)
                .filter(
                    Document.id != doc.id,
                    Document.vendor_normalized == doc.vendor_normalized,
                    Document.total_amount == doc.total_amount,
                    Document.invoice_date.between(
                        doc.invoice_date - timedelta(days=3),
                        doc.invoice_date + timedelta(days=3),
                    ),
                )
                .first()
            )
            if near:
                anomalies.append(_anomaly(
                    doc, "DUPLICATE_INVOICE", "medium",
                    f"{doc.vendor_name} billed the same amount ({doc.total_amount}) within 3 days "
                    f"under a different reference (document #{near.id}). Possible duplicate submission.",
                    details={"duplicate_of_document_id": near.id},
                ))
        return anomalies

    def _check_dates(self, doc: Document) -> list[Anomaly]:
        if not doc.invoice_date:
            return []
        today = date.today()
        if doc.invoice_date > today:
            return [_anomaly(
                doc, "DATE_INCONSISTENT", "high",
                f"Invoice {doc.invoice_number or doc.filename} from {doc.vendor_name} is dated "
                f"{doc.invoice_date.isoformat()}, which is in the future.",
                details={"invoice_date": doc.invoice_date.isoformat()},
            )]
        if doc.invoice_date < today - timedelta(days=365 * STALE_YEARS):
            return [_anomaly(
                doc, "DATE_INCONSISTENT", "low",
                f"Invoice {doc.invoice_number or doc.filename} is over {STALE_YEARS} years old "
                f"({doc.invoice_date.isoformat()}) — unusually stale for a new submission.",
                details={"invoice_date": doc.invoice_date.isoformat()},
            )]
        return []

    def _check_category(self, db: Session, doc: Document) -> list[Anomaly]:
        """Keyword vote over line-item descriptions vs the declared category."""
        if not doc.category:
            return []
        text = " ".join((li.description or "") for li in doc.line_items).lower()
        if not text.strip():
            return []
        votes = {
            cat: sum(1 for kw in kws if kw in text)
            for cat, kws in CATEGORY_KEYWORDS.items()
        }
        best_cat, best_votes = max(votes.items(), key=lambda kv: kv[1])
        declared_votes = votes.get(doc.category, 0)
        if best_votes >= 2 and best_cat != doc.category and declared_votes == 0:
            return [_anomaly(
                doc, "CATEGORY_MISMATCH", "medium",
                f"Invoice {doc.invoice_number or doc.filename} is categorised '{doc.category}' but its "
                f"line items ({text[:80]}...) look like '{best_cat}'.",
                details={"declared": doc.category, "suggested": best_cat, "keyword_votes": votes},
            )]
        return []

    def _amount_history(self, db: Session, doc: Document) -> tuple[list[float], str]:
        """Prior amounts for this vendor+category; falls back to category-wide."""
        base = db.query(Document.total_amount).filter(
            Document.id != doc.id,
            Document.total_amount.isnot(None),
            Document.category == doc.category,
        )
        vendor_amounts = [
            float(a) for (a,) in base.filter(Document.vendor_normalized == doc.vendor_normalized).all()
        ]
        if len(vendor_amounts) >= MIN_VENDOR_HISTORY:
            return vendor_amounts, "vendor"
        category_amounts = [float(a) for (a,) in base.all()]
        if len(category_amounts) >= MIN_CATEGORY_HISTORY:
            return category_amounts, "category"
        return [], "insufficient"

    def _check_amount_outlier(self, db: Session, doc: Document) -> list[Anomaly]:
        if doc.total_amount is None or not doc.category:
            return []
        history, scope = self._amount_history(db, doc)
        if not history:
            return []

        amounts = np.array(history)
        median = float(np.median(amounts))
        mad = float(np.median(np.abs(amounts - median)))
        effective_mad = max(mad, MAD_FLOOR_RATIO * abs(median))
        if effective_mad == 0:
            return []
        z = 0.6745 * (float(doc.total_amount) - median) / effective_mad

        if abs(z) < Z_MEDIUM:
            return []
        severity = "high" if abs(z) >= Z_HIGH else "medium"
        scope_desc = (
            f"{doc.vendor_name} typically bills in {doc.category}"
            if scope == "vendor"
            else f"is typical for the {doc.category} category"
        )
        # lead with plain language ("5x the typical amount"); keep the z-score
        # as supporting evidence for the statistically inclined
        amount = float(doc.total_amount)
        ratio = amount / median if median else 0
        if ratio >= 1:
            comparison = f"about {ratio:,.1f}x what {scope_desc}"
        else:
            comparison = f"only {ratio:.0%} of what {scope_desc}"
        return [_anomaly(
            doc, "AMOUNT_OUTLIER", severity,
            f"Amount {amount:,.2f} on invoice {doc.invoice_number or doc.filename} is {comparison} "
            f"(typical: {median:,.2f} across {len(history)} documents; robust z-score {z:+.1f}).",
            score=round(z, 2),
            details={"median": median, "mad": mad, "effective_mad": effective_mad,
                     "n": len(history), "scope": scope},
        )]
