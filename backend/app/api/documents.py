from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.orchestrator import orchestrator
from app.db.database import get_db
from app.db.models import Document
from app.schemas import DocumentDetail, DocumentOut, UploadResult

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResult)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Run the full pipeline on one uploaded PDF or CSV."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        result = orchestrator.process_upload(db, file.filename or "upload", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("", response_model=list[DocumentOut])
def list_documents(
    vendor: str | None = None,
    category: str | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(Document)
    if vendor:
        q = q.filter(Document.vendor_name.ilike(f"%{vendor}%"))
    if category:
        q = q.filter(Document.category == category)
    if status:
        q = q.filter(Document.status == status)
    return q.order_by(Document.id.desc()).limit(min(limit, 1000)).all()


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
