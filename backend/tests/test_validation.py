from datetime import date, timedelta

from app.db.models import Document, LineItem
from app.agents.validation import ValidationAgent

agent = ValidationAgent()


def make_doc(db, vendor="Acme IT Solutions", amount=95_000, category="IT Services",
             invoice_number=None, invoice_date=None, **kwargs):
    doc = Document(
        filename="test.pdf",
        file_type="pdf",
        vendor_name=vendor,
        vendor_normalized=vendor.lower(),
        invoice_number=invoice_number or f"INV-{id(object())}",
        invoice_date=invoice_date or date(2026, 6, 10),
        total_amount=amount,
        category=category,
        status="processed",
        **kwargs,
    )
    db.add(doc)
    db.flush()
    return doc


def seed_history(db, n=6, base=90_000):
    for i in range(n):
        make_doc(db, amount=base + i * 2_000, invoice_date=date(2026, 1 + i % 6, 5),
                 invoice_number=f"INV-HIST-{i}")


def rule_codes(anomalies):
    return {a.rule_code for a in anomalies}


def test_amount_outlier_flagged(db):
    seed_history(db)
    outlier = make_doc(db, amount=480_000)
    anomalies = agent.run(db, outlier)
    assert "AMOUNT_OUTLIER" in rule_codes(anomalies)
    outlier_anomaly = next(a for a in anomalies if a.rule_code == "AMOUNT_OUTLIER")
    assert outlier_anomaly.severity == "high"
    assert outlier_anomaly.score > 3.5


def test_normal_amount_not_flagged(db):
    seed_history(db)
    normal = make_doc(db, amount=97_000)
    assert "AMOUNT_OUTLIER" not in rule_codes(agent.run(db, normal))


def test_high_normal_with_tight_history_not_flagged(db):
    """Cold-start guard: 5 near-identical amounts must not make a slightly
    higher (but normal) amount look like an outlier — the MAD floor applies."""
    for i in range(5):
        make_doc(db, amount=90_000 + i * 500, invoice_number=f"INV-TIGHT-{i}")
    high_normal = make_doc(db, amount=106_000)
    assert "AMOUNT_OUTLIER" not in rule_codes(agent.run(db, high_normal))


def test_duplicate_invoice_number(db):
    make_doc(db, invoice_number="INV-1001")
    dup = make_doc(db, invoice_number="INV-1001")
    anomalies = agent.run(db, dup)
    assert "DUPLICATE_INVOICE" in rule_codes(anomalies)
    assert next(a for a in anomalies if a.rule_code == "DUPLICATE_INVOICE").severity == "high"


def test_fuzzy_duplicate_same_amount_nearby_date(db):
    make_doc(db, invoice_number="INV-2001", amount=50_000, invoice_date=date(2026, 6, 10))
    near = make_doc(db, invoice_number="INV-2002", amount=50_000, invoice_date=date(2026, 6, 12))
    anomalies = agent.run(db, near)
    dup = next(a for a in anomalies if a.rule_code == "DUPLICATE_INVOICE")
    assert dup.severity == "medium"


def test_missing_fields(db):
    doc = Document(filename="bad.pdf", file_type="pdf", status="processed")
    db.add(doc)
    db.flush()
    anomalies = agent.run(db, doc)
    missing = next(a for a in anomalies if a.rule_code == "MISSING_FIELD")
    assert "total_amount" in missing.details["missing_fields"]
    assert missing.severity == "high"


def test_future_date_flagged(db):
    doc = make_doc(db, invoice_date=date.today() + timedelta(days=90))
    anomalies = agent.run(db, doc)
    assert "DATE_INCONSISTENT" in rule_codes(anomalies)


def test_category_mismatch(db):
    doc = make_doc(db, category="Office Supplies")
    doc.line_items.append(LineItem(description="Flight tickets DEL-BLR", amount=20_000))
    doc.line_items.append(LineItem(description="Hotel accommodation", amount=18_000))
    db.flush()
    anomalies = agent.run(db, doc)
    mismatch = next(a for a in anomalies if a.rule_code == "CATEGORY_MISMATCH")
    assert mismatch.details["suggested"] == "Travel"
