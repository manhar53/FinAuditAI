from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.extraction import parse_date
from app.db.database import get_db
from app.db.models import Anomaly, Document
from app.schemas import AnomalyOut, AnomalyStatusUpdate

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=list[AnomalyOut])
def list_anomalies(
    severity: str | None = None,
    rule_code: str | None = None,
    vendor: str | None = None,
    min_amount: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(Anomaly).join(Document, Anomaly.document_id == Document.id)
    if severity:
        q = q.filter(Anomaly.severity == severity.lower())
    if status:
        q = q.filter(Anomaly.status == status.lower())
    if rule_code:
        q = q.filter(Anomaly.rule_code == rule_code.upper())
    if vendor:
        q = q.filter(Document.vendor_name.ilike(f"%{vendor}%"))
    if min_amount is not None:
        q = q.filter(Document.total_amount >= min_amount)
    if start := parse_date(start_date):
        q = q.filter(Document.invoice_date >= start)
    if end := parse_date(end_date):
        q = q.filter(Document.invoice_date <= end)
    return q.order_by(Anomaly.id.desc()).limit(min(limit, 1000)).all()


@router.patch("/{anomaly_id}", response_model=AnomalyOut)
def update_anomaly_status(anomaly_id: int, update: AnomalyStatusUpdate, db: Session = Depends(get_db)):
    """Reviewer triage: open -> reviewed (confirmed issue) or dismissed (false alarm)."""
    anomaly = db.get(Anomaly, anomaly_id)
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    anomaly.status = update.status
    db.commit()
    db.refresh(anomaly)
    return anomaly
