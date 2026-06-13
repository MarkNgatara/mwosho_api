import logging
from datetime import datetime

import pandas as pd

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.services.ai_service import AIService
from app.services.cleaning_service import CleaningService
from app.services.file_service import FileService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_AGENT_SAMPLE_ROWS = 1_000


# ── NEW: Full 9-agent pipeline ────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.workers.tasks.run_agent_pipeline", queue="file_processing")
def run_agent_pipeline(self, job_id: str):
    """Runs the full Mwosho agent pipeline (Agents 0-8) for a job."""
    try:
        from app.agents.orchestrator import Orchestrator
        Orchestrator().run_pipeline(job_id)
    except Exception as exc:
        logger.exception(f"Agent pipeline failed for job {job_id}: {exc}")
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.job_id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(exc)[:500]
                db.commit()
        finally:
            db.close()


def _get_job(db, job_id: str) -> Job:
    return db.query(Job).filter(Job.job_id == job_id).first()


def _update_job(db, job: Job, **kwargs):
    for key, val in kwargs.items():
        setattr(job, key, val)
    db.commit()


@celery_app.task(bind=True, name="app.workers.tasks.process_file_task", queue="file_processing")
def process_file_task(self, job_id: str):
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            return

        # 1. Split file into chunks
        _update_job(db, job, status=JobStatus.CHUNKING, progress=5.0)
        chunk_paths, total_rows = FileService.split_into_chunks(
            job.file_path, job_id, job.cleaning_options or {}
        )

        # 2. Run AI agent on a sample from the first chunk
        #    Agent profiles, detects issues, cleans the sample, and writes its report
        #    to ai_insights — all before the workers start so the report is available early.
        try:
            sample_df = pd.read_csv(chunk_paths[0], nrows=_AGENT_SAMPLE_ROWS)
            _, ai_report = AIService().run_agent(sample_df)
            _update_job(db, job, ai_insights=ai_report, progress=8.0)
            logger.info(f"Job {job_id}: agent score={ai_report.get('quality_score')}")
        except Exception as exc:
            logger.warning(f"Job {job_id}: AI agent skipped — {exc}")

        # 3. Process each chunk (CleaningService — same options as before)
        _update_job(
            db, job,
            status=JobStatus.PROCESSING,
            total_chunks=len(chunk_paths),
            total_rows=total_rows,
            progress=10.0,
        )
        for i, chunk_path in enumerate(chunk_paths):
            process_chunk_task(job_id, chunk_path, i, len(chunk_paths))

        # 4. Merge cleaned chunks
        _update_job(db, job, status=JobStatus.MERGING, progress=90.0)
        result_path, stats = FileService.merge_chunks(job_id, job.original_filename)

        _update_job(
            db, job,
            status=JobStatus.COMPLETED,
            progress=100.0,
            result_file_path=result_path,
            cleaned_rows=stats["cleaned_rows"],
            duplicates_removed=stats["duplicates_removed"],
            missing_filled=stats["missing_filled"],
            completed_at=datetime.utcnow(),
        )

    except Exception as exc:
        logger.exception(f"Job {job_id} failed: {exc}")
        db.refresh(job)
        _update_job(db, job, status=JobStatus.FAILED, error_message=str(exc))
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_chunk_task", queue="chunk_processing")
def process_chunk_task(job_id: str, chunk_path: str, chunk_index: int, total_chunks: int):
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            return {}

        cleaner = CleaningService(job.cleaning_options or {})
        stats = cleaner.clean_chunk(chunk_path)

        completed = job.completed_chunks + 1
        progress = 10.0 + (completed / total_chunks) * 75.0
        _update_job(db, job, completed_chunks=completed, progress=round(progress, 1))

        return stats
    finally:
        db.close()
