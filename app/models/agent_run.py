from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Float
from sqlalchemy.sql import func
from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id               = Column(Integer, primary_key=True, index=True)
    job_id           = Column(String(64), index=True, nullable=False)
    agent_name       = Column(String(50), nullable=False)
    status           = Column(String(20), default="pending")   # pending|running|completed|failed|skipped
    output_data      = Column(JSON)
    error_message    = Column(Text)
    duration_seconds = Column(Float)
    started_at       = Column(DateTime(timezone=True))
    completed_at     = Column(DateTime(timezone=True), onupdate=func.now())
