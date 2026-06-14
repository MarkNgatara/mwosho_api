import json
import os
import threading
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.user import SubscriptionTier, User
from app.schemas.job import CleaningOptions, JobResponse
from app.services.scan_service import ScanService
from app.utils.helpers import generate_job_id, get_current_user

router = APIRouter(prefix="/upload", tags=["upload"])

TIER_LIMITS = {
    SubscriptionTier.FREE:       {"max_file_mb": 18,    "jobs_per_month": 5},
    SubscriptionTier.PRO:        {"max_file_mb": 500,   "jobs_per_month": 100},
    SubscriptionTier.SCALE:      {"max_file_mb": 5120,  "jobs_per_month": 500},   # 5 GB
    SubscriptionTier.ENTERPRISE: {"max_file_mb": 20480, "jobs_per_month": 999_999},  # 20 GB
}

# SCALE/ENTERPRISE unlock additional file types
ALLOWED_EXTENSIONS_BASE  = {".csv", ".xlsx", ".xls", ".tsv"}
ALLOWED_EXTENSIONS_SCALE = {".csv", ".xlsx", ".xls", ".tsv", ".json", ".parquet", ".jsonl", ".gz"}

_scanner = ScanService()


def _get_allowed_extensions(tier: SubscriptionTier) -> set[str]:
    if tier in (SubscriptionTier.SCALE, SubscriptionTier.ENTERPRISE):
        return ALLOWED_EXTENSIONS_SCALE
    return ALLOWED_EXTENSIONS_BASE


def _dispatch_pipeline(job_id: str) -> None:
    """Dispatch to Celery if available, else run in background thread (no Redis needed)."""
    try:
        from app.workers.tasks import run_agent_pipeline
        run_agent_pipeline.delay(job_id)
    except Exception:
        # Redis / Celery offline — run synchronously in a daemon thread
        def _run():
            try:
                from app.agents.orchestrator import Orchestrator
                Orchestrator().run_pipeline(job_id)
            except Exception as exc:
                print(f"[pipeline] background run failed for {job_id}: {exc}")

        threading.Thread(target=_run, daemon=True, name=f"pipeline-{job_id}").start()


@router.post("/", response_model=JobResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    cleaning_options: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    opts: dict = {}
    if cleaning_options:
        try:
            raw = json.loads(cleaning_options)
            opts = CleaningOptions(**raw).model_dump()
        except Exception:
            opts = CleaningOptions().model_dump()

    ext = Path(file.filename).suffix.lower()
    allowed = _get_allowed_extensions(current_user.subscription_tier)
    if ext not in allowed:
        base_types = "csv, tsv, xlsx, xls"
        extra = " — upgrade to SCALE for json, parquet, jsonl, gz" if ext in ALLOWED_EXTENSIONS_SCALE else ""
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not supported on your plan. Supported: {base_types}{extra}",
        )

    limits = TIER_LIMITS[current_user.subscription_tier]
    if current_user.jobs_used_this_month >= limits["jobs_per_month"]:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly job limit ({limits['jobs_per_month']}) reached. Upgrade your plan.",
        )

    job_id = generate_job_id()
    upload_path = Path(settings.UPLOAD_DIR) / f"{job_id}{ext}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    file_size = 0
    max_bytes = limits["max_file_mb"] * 1024 * 1024
    async with aiofiles.open(upload_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > max_bytes:
                await out.close()
                os.remove(upload_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds {limits['max_file_mb']} MB limit for your plan.",
                )
            await out.write(chunk)

    scan = _scanner.scan_file(str(upload_path))
    if not scan.clean:
        os.remove(upload_path)
        raise HTTPException(
            status_code=422,
            detail=f"File rejected by security scan: {scan.reason}",
        )

    job = Job(
        job_id=job_id,
        user_id=current_user.id,
        original_filename=file.filename,
        file_path=str(upload_path),
        file_size_bytes=file_size,
        cleaning_options=opts,
    )
    db.add(job)
    current_user.jobs_used_this_month += 1
    db.commit()
    db.refresh(job)

    # Dispatch pipeline — works with or without Redis
    _dispatch_pipeline(job_id)
    return job
