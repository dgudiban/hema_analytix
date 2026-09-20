"""Chat endpoints: hybrid grounded chat and the LLM-only baseline.

The hybrid endpoint requires login and only uses the patient's own reports.
The baseline deliberately has no DB access and stays open (research comparison).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.models.db import get_db
from app.models.entities import User
from app.schemas.dto import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    history = [m.model_dump() for m in body.history] if body.history else None
    return chat_service.answer_question(
        body.message, db, report_id=body.report_id, history=history, user_id=user.id
    )


@router.post("/baseline", response_model=ChatResponse)
def chat_baseline(body: ChatRequest):
    # Deliberately no DB access: the baseline gets no patient data or RAG.
    return chat_service.answer_baseline(body.message)
