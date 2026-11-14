from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import CustomerUser, DbSession
from app.services import ai_service as svc

router = APIRouter(prefix="/ai", tags=["ai"])

ERRORS = {
    429: {"description": "Too many requests (Retry-After header)"},
    502: {"description": "AI provider failed"},
    503: {"description": "AI not configured / temporarily unavailable"},
    504: {"description": "AI provider timed out"},
}


class InsightQuestion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str | None = Field(default=None, min_length=3, max_length=500)


class InsightAnswer(BaseModel):
    answer: str
    source: Literal["openai", "no_orders"]  # no_orders: factual reply, OpenAI not called
    model: str | None
    orders_considered: int
    generated_at: datetime


@router.post("/insights", response_model=InsightAnswer, responses=ERRORS)
def ask_insights(db: DbSession, customer: CustomerUser, data: InsightQuestion | None = None):
    """Insights about YOUR orders, optionally answering `question`. Uses only your own order
    history (taken from your token, never from the request)."""
    return svc.ask(db, customer, data.question if data else None)


@router.get("/summary", response_model=InsightAnswer, responses=ERRORS)
def order_summary(db: DbSession, customer: CustomerUser):
    """AI summary of your previous orders."""
    return svc.summary(db, customer)
