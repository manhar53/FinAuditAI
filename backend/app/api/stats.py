from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.query_agent import spend_over_time
from app.db.database import get_db
from app.db.models import Anomaly, Document

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total_documents = db.query(func.count(Document.id)).scalar() or 0
    total_anomalies = db.query(func.count(Anomaly.id)).scalar() or 0
    flagged_documents = db.query(func.count(func.distinct(Anomaly.document_id))).scalar() or 0
    total_spend = float(db.query(func.coalesce(func.sum(Document.total_amount), 0)).scalar())

    by_severity = dict(
        db.query(Anomaly.severity, func.count(Anomaly.id)).group_by(Anomaly.severity).all()
    )
    by_rule = dict(
        db.query(Anomaly.rule_code, func.count(Anomaly.id)).group_by(Anomaly.rule_code).all()
    )
    return {
        "total_documents": total_documents,
        "flagged_documents": flagged_documents,
        "total_anomalies": total_anomalies,
        "total_spend": total_spend,
        "anomalies_by_severity": by_severity,
        "anomalies_by_rule": by_rule,
    }


@router.get("/trends")
def trends(db: Session = Depends(get_db)):
    rows, _ = spend_over_time(db, {})
    return {"monthly": rows}


@router.get("/breakdown")
def breakdown(by: str = "vendor", db: Session = Depends(get_db)):
    column = Document.vendor_name if by == "vendor" else Document.category
    rows = (
        db.query(
            column.label("key"),
            func.count(Document.id).label("documents"),
            func.coalesce(func.sum(Document.total_amount), 0).label("total_spend"),
            func.count(func.distinct(Anomaly.id)).label("anomalies"),
        )
        .outerjoin(Anomaly, Anomaly.document_id == Document.id)
        .filter(column.isnot(None))
        .group_by(column)
        .order_by(func.sum(Document.total_amount).desc())
        .all()
    )
    return {
        "by": by,
        "rows": [
            {"key": k, "documents": d, "total_spend": float(t), "anomalies": a}
            for k, d, t, a in rows
        ],
    }
