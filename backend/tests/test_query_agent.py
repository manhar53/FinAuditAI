from datetime import date

from app.agents.query_agent import _extract_amount, keyword_route, query_agent, sanitize_params
from app.db.models import Anomaly, Document


def seed(db):
    doc = Document(
        filename="inv.pdf", file_type="pdf", vendor_name="Acme IT Solutions",
        vendor_normalized="acme it solutions", invoice_number="INV-1",
        invoice_date=date(2026, 7, 8), total_amount=480_000,
        category="IT Services", status="needs_review",
    )
    db.add(doc)
    db.flush()
    db.add(Anomaly(document_id=doc.id, rule_code="AMOUNT_OUTLIER", severity="high",
                   explanation="480,000.00 is a +9.1-sigma outlier", score=9.1, details={}))
    db.flush()


def test_extract_amount_variants():
    assert _extract_amount("above ₹50,000") == 50_000
    assert _extract_amount("over 50k") == 50_000
    assert _extract_amount("more than 1.5 lakh") == 150_000


def test_sanitize_drops_hallucinated_dates():
    # "monthly" is granularity, not a time range — invented dates must go
    assert sanitize_params("What is the monthly spend trend?", {"start_date": "2026-07-01"}) == {}


def test_sanitize_keeps_real_time_refs():
    params = {"start_date": "2026-07-01"}
    assert sanitize_params("flagged invoices this month", dict(params)) == params
    assert sanitize_params("spend since March", dict(params)) == params


def test_keyword_route_top_vendors(db):
    tool, params = keyword_route(db, "which vendor had the most flagged invoices this month?")
    assert tool == "top_vendors_by_anomalies"
    assert params["start_date"].endswith("-01")


def test_keyword_route_above_amount(db):
    tool, params = keyword_route(db, "show me all anomalies above ₹50,000")
    assert tool == "anomalies_above_amount"
    assert params["min_amount"] == 50_000


def test_keyword_route_vendor_summary(db):
    seed(db)
    tool, params = keyword_route(db, "give me a summary for Acme IT Solutions")
    assert tool == "vendor_summary"
    assert params["vendor"] == "Acme IT Solutions"


def test_end_to_end_tool_answer(db, monkeypatch):
    # force the keyword path so the test never depends on a live LLM
    monkeypatch.setattr("app.agents.query_agent.llm_route", lambda q: None)
    seed(db)
    res = query_agent.answer(db, "show me all anomalies above ₹50,000")
    assert res["rows"], res
    assert res["rows"][0]["vendor"] == "Acme IT Solutions"
    assert "keyword_router" in res["tool_used"]
