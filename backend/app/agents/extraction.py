"""Extraction Agent: turns an uploaded file into structured records.

CSV rows are already structured, so they go through a plain parser — using an
LLM there would only add cost and failure modes. PDFs go: pdfplumber text ->
LLM (strict JSON prompt) -> field validation, with a regex extractor both as
a cross-check filler and as a full fallback when no LLM is reachable. The
extraction_method field records which path produced each document.
"""
import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pdfplumber
from dateutil import parser as dateparser

from app.llm.client import get_llm_client
from app.llm.prompts import EXTRACTION_PROMPT, EXTRACTION_SYSTEM

logger = logging.getLogger(__name__)

KNOWN_CATEGORIES = ["IT Services", "Cloud Services", "Travel", "Office Supplies", "Marketing", "Other"]

# shared with the Validation Agent's category-mismatch check
CATEGORY_KEYWORDS = {
    "Travel": {"flight", "hotel", "airport", "travel", "ticket", "accommodation", "cab", "taxi"},
    "IT Services": {"software", "server", "application", "bug", "patch", "maintenance", "support"},
    "Cloud Services": {"cloud", "compute", "storage", "bandwidth", "database", "hosting", "instance"},
    "Office Supplies": {"paper", "toner", "stationery", "marker", "printer", "pen", "carton"},
    "Marketing": {"campaign", "ad", "seo", "influencer", "creative", "social", "branding"},
}


def infer_category(text: str) -> Optional[str]:
    """Keyword vote over line-item text; needs at least 2 keyword hits to call it."""
    text = text.lower()
    votes = {cat: sum(1 for kw in kws if kw in text) for cat, kws in CATEGORY_KEYWORDS.items()}
    best_cat, best_votes = max(votes.items(), key=lambda kv: kv[1])
    return best_cat if best_votes >= 2 else None


@dataclass
class ExtractedLineItem:
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


@dataclass
class ExtractedDoc:
    file_type: str
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total_amount: Optional[float] = None
    currency: str = "INR"
    category: Optional[str] = None
    raw_text: str = ""
    extraction_method: str = ""
    line_items: list[ExtractedLineItem] = field(default_factory=list)


def normalize_vendor(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def parse_amount(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"(rs\.?|inr|₹|,|\s)", "", str(value).lower())
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # ISO dates are unambiguous; dayfirst=True would swap their month/day
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    try:
        # dayfirst matches Indian convention (15-01-2027 = 15 Jan)
        return dateparser.parse(text, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


def normalize_category(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for cat in KNOWN_CATEGORIES:
        if cat.lower() == str(value).strip().lower():
            return cat
    return str(value).strip().title()


# ---------------------------------------------------------------- CSV path

CSV_COLUMN_ALIASES = {
    "date": {"date", "invoice_date", "expense_date"},
    "vendor": {"vendor", "vendor_name", "supplier", "payee"},
    "category": {"category", "expense_category", "type"},
    "description": {"description", "details", "memo"},
    "amount": {"amount", "total", "total_amount", "value"},
    "reference_no": {"reference_no", "ref", "reference", "invoice_no", "invoice_number"},
}


def _map_columns(header: list[str]) -> dict[str, str]:
    mapping = {}
    for col in header:
        key = col.strip().lower().replace(" ", "_")
        for canonical, aliases in CSV_COLUMN_ALIASES.items():
            if key in aliases:
                mapping[col] = canonical
    return mapping


def extract_from_csv(content: bytes) -> list[ExtractedDoc]:
    """Each CSV row becomes one document record."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    mapping = _map_columns(reader.fieldnames or [])
    docs = []
    for row in reader:
        canonical = {mapping.get(k): v for k, v in row.items() if mapping.get(k)}
        docs.append(
            ExtractedDoc(
                file_type="csv",
                vendor_name=(canonical.get("vendor") or "").strip() or None,
                invoice_number=(canonical.get("reference_no") or "").strip() or None,
                invoice_date=parse_date(canonical.get("date")),
                total_amount=parse_amount(canonical.get("amount")),
                category=normalize_category(canonical.get("category")),
                raw_text=", ".join(f"{k}: {v}" for k, v in row.items()),
                extraction_method="csv_parser",
                line_items=[
                    ExtractedLineItem(
                        description=(canonical.get("description") or "").strip(),
                        quantity=1,
                        unit_price=parse_amount(canonical.get("amount")),
                        amount=parse_amount(canonical.get("amount")),
                    )
                ],
            )
        )
    return docs


# ---------------------------------------------------------------- PDF path

INVOICE_NO_RE = re.compile(r"invoice\s*(?:no|number|#)\s*[:.]?\s*(\S+)", re.I)
DATE_RE = re.compile(r"(?:invoice\s*)?date\s*[:.]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)
TOTAL_RE = re.compile(
    r"(?:grand\s+total|amount\s+due|net\s+payable|total)\s*(?:\(inr\))?\s*[:.]?\s*"
    r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)
CATEGORY_RE = re.compile(r"category\s*[:.]?\s*(.+)", re.I)
LINE_ITEM_RE = re.compile(r"^(.+?)\s+(\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$")
BULLET_ITEM_RE = re.compile(r"^[-•*]\s*(.+?)\s+([\d,]+\.\d{2})$")


def regex_extract(text: str) -> ExtractedDoc:
    """Deterministic extractor: fills gaps in LLM output and is the full
    fallback when no LLM is reachable."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    doc = ExtractedDoc(file_type="pdf", raw_text=text, extraction_method="regex_fallback")

    if lines:
        doc.vendor_name = re.sub(r"\s*INVOICE\s*$", "", lines[0]).strip() or None

    if m := INVOICE_NO_RE.search(text):
        doc.invoice_number = m.group(1)
    if m := DATE_RE.search(text):
        doc.invoice_date = parse_date(m.group(1))
    if m := TOTAL_RE.search(text):
        doc.total_amount = parse_amount(m.group(1))
    if m := CATEGORY_RE.search(text):
        doc.category = normalize_category(m.group(1).splitlines()[0])

    for ln in lines:
        if ln.lower().startswith(("description", "total")):
            continue
        if m := LINE_ITEM_RE.match(ln):
            doc.line_items.append(
                ExtractedLineItem(
                    description=m.group(1).strip(),
                    quantity=float(m.group(2)),
                    unit_price=parse_amount(m.group(3)),
                    amount=parse_amount(m.group(4)),
                )
            )
        elif m := BULLET_ITEM_RE.match(ln):
            doc.line_items.append(
                ExtractedLineItem(description=m.group(1).strip(), amount=parse_amount(m.group(2)))
            )
    return doc


def llm_extract(text: str) -> Optional[ExtractedDoc]:
    client = get_llm_client()
    data = client.complete_json(EXTRACTION_PROMPT.format(text=text[:6000]), system=EXTRACTION_SYSTEM)
    if not data:
        return None
    doc = ExtractedDoc(
        file_type="pdf",
        vendor_name=(data.get("vendor_name") or None),
        invoice_number=(str(data["invoice_number"]) if data.get("invoice_number") else None),
        invoice_date=parse_date(data.get("invoice_date")),
        total_amount=parse_amount(data.get("total_amount")),
        currency=data.get("currency") or "INR",
        category=normalize_category(data.get("category")),
        raw_text=text,
        extraction_method=f"llm:{client.name}",
    )
    for item in data.get("line_items") or []:
        if isinstance(item, dict) and item.get("description"):
            doc.line_items.append(
                ExtractedLineItem(
                    description=str(item["description"]),
                    quantity=parse_amount(item.get("quantity")),
                    unit_price=parse_amount(item.get("unit_price")),
                    amount=parse_amount(item.get("amount")),
                )
            )
    return doc


def _finalize(doc: ExtractedDoc) -> ExtractedDoc:
    """Deterministic, auditable last-resort fills, applied to both paths;
    each one is recorded in extraction_method."""
    item_amounts = [li.amount for li in doc.line_items if li.amount is not None]
    if doc.total_amount is None and item_amounts:
        # line items are usually easier to extract than an oddly-labelled
        # total line, and their sum IS the total
        doc.total_amount = round(sum(item_amounts), 2)
        doc.extraction_method += "+derived_total"
        logger.info("Derived total %s from %d line items", doc.total_amount, len(item_amounts))
    if doc.category in (None, "Other") and doc.line_items:
        inferred = infer_category(" ".join(li.description or "" for li in doc.line_items))
        if inferred:
            doc.category = inferred
            doc.extraction_method += "+inferred_category"
    return doc


def extract_from_pdf(content: bytes) -> ExtractedDoc:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    regex_doc = regex_extract(text)
    llm_doc = llm_extract(text) if get_llm_client().available() else None
    if llm_doc is None:
        return _finalize(regex_doc)

    # Small local models occasionally drop a field the regex found; the
    # deterministic value fills the gap and the method records the mix.
    filled = []
    for attr in ("vendor_name", "invoice_number", "invoice_date", "total_amount", "category"):
        if getattr(llm_doc, attr) is None and getattr(regex_doc, attr) is not None:
            setattr(llm_doc, attr, getattr(regex_doc, attr))
            filled.append(attr)
    if not llm_doc.line_items:
        llm_doc.line_items = regex_doc.line_items
    elif regex_doc.line_items and not any(li.amount is not None for li in llm_doc.line_items):
        # LLM found descriptions but lost the numbers; the regex version has them
        llm_doc.line_items = regex_doc.line_items
        filled.append("line_items")
    if filled:
        llm_doc.extraction_method += "+regex"
        logger.info("Regex filled fields missed by LLM: %s", filled)
    return _finalize(llm_doc)


class ExtractionAgent:
    def extract(self, filename: str, content: bytes) -> list[ExtractedDoc]:
        name = filename.lower()
        if name.endswith(".csv"):
            return extract_from_csv(content)
        if name.endswith(".pdf"):
            return [extract_from_pdf(content)]
        raise ValueError(f"Unsupported file type: {filename} (only .pdf and .csv)")
