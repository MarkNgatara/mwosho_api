import json
import os
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
from app.workers.tasks import run_agent_pipeline

router = APIRouter(prefix="/upload", tags=["upload"])

TIER_LIMITS = {
    SubscriptionTier.FREE:       {"max_file_mb": 10,   "jobs_per_month": 5},
    SubscriptionTier.PRO:        {"max_file_mb": 500,  "jobs_per_month": 100},
    SubscriptionTier.ENTERPRISE: {"max_file_mb": 2048, "jobs_per_month": 999_999},
}

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".tsv"}

_scanner = ScanService()


@router.post("/", response_model=JobResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    # Frontend sends cleaning_options as a JSON string in FormData
    cleaning_options: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Parse cleaning options from JSON string
    opts: dict = {}
    if cleaning_options:
        try:
            raw = json.loads(cleaning_options)
            opts = CleaningOptions(**raw).model_dump()
        except Exception:
            opts = CleaningOptions().model_dump()  # fall back to defaults

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not supported. Use: csv, tsv, xlsx, xls",
        )

    limits = TIER_LIMITS[current_user.subscription_tier]
    if current_user.jobs_used_this_month >= limits["jobs_per_month"]:
        raise HTTPException(
            status_code=429,
            detail="Monthly job limit reached. Upgrade your plan.",
        )

    job_id = generate_job_id()
    upload_path = Path(settings.UPLOAD_DIR) / f"{job_id}{ext}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream file to disk (enforce size limit mid-upload)
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
                    detail=f"File exceeds {limits['max_file_mb']} MB limit for your plan",
                )
            await out.write(chunk)

    # Virus / malware scan
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

    run_agent_pipeline.delay(job_id)
    return job
