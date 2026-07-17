from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.query_agent import query_agent
from app.db.database import get_db
from app.schemas import QueryRequest, QueryResponse

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
def ask(request: QueryRequest, db: Session = Depends(get_db)):
    """Natural-language question -> Query Agent (semantic-layer tools + RAG)."""
    return query_agent.answer(db, request.question)
