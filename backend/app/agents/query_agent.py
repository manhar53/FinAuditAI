"""Query Agent: natural language -> answer over the audit database.

Design: the LLM never writes SQL. It routes the question to one of a fixed
catalog of parameterized, vetted query tools (a small semantic layer), so
numeric answers are always computed by real SQL — a 3B local model asked to
write free-form SQL gets it wrong far too often to demo. "Why was X
flagged?"-style questions instead go through the RAG store over anomaly
explanations. A keyword router covers the case where the LLM is down or
returns unparseable JSON.
"""
import logging
import re
from datetime import date
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.extraction import normalize_vendor, parse_date
from app.db.models import Anomaly, Document
from app.llm.client import get_llm_client
from app.llm.prompts import RAG_ANSWER_PROMPT, RAG_ANSWER_SYSTEM, ROUTER_PROMPT, ROUTER_SYSTEM
from app.rag.store import rag_store

logger = logging.getLogger(__name__)


def _fmt(amount) -> str:
    return f"{float(amount):,.2f}" if amount is not None else "-"


def _date_filters(query, column, params: dict):
    if start := parse_date(params.get("start_date")):
        query = query.filter(column >= start)
    if end := parse_date(params.get("end_date")):
        query = query.filter(column <= end)
    return query


# ------------------------------------------------------------ query tools

def top_vendors_by_anomalies(db: Session, params: dict):
    q = (
        db.query(Document.vendor_name, func.count(Anomaly.id).label("anomaly_count"))
        .join(Anomaly, Anomaly.document_id == Document.id)
        .filter(Document.vendor_name.isnot(None))
    )
    q = _date_filters(q, Document.invoice_date, params)
    limit = int(params.get("limit") or 5)
    rows = (
        q.group_by(Document.vendor_name)
        .order_by(func.count(Anomaly.id).desc())
        .limit(limit)
        .all()
    )
    data = [{"vendor": v, "anomaly_count": c} for v, c in rows]
    if not data:
        return data, "No flagged documents found for that period."
    top = data[0]
    return data, (
        f"{top['vendor']} has the most flagged documents ({top['anomaly_count']} anomalies). "
        f"Full ranking: " + ", ".join(f"{r['vendor']} ({r['anomaly_count']})" for r in data) + "."
    )


def anomalies_above_amount(db: Session, params: dict):
    q = (
        db.query(Anomaly, Document)
        .join(Document, Anomaly.document_id == Document.id)
        .filter(Document.total_amount.isnot(None))
    )
    if (min_amount := params.get("min_amount")) is not None:
        q = q.filter(Document.total_amount >= float(min_amount))
    if severity := params.get("severity"):
        q = q.filter(Anomaly.severity == str(severity).lower())
    q = _date_filters(q, Document.invoice_date, params)
    rows = q.order_by(Document.total_amount.desc()).limit(50).all()
    data = [
        {
            "anomaly_id": a.id,
            "rule_code": a.rule_code,
            "severity": a.severity,
            "vendor": d.vendor_name,
            "invoice_number": d.invoice_number,
            "amount": float(d.total_amount),
            "date": d.invoice_date.isoformat() if d.invoice_date else None,
            "explanation": a.explanation,
        }
        for a, d in rows
    ]
    threshold = f" on documents of {_fmt(min_amount)}+" if params.get("min_amount") is not None else ""
    if not data:
        return data, f"No anomalies found{threshold}."
    return data, (
        f"Found {len(data)} anomal{'y' if len(data) == 1 else 'ies'}{threshold}. Largest: "
        f"{data[0]['vendor']} invoice {data[0]['invoice_number']} at {_fmt(data[0]['amount'])} "
        f"({data[0]['rule_code']}, {data[0]['severity']})."
    )


def spend_by_category(db: Session, params: dict):
    q = (
        db.query(
            Document.category,
            func.sum(Document.total_amount).label("total"),
            func.count(Document.id).label("documents"),
        )
        .filter(Document.total_amount.isnot(None), Document.category.isnot(None))
    )
    q = _date_filters(q, Document.invoice_date, params)
    rows = q.group_by(Document.category).order_by(func.sum(Document.total_amount).desc()).all()
    data = [{"category": c, "total": float(t), "documents": n} for c, t, n in rows]
    if not data:
        return data, "No spend recorded for that period."
    return data, "Spend by category: " + ", ".join(f"{r['category']} {_fmt(r['total'])}" for r in data) + "."


def spend_over_time(db: Session, params: dict):
    """Monthly totals, aggregated in Python for SQLite/Postgres portability."""
    q = db.query(Document.invoice_date, Document.total_amount, Document.id).filter(
        Document.invoice_date.isnot(None), Document.total_amount.isnot(None)
    )
    q = _date_filters(q, Document.invoice_date, params)
    flagged_ids = {doc_id for (doc_id,) in db.query(Anomaly.document_id).distinct().all()}

    months: dict[str, dict] = {}
    for inv_date, amount, doc_id in q.all():
        key = inv_date.strftime("%Y-%m")
        bucket = months.setdefault(key, {"month": key, "total": 0.0, "documents": 0, "flagged": 0})
        bucket["total"] += float(amount)
        bucket["documents"] += 1
        if doc_id in flagged_ids:
            bucket["flagged"] += 1
    data = sorted(months.values(), key=lambda r: r["month"])
    if not data:
        return data, "No dated documents found for that period."
    latest = data[-1]
    return data, (
        f"Monthly trend over {len(data)} month(s); latest ({latest['month']}): "
        f"{_fmt(latest['total'])} across {latest['documents']} documents, {latest['flagged']} flagged."
    )


def vendor_summary(db: Session, params: dict):
    vendor_norm = normalize_vendor(params.get("vendor"))
    if not vendor_norm:
        return [], "Please name a vendor."
    docs = db.query(Document).filter(Document.vendor_normalized == vendor_norm).all()
    if not docs:
        return [], f"No documents found for vendor '{params.get('vendor')}'."
    doc_ids = [d.id for d in docs]
    anomaly_count = db.query(func.count(Anomaly.id)).filter(Anomaly.document_id.in_(doc_ids)).scalar()
    amounts = [float(d.total_amount) for d in docs if d.total_amount is not None]
    data = [{
        "vendor": docs[0].vendor_name,
        "documents": len(docs),
        "total_spend": sum(amounts),
        "average_amount": sum(amounts) / len(amounts) if amounts else None,
        "anomalies": anomaly_count,
    }]
    r = data[0]
    return data, (
        f"{r['vendor']}: {r['documents']} documents, total spend {_fmt(r['total_spend'])}, "
        f"average {_fmt(r['average_amount'])}, {r['anomalies']} anomalies flagged."
    )


def anomaly_counts_by_rule(db: Session, params: dict):
    rows = (
        db.query(Anomaly.rule_code, Anomaly.severity, func.count(Anomaly.id))
        .group_by(Anomaly.rule_code, Anomaly.severity)
        .all()
    )
    data = [{"rule_code": r, "severity": s, "count": c} for r, s, c in rows]
    if not data:
        return data, "No anomalies have been flagged yet."
    total = sum(r["count"] for r in data)
    by_rule: dict[str, int] = {}
    for r in data:
        by_rule[r["rule_code"]] = by_rule.get(r["rule_code"], 0) + r["count"]
    return data, (
        f"{total} anomalies flagged in total: "
        + ", ".join(f"{rule} ({n})" for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]))
        + "."
    )


TOOLS: dict[str, dict] = {
    "top_vendors_by_anomalies": {
        "fn": top_vendors_by_anomalies,
        "description": "Rank vendors by number of flagged anomalies.",
        "params": "start_date?: YYYY-MM-DD, end_date?: YYYY-MM-DD, limit?: int",
    },
    "anomalies_above_amount": {
        "fn": anomalies_above_amount,
        "description": "List anomalies on documents above a minimum amount, optionally by severity/date range.",
        "params": "min_amount?: number, severity?: low|medium|high, start_date?, end_date?",
    },
    "spend_by_category": {
        "fn": spend_by_category,
        "description": "Total spend grouped by expense category.",
        "params": "start_date?, end_date?",
    },
    "spend_over_time": {
        "fn": spend_over_time,
        "description": "Monthly spend, document counts and flagged counts (trend).",
        "params": "start_date?, end_date?",
    },
    "vendor_summary": {
        "fn": vendor_summary,
        "description": "Documents, total/average spend and anomaly count for one named vendor.",
        "params": "vendor: string (required)",
    },
    "anomaly_counts_by_rule": {
        "fn": anomaly_counts_by_rule,
        "description": "Overview: anomaly counts grouped by rule and severity.",
        "params": "(none)",
    },
}


def tool_catalog() -> str:
    return "\n".join(
        f"- {name}: {t['description']} Params: {t['params']}" for name, t in TOOLS.items()
    )


# ------------------------------------------------------------- routing

EXPLAIN_RE = re.compile(r"\b(why|explain|reason|what happened|tell me about)\b", re.I)
AMOUNT_RE = re.compile(r"(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\b", re.I)

# \bmonth\b deliberately does not match "monthly" — that's granularity, not a range
TIME_HINT_RE = re.compile(
    r"\b(this|last|past|current|since|until|before|after|between|from|today|yesterday|"
    r"month|months|week|weeks|year|years|quarter|20\d{2}|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|"
    r"aug(ust)?|sep(tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\b",
    re.I,
)


def sanitize_params(question: str, params: dict) -> dict:
    """Small local models sometimes copy parameters from the router prompt's
    examples. Any param the question itself doesn't support gets dropped —
    the same trust-nothing principle as not letting the LLM write SQL."""
    if not TIME_HINT_RE.search(question):
        params.pop("start_date", None)
        params.pop("end_date", None)
    if "min_amount" in params and not re.search(r"\d", question):
        params.pop("min_amount")
    return params


def _extract_amount(question: str) -> Optional[float]:
    best = None
    for m in AMOUNT_RE.finditer(question):
        value = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        if unit == "k":
            value *= 1_000
        elif unit in ("lakh", "lac"):
            value *= 100_000
        if best is None or value > best:
            best = value
    return best


def _time_params(question: str) -> dict:
    today = date.today()
    q = question.lower()
    if "this month" in q:
        return {"start_date": today.replace(day=1).isoformat()}
    if "last month" in q:
        first_this = today.replace(day=1)
        last_prev = first_this.replace(day=1) if first_this.month == 1 else first_this
        prev_month_end = first_this.fromordinal(first_this.toordinal() - 1)
        return {
            "start_date": prev_month_end.replace(day=1).isoformat(),
            "end_date": prev_month_end.isoformat(),
        }
    if "this year" in q:
        return {"start_date": today.replace(month=1, day=1).isoformat()}
    return {}


def keyword_route(db: Session, question: str) -> tuple[str, dict]:
    """Deterministic fallback router — no LLM required."""
    q = question.lower()
    params = _time_params(question)

    known_vendors = [v for (v,) in db.query(Document.vendor_name).distinct().all() if v]
    named = next((v for v in known_vendors if v.lower() in q), None)

    if re.search(r"most (flagged|anomal)|which vendor|top vendor", q):
        return "top_vendors_by_anomalies", params
    if re.search(r"(above|over|more than|greater)", q) and _extract_amount(question):
        return "anomalies_above_amount", {**params, "min_amount": _extract_amount(question)}
    if "categor" in q and re.search(r"spend|total|much|cost", q):
        return "spend_by_category", params
    if re.search(r"trend|over time|monthly|per month", q):
        return "spend_over_time", params
    if named:
        return "vendor_summary", {"vendor": named}
    if re.search(r"anomal|flag|issue|problem", q):
        return "anomaly_counts_by_rule", {}
    return "anomaly_counts_by_rule", {}


def llm_route(question: str) -> Optional[tuple[str, dict]]:
    client = get_llm_client()
    if not client.available():
        return None
    today = date.today()
    prompt = ROUTER_PROMPT.format(
        tool_catalog=tool_catalog(),
        question=question,
        today=today.isoformat(),
        month_start=today.replace(day=1).isoformat(),
    )
    data = client.complete_json(prompt, system=ROUTER_SYSTEM)
    if not data or data.get("tool") not in TOOLS:
        logger.info("LLM router produced unusable output, using keyword fallback: %r", data)
        return None
    params = data.get("params")
    if not isinstance(params, dict):
        params = {}
    return data["tool"], sanitize_params(question, params)


# ------------------------------------------------------------- RAG path

def rag_answer(db: Session, question: str) -> dict:
    chunks = rag_store.search(db, question, k=6)
    if not chunks:
        return {"answer": "No indexed audit records match that question yet.", "tool_used": "rag", "rows": []}
    context = "\n".join(f"- {c.text}" for c in chunks)
    client = get_llm_client()
    if client.available():
        try:
            answer = client.complete(
                RAG_ANSWER_PROMPT.format(context=context, question=question),
                system=RAG_ANSWER_SYSTEM,
            ).strip()
        except Exception:
            answer = "Most relevant audit records:\n" + context
    else:
        answer = "Most relevant audit records:\n" + context
    rows = [{"source": c.source_type, "source_id": c.source_id, "text": c.text} for c in chunks]
    return {"answer": answer, "tool_used": "rag", "rows": rows}


class QueryAgent:
    def answer(self, db: Session, question: str) -> dict:
        question = question.strip()
        if not question:
            return {"answer": "Ask me something about the audited documents.", "tool_used": "none", "rows": []}

        if EXPLAIN_RE.search(question):
            return rag_answer(db, question)

        routed = llm_route(question)
        route_source = "llm_router"
        if routed is None:
            routed = keyword_route(db, question)
            route_source = "keyword_router"
        tool_name, params = routed

        try:
            rows, answer = TOOLS[tool_name]["fn"](db, params)
        except Exception:
            logger.exception("Tool %s failed with params %r; retrying with defaults", tool_name, params)
            rows, answer = TOOLS[tool_name]["fn"](db, {})
        return {"answer": answer, "tool_used": f"{tool_name} (via {route_source})", "rows": rows}


query_agent = QueryAgent()
