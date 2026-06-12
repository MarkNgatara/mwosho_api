import logging
from datetime import datetime

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.services.cleaning_service import CleaningService
from app.services.file_service import FileService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


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

        # 2. Process each chunk sequentially (workers handle true parallelism via concurrency)
        _update_job(
            db, job,
            status=JobStatus.PROCESSING,
            total_chunks=len(chunk_paths),
            total_rows=total_rows,
            progress=10.0,
        )

        for i, chunk_path in enumerate(chunk_paths):
            process_chunk_task(job_id, chunk_path, i, len(chunk_paths))

        # 3. Merge cleaned chunks
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
