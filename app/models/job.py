import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Enum, Text
from sqlalchemy.sql import func
from app.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    CHUNKING = "chunking"
    PROCESSING = "processing"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    original_filename = Column(String(500))
    file_path = Column(String(1000))
    file_size_bytes = Column(Integer)

    status = Column(Enum(JobStatus), default=JobStatus.PENDING)
    progress = Column(Float, default=0.0)

    total_chunks = Column(Integer, default=0)
    completed_chunks = Column(Integer, default=0)

    total_rows = Column(Integer, default=0)
    cleaned_rows = Column(Integer, default=0)
    duplicates_removed = Column(Integer, default=0)
    missing_filled = Column(Integer, default=0)

    result_file_path = Column(String(1000))
    error_message = Column(Text)
    cleaning_options = Column(JSON)
    ai_insights = Column(JSON)

    # ── Agent pipeline ────────────────────────────────────────────────────
    orchestrator_state   = Column(String(50), default="created")
    dataset_type         = Column(String(50))
    issues_found         = Column(Integer, default=0)
    quality_score_before = Column(Float)
    quality_score_after  = Column(Float)
    governance_flags     = Column(JSON)
    cleaning_plan        = Column(JSON)
    analytics_insights   = Column(JSON)
    report_data          = Column(JSON)
    agent_outputs        = Column(JSON)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True))
