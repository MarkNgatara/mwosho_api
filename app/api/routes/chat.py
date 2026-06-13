"""
AI chat endpoint — lets users ask questions about their data / cleaning jobs.
Rate limits stored in DB (survive server restarts):
  FREE → 5/hour  |  PRO → 80/hour  |  ENTERPRISE → 200/hour
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.user import SubscriptionTier, User
from app.utils.helpers import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])

TIER_HOURLY_LIMITS = {
    SubscriptionTier.FREE:       5,
    SubscriptionTier.PRO:        80,
    SubscriptionTier.SCALE:      150,
    SubscriptionTier.ENTERPRISE: 200,
}

SYSTEM_PROMPT = """You are Mwosho AI, a friendly data cleaning assistant built into the Mwosho Data Cleaning App.
You help data analysts:
- Understand cleaning operations applied to their files
- Interpret cleaning results (duplicates removed, missing values filled, formatting fixes)
- Give advice on data quality best practices
- Answer questions about CSV/Excel data structures
- Suggest data cleaning strategies

Be concise, practical, and helpful. If a job context is provided, refer to it.
Never make up statistics — only reference data the user provides.
If asked about something outside data cleaning, politely redirect to data topics."""


class ChatRequest(BaseModel):
    message: str
    job_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    requests_used: int
    requests_limit: int


def _get_limit(user: User) -> int:
    return TIER_HOURLY_LIMITS.get(user.subscription_tier, 5)


def _check_and_record(user: User, db: Session) -> tuple[int, int]:
    """
    Check rate limit using DB columns. Resets the window if >1 hour has passed.
    Returns (used_after_this_request, limit).
    Raises 429 if over limit.
    """
    limit = _get_limit(user)
    now = datetime.now(timezone.utc)

    window_start = user.chat_window_start
    if window_start and window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)

    # Reset window if it's been more than 1 hour or no window yet
    if not window_start or (now - window_start) > timedelta(hours=1):
        user.chat_used_this_hour = 0
        user.chat_window_start = now
        db.commit()

    if user.chat_used_this_hour >= limit:
        minutes_left = 60 - int((now - window_start).total_seconds() / 60)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached: {limit} messages/hour on your plan. Resets in ~{minutes_left} min. Upgrade for more.",
        )

    user.chat_used_this_hour += 1
    db.commit()
    return user.chat_used_this_hour, limit


def _build_job_context(job: Job) -> str:
    opts = job.cleaning_options or {}
    lines = [
        f"File: {job.original_filename}",
        f"Status: {job.status}",
        f"Total rows: {job.total_rows}",
        f"Cleaned rows: {job.cleaned_rows}",
        f"Duplicates removed: {job.duplicates_removed}",
        f"Missing values filled: {job.missing_filled}",
        f"Cleaning options applied: {opts}",
    ]
    if job.ai_insights:
        lines.append(f"AI insights: {job.ai_insights}")
    if job.error_message:
        lines.append(f"Error: {job.error_message}")
    return "\n".join(lines)


@router.post("/", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(payload.message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 characters)")

    # Check + record BEFORE calling Claude (so failed calls still count)
    used, limit = _check_and_record(current_user, db)

    if not settings.ANTHROPIC_API_KEY:
        return ChatResponse(
            reply=(
                "Mwosho AI is not configured yet — add ANTHROPIC_API_KEY to your .env file. "
                "Once configured, I can answer questions about your data cleaning jobs."
            ),
            requests_used=used,
            requests_limit=limit,
        )

    # Build context
    context_block = ""
    if payload.job_id:
        job = db.query(Job).filter(
            Job.job_id == payload.job_id,
            Job.user_id == current_user.id,
        ).first()
        if job:
            context_block = f"\n\n[Job context]\n{_build_job_context(job)}"

    user_message = payload.message.strip()
    if context_block:
        user_message = f"{user_message}{context_block}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        reply = response.content[0].text
    except Exception as exc:
        print(f"[chat] Anthropic API error: {exc}")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable. Try again shortly.")

    return ChatResponse(reply=reply, requests_used=used, requests_limit=limit)


@router.get("/limit")
def get_limit_status(current_user: User = Depends(get_current_user)):
    """Return current rate limit status without consuming a request."""
    limit = _get_limit(current_user)
    now = datetime.now(timezone.utc)

    window_start = current_user.chat_window_start
    if window_start and window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)

    if not window_start or (now - window_start) > timedelta(hours=1):
        used = 0
    else:
        used = current_user.chat_used_this_hour or 0

    return {"requests_used": used, "requests_limit": limit}
