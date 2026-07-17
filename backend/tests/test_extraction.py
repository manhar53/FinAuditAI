from datetime import date

from app.agents.extraction import _finalize, extract_from_csv, parse_amount, regex_extract

SAMPLE_TEXT = """Acme IT Solutions INVOICE
4th Floor, Cyber Towers, Hyderabad 500081
Invoice No: INV-AI-1003
Invoice Date: 08-07-2026
Bill To: FinAudit Demo Corp, 12 MG Road, Bengaluru 560001
Category: IT Services
Description Qty Unit Price Amount
Bug-fix sprint 1 45,000.00 45,000.00
Server maintenance 1 53,500.00 53,500.00
Total: Rs. 98,500.00
"""


def test_regex_extract_fields():
    doc = regex_extract(SAMPLE_TEXT)
    assert doc.vendor_name == "Acme IT Solutions"
    assert doc.invoice_number == "INV-AI-1003"
    assert doc.invoice_date == date(2026, 7, 8)
    assert doc.total_amount == 98_500.0
    assert doc.category == "IT Services"
    assert len(doc.line_items) == 2
    assert doc.line_items[0].description == "Bug-fix sprint"


MESSY_TEXT = """PURCHASE MEMO
OfficeMart Supplies
Warehouse 3, Bhiwandi, Thane 421302
Memo no. OM/JUL/22
Dt. 11-07-2026
- Printer toner 6,250.00
- A4 paper cartons 3,500.00
Net Payable Rs 9,750.00
"""


def test_regex_handles_messy_labels_and_bullets():
    doc = regex_extract(MESSY_TEXT)
    assert doc.total_amount == 9_750.0  # "Net Payable" label
    assert len(doc.line_items) == 2  # bullet-style items
    assert doc.line_items[0].amount == 6_250.0


def test_finalize_derives_total_and_infers_category():
    doc = regex_extract(MESSY_TEXT)
    doc.total_amount = None  # simulate the total line being missed
    doc.category = None
    doc = _finalize(doc)
    assert doc.total_amount == 9_750.0
    assert doc.category == "Office Supplies"
    assert "derived_total" in doc.extraction_method
    assert "inferred_category" in doc.extraction_method


def test_parse_amount_formats():
    assert parse_amount("Rs. 4,80,000.00") == 480_000.0
    assert parse_amount("₹50,000") == 50_000.0
    assert parse_amount(1234.5) == 1234.5
    assert parse_amount("not a number") is None


def test_csv_extraction():
    csv_bytes = (
        "date,vendor,category,description,amount,reference_no\n"
        "2026-07-12,BrightSpark Marketing,Marketing,SEO retainer,70000,EXP-5021\n"
        "2026-07-13,BrightSpark Marketing,Marketing,Ad creative design,65000,EXP-5022\n"
    ).encode()
    docs = extract_from_csv(csv_bytes)
    assert len(docs) == 2
    assert docs[0].vendor_name == "BrightSpark Marketing"
    assert docs[0].invoice_number == "EXP-5021"
    assert docs[0].total_amount == 70_000.0
    assert docs[0].invoice_date == date(2026, 7, 12)
    assert docs[0].extraction_method == "csv_parser"
