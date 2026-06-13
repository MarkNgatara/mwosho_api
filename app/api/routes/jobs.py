import os
import shutil
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobResponse
from app.utils.helpers import get_current_user
from app.config import settings

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _wipe_files(job_id: str, file_path: str | None, result_path: str | None) -> None:
    for p in [file_path, result_path]:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    chunks_dir = os.path.join(settings.CHUNKS_DIR, job_id)
    try:
        shutil.rmtree(chunks_dir, ignore_errors=True)
    except Exception:
        pass


def _mark_deleted(db: Session, job: Job) -> None:
    job.files_deleted  = True
    job.file_path      = None
    job.result_file_path = None
    job.download_token = None
    db.commit()


@router.get("/", response_model=List[JobResponse])
def list_jobs(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Job)
        .filter(Job.user_id == current_user.id)
        .order_by(Job.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Authenticated download (dashboard button) ─────────────────────────────────
@router.get("/{job_id}/download")
def download_result(
    job_id: str,
    bg: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.files_deleted:
        raise HTTPException(status_code=410, detail="File has been permanently deleted.")
    if not job.result_file_path or not os.path.exists(job.result_file_path):
        raise HTTPException(status_code=404, detail="Result file not ready yet")

    file_path   = job.file_path
    result_path = job.result_file_path
    bg.add_task(_wipe_files, job.job_id, file_path, result_path)
    _mark_deleted(db, job)

    return FileResponse(
        path=result_path,
        filename=f"cleaned_{job.original_filename}",
        media_type="application/octet-stream",
    )


# ── Public token download (email link) ────────────────────────────────────────
@router.get("/download/{token}")
def download_by_token(
    token: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.download_token == token).first()
    if not job:
        raise HTTPException(status_code=404, detail="Invalid or expired download link.")

    if job.files_deleted:
        raise HTTPException(
            status_code=410,
            detail="This file has already been downloaded and permanently deleted.",
        )

    now = datetime.now(timezone.utc)
    expires = job.expires_at
    if expires and expires.tzinfo is None:
        from datetime import timezone as tz
        expires = expires.replace(tzinfo=tz.utc)
    if expires and expires < now:
        bg.add_task(_wipe_files, job.job_id, job.file_path, job.result_file_path)
        _mark_deleted(db, job)
        raise HTTPException(
            status_code=410,
            detail="Download link has expired. Files are permanently deleted after 1 hour.",
        )

    if not job.result_file_path or not os.path.exists(job.result_file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    file_path   = job.file_path
    result_path = job.result_file_path
    bg.add_task(_wipe_files, job.job_id, file_path, result_path)
    _mark_deleted(db, job)

    return FileResponse(
        path=result_path,
        filename=f"cleaned_{job.original_filename}",
        media_type="application/octet-stream",
    )


# ── Delete job (user-initiated) ───────────────────────────────────────────────
@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    bg: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    bg.add_task(_wipe_files, job.job_id, job.file_path, job.result_file_path)
    db.delete(job)
    db.commit()
