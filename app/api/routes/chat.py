"""
AI chat endpoint — lets users ask questions about their data / cleaning jobs.
Rate limits per subscription tier (per user, per hour).
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

# ── In-memory rate limit store ─────────────────────────────────────────────
# { user_id: [timestamp, timestamp, ...] }
_rate_store: dict[int, list[datetime]] = {}

TIER_HOURLY_LIMITS = {
    SubscriptionTier.FREE:       20,
    SubscriptionTier.PRO:        100,
    SubscriptionTier.ENTERPRISE: 500,
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
    job_id: Optional[str] = None   # optional job context


class ChatResponse(BaseModel):
    reply: str
    requests_used: int
    requests_limit: int


def _check_rate_limit(user: User) -> tuple[int, int]:
    """Returns (used_this_hour, limit). Raises 429 if over limit."""
    limit = TIER_HOURLY_LIMITS.get(user.subscription_tier, 20)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=1)

    history = _rate_store.get(user.id, [])
    # Prune old timestamps outside the rolling window
    history = [t for t in history if t > window_start]
    _rate_store[user.id] = history

    if len(history) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached: {limit} messages per hour on your plan. Upgrade for more.",
        )
    return len(history), limit


def _record_request(user_id: int) -> None:
    _rate_store.setdefault(user_id, []).append(datetime.now(timezone.utc))


def _build_job_context(job: Job) -> str:
    opts = job.cleaning_options or {}
    lines = [
        f"File: {job.original_filename}",
        f"Status: {job.status}",
        f"Total rows: {job.total_rows}",
        f"Cleaned rows: {job.cleaned_rows}",
        f"Duplicates removed: {job.duplicates_removed}",
        f"Missing values filled: {job.missing_filled}",
        f"Cleaning options: {opts}",
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

    used, limit = _check_rate_limit(current_user)

    if not settings.ANTHROPIC_API_KEY:
        # Dev mode — echo a helpful placeholder
        _record_request(current_user.id)
        return ChatResponse(
            reply=(
                "Mwosho AI is not configured yet — add ANTHROPIC_API_KEY to your .env file. "
                "Once configured, I can answer questions about your data cleaning jobs, "
                "suggest best practices, and help you understand your results."
            ),
            requests_used=used + 1,
            requests_limit=limit,
        )

    # Build context message
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

    _record_request(current_user.id)
    return ChatResponse(
        reply=reply,
        requests_used=used + 1,
        requests_limit=limit,
    )


@router.get("/limit")
def get_limit(current_user: User = Depends(get_current_user)):
    """Return current rate limit status without sending a message."""
    limit = TIER_HOURLY_LIMITS.get(current_user.subscription_tier, 20)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=1)
    history = _rate_store.get(current_user.id, [])
    history = [t for t in history if t > window_start]
    _rate_store[current_user.id] = history
    return {"requests_used": len(history), "requests_limit": limit}
