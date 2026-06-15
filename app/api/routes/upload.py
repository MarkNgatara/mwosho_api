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
from app.models.user import User
from app.plans import allowed_extensions, plan_for
from app.schemas.job import CleaningOptions, JobResponse
from app.services.scan_service import ScanService
from app.utils.helpers import generate_job_id, get_current_user

router = APIRouter(prefix="/upload", tags=["upload"])

_scanner = ScanService()


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
    allowed = allowed_extensions(current_user.subscription_tier)
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{ext}' is not available on your plan. "
                f"Allowed: {', '.join(sorted(allowed))}. Upgrade to unlock more formats."
            ),
        )

    plan = plan_for(current_user.subscription_tier)
    if current_user.jobs_used_this_month >= plan.jobs_per_month:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly job limit ({plan.jobs_per_month}) reached on the {plan.name} plan. Upgrade for more.",
        )

    job_id = generate_job_id()
    upload_path = Path(settings.UPLOAD_DIR) / f"{job_id}{ext}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    file_size = 0
    max_bytes = plan.max_file_mb * 1024 * 1024
    async with aiofiles.open(upload_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > max_bytes:
                await out.close()
                os.remove(upload_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {plan.max_file_mb} MB limit on the {plan.name} plan.",
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
