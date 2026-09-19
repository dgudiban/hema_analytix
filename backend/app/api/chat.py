"""Chat endpoints: hybrid grounded chat and the LLM-only baseline."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.schemas.dto import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    history = [m.model_dump() for m in body.history] if body.history else None
    return chat_service.answer_question(
        body.message, db, report_id=body.report_id, history=history
    )


@router.post("/baseline", response_model=ChatResponse)
def chat_baseline(body: ChatRequest):
    # Deliberately no DB access: the baseline gets no patient data or RAG.
    return chat_service.answer_baseline(body.message)
