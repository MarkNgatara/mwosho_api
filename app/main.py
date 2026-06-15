import os
import shutil
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import audit_log, agent_run  # ensure tables are registered
from app.api.routes import auth, upload, jobs, payments, chat, agents as agents_router

Base.metadata.create_all(bind=engine)

# Add any columns that were introduced after the initial table creation
def _migrate():
    new_cols = [
        ("billing_cycle",           "VARCHAR(20) DEFAULT 'monthly'"),
        ("period_end",              "DATETIME NULL"),
        ("stripe_customer_id",      "VARCHAR(100) NULL"),
        ("stripe_subscription_id",  "VARCHAR(100) NULL"),
        ("totp_secret",             "VARCHAR(64) NULL"),
        ("is_2fa_enabled",          "BOOLEAN DEFAULT FALSE"),
        ("is_email_verified",       "BOOLEAN DEFAULT FALSE"),
        ("email_otp_hash",          "VARCHAR(64) NULL"),
        ("otp_expires_at",          "DATETIME NULL"),
        ("chat_used_this_hour",     "INT DEFAULT 0"),
        ("chat_window_start",       "DATETIME NULL"),
    ]
    # Jobs table new agent columns
    new_job_cols = [
        ("expires_at",     "DATETIME NULL"),
        ("download_token", "VARCHAR(64) NULL"),
        ("files_deleted",  "BOOLEAN DEFAULT FALSE"),
        ("orchestrator_state",   "VARCHAR(50) DEFAULT 'created'"),
        ("dataset_type",         "VARCHAR(50) NULL"),
        ("issues_found",         "INT DEFAULT 0"),
        ("quality_score_before", "FLOAT NULL"),
        ("quality_score_after",  "FLOAT NULL"),
        ("governance_flags",     "JSON NULL"),
        ("cleaning_plan",        "JSON NULL"),
        ("analytics_insights",   "JSON NULL"),
        ("report_data",          "JSON NULL"),
        ("agent_outputs",        "JSON NULL"),
    ]
    try:
        with engine.connect() as conn:
            # users table
            rows = conn.execute(text("SHOW COLUMNS FROM users")).fetchall()
            existing = {r[0] for r in rows}
            for col, defn in new_cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {defn}"))
            # jobs table
            rows = conn.execute(text("SHOW COLUMNS FROM jobs")).fetchall()
            existing = {r[0] for r in rows}
            for col, defn in new_job_cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} {defn}"))
            # Migrate subscription_tier ENUM to the 6-tier model.
            try:
                # 1. widen to a superset so legacy + new values both fit
                conn.execute(text(
                    "ALTER TABLE users MODIFY COLUMN subscription_tier "
                    "ENUM('free','pro','scale','starter','professional',"
                    "'business','growth','enterprise') DEFAULT 'free'"
                ))
                # 2. remap legacy tiers (pre-revenue: test accounts only)
                conn.execute(text("UPDATE users SET subscription_tier='professional' WHERE subscription_tier='pro'"))
                conn.execute(text("UPDATE users SET subscription_tier='business' WHERE subscription_tier='scale'"))
                # 3. narrow to the final 6-tier enum
                conn.execute(text(
                    "ALTER TABLE users MODIFY COLUMN subscription_tier "
                    "ENUM('free','starter','professional','business','growth','enterprise') DEFAULT 'free'"
                ))
            except Exception:
                pass  # already migrated or column doesn't exist yet
            conn.commit()
    except Exception as exc:
        print(f"[migration] skipped: {exc}")

_migrate()


def _cleanup_expired_files() -> None:
    """Background thread: wipe files for jobs whose 1-hour window has passed."""
    while True:
        time.sleep(600)  # check every 10 minutes
        try:
            from app.models.job import Job
            db = SessionLocal()
            now = datetime.now(timezone.utc)
            expired = (
                db.query(Job)
                .filter(Job.files_deleted == False, Job.expires_at != None)
                .all()
            )
            for job in expired:
                exp = job.expires_at
                if exp is not None:
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp > now:
                        continue
                # Wipe files
                for p in [job.file_path, job.result_file_path]:
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                chunks_dir = os.path.join(settings.CHUNKS_DIR, job.job_id)
                shutil.rmtree(chunks_dir, ignore_errors=True)
                job.files_deleted    = True
                job.file_path        = None
                job.result_file_path = None
                job.download_token   = None
            db.commit()
            db.close()
        except Exception as exc:
            print(f"[cleanup] error: {exc}")


threading.Thread(target=_cleanup_expired_files, daemon=True, name="file-cleanup").start()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Enterprise data cleaning SaaS — async, chunked, multi-worker",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(agents_router.router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}
