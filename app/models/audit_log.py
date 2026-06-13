from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id         = Column(Integer, primary_key=True, index=True)
    job_id     = Column(String(64), index=True, nullable=False)
    agent      = Column(String(50), nullable=False)
    action     = Column(String(100), nullable=False)
    detail     = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
