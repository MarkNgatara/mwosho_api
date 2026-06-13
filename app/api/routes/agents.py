"""API routes for agent pipeline status, audit logs, and reports."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job
from app.models.audit_log import AuditLog
from app.models.agent_run import AgentRun
from app.models.user import User
from app.utils.helpers import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentRunOut(BaseModel):
    agent_name: str
    status: str
    duration_seconds: float | None
    error_message: str | None

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    agent: str
    action: str
    detail: str | None
    created_at: str | None

    class Config:
        from_attributes = True


class PipelineStatusOut(BaseModel):
    job_id: str
    orchestrator_state: str
    dataset_type: str | None
    quality_score_before: float | None
    quality_score_after: float | None
    issues_found: int
    agent_runs: List[AgentRunOut]
    agent_outputs: dict | None
    governance_flags: dict | None
    cleaning_plan: dict | None
    analytics_insights: dict | None
    report_data: dict | None


@router.get("/{job_id}/status", response_model=PipelineStatusOut)
def pipeline_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    runs = db.query(AgentRun).filter(AgentRun.job_id == job_id).order_by(AgentRun.id).all()

    return PipelineStatusOut(
        job_id=job.job_id,
        orchestrator_state=job.orchestrator_state or "created",
        dataset_type=job.dataset_type,
        quality_score_before=job.quality_score_before,
        quality_score_after=job.quality_score_after,
        issues_found=job.issues_found or 0,
        agent_runs=[AgentRunOut.model_validate(r) for r in runs],
        agent_outputs=job.agent_outputs,
        governance_flags=job.governance_flags,
        cleaning_plan=job.cleaning_plan,
        analytics_insights=job.analytics_insights,
        report_data=job.report_data,
    )


@router.get("/{job_id}/audit")
def audit_log(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.job_id == job_id)
        .order_by(AuditLog.id)
        .all()
    )
    return [
        {
            "agent": l.agent,
            "action": l.action,
            "detail": l.detail,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


@router.get("/{job_id}/report")
def get_report(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.job_id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.report_data:
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return job.report_data
