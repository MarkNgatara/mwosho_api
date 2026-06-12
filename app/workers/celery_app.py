from celery import Celery
from app.config import settings

celery_app = Celery(
    "1ndependence",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,   # one task per worker slot — avoids starvation on large jobs
    task_acks_late=True,            # only ack after task completes, so crashes re-queue
    task_reject_on_worker_lost=True,
    result_expires=86400,           # keep results 24 h
    task_routes={
        "app.workers.tasks.process_file_task":  {"queue": "file_processing"},
        "app.workers.tasks.process_chunk_task": {"queue": "chunk_processing"},
    },
)
