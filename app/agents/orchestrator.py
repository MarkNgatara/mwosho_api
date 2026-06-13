"""
Agent 0: Orchestrator — the brain of the pipeline.

Responsibilities:
  - Create and track job state machine
  - Route to each agent in sequence
  - Enforce subscription limits (governance/analytics = PRO+)
  - Retry failed agents (1 retry)
  - Maintain full audit log
  - Allocate workers (via Celery task dispatch)
"""
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.audit_log import AuditLog
from app.models.agent_run import AgentRun
from app.models.user import SubscriptionTier


class Orchestrator:

    # ── Audit log ─────────────────────────────────────────────────────────────

    def _log(self, db: Session, job_id: str, agent: str, action: str, detail: str = "") -> None:
        db.add(AuditLog(job_id=job_id, agent=agent, action=action, detail=detail[:1000]))
        db.commit()

    # ── State machine ─────────────────────────────────────────────────────────

    def _set_state(self, db: Session, job: Job, state: str) -> None:
        job.orchestrator_state = state
        if state == "cleaning":
            job.status = JobStatus.PROCESSING
        elif state == "completed":
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
        elif state == "failed":
            job.status = JobStatus.FAILED
        db.commit()
        self._log(db, job.job_id, "orchestrator", "state_change", f"→ {state}")

    # ── Run single agent with retry + timing ─────────────────────────────────

    def _run_agent(self, db: Session, job: Job, stage: str, agent_instance, retries: int = 1) -> None:
        run = AgentRun(
            job_id=job.job_id,
            agent_name=stage,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()

        start = time.time()
        last_error = None

        for attempt in range(retries + 1):
            try:
                agent_instance.run(job, db)
                run.status = "completed"
                run.duration_seconds = round(time.time() - start, 2)
                db.commit()
                self._log(db, job.job_id, stage, "completed", f"{run.duration_seconds}s")
                return
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    self._log(db, job.job_id, stage, "retry", f"attempt {attempt + 1}: {last_error}")
                    time.sleep(2 ** attempt)  # exponential back-off: 1s, 2s

        run.status = "failed"
        run.error_message = last_error
        run.duration_seconds = round(time.time() - start, 2)
        db.commit()
        self._log(db, job.job_id, stage, "failed", last_error or "")
        raise RuntimeError(f"Agent {stage} failed after {retries + 1} attempts: {last_error}")

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def run_pipeline(self, job_id: str) -> None:
        """Entry point called by the Celery task."""
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.job_id == job_id).first()
            if not job:
                return

            from app.models.user import User
            user = db.query(User).filter(User.id == job.user_id).first()
            tier = user.subscription_tier if user else SubscriptionTier.FREE

            self._log(db, job_id, "orchestrator", "pipeline_start",
                      f"tier={tier} file={job.original_filename}")

            # ── Agent imports (lazy — keeps startup fast) ─────────────────
            from app.agents.classifier import ClassifierAgent
            from app.agents.inspector import InspectorAgent
            from app.agents.governance import GovernanceAgent
            from app.agents.planner import PlannerAgent
            from app.agents.cleaner import CleanerAgent
            from app.agents.validator import ValidatorAgent
            from app.agents.analytics import AnalyticsAgent
            from app.agents.reporter import ReporterAgent

            # 1. Classify ─────────────────────────────────────────────────
            self._set_state(db, job, "classifying")
            self._run_agent(db, job, "classifying", ClassifierAgent())
            db.refresh(job)

            # 2. Inspect ──────────────────────────────────────────────────
            self._set_state(db, job, "inspecting")
            self._run_agent(db, job, "inspecting", InspectorAgent())
            db.refresh(job)

            # 3. Governance — PRO/SCALE/ENTERPRISE ───────────────────────
            if tier in (SubscriptionTier.PRO, SubscriptionTier.SCALE, SubscriptionTier.ENTERPRISE):
                self._set_state(db, job, "governing")
                self._run_agent(db, job, "governing", GovernanceAgent())
                db.refresh(job)
            else:
                self._log(db, job_id, "orchestrator", "skip",
                          "Governance skipped — requires PRO/ENTERPRISE")

            # 4. Plan ─────────────────────────────────────────────────────
            self._set_state(db, job, "planning")
            self._run_agent(db, job, "planning", PlannerAgent())
            db.refresh(job)

            # 5. Clean ────────────────────────────────────────────────────
            self._set_state(db, job, "cleaning")
            self._run_agent(db, job, "cleaning", CleanerAgent(), retries=0)
            db.refresh(job)

            # 6. Validate ─────────────────────────────────────────────────
            self._set_state(db, job, "validating")
            self._run_agent(db, job, "validating", ValidatorAgent())
            db.refresh(job)

            # 7. Analytics — PRO/SCALE/ENTERPRISE ────────────────────────
            if tier in (SubscriptionTier.PRO, SubscriptionTier.SCALE, SubscriptionTier.ENTERPRISE):
                self._set_state(db, job, "analyzing")
                self._run_agent(db, job, "analyzing", AnalyticsAgent())
                db.refresh(job)
            else:
                self._log(db, job_id, "orchestrator", "skip",
                          "Analytics skipped — requires PRO/ENTERPRISE")

            # 8. Report ───────────────────────────────────────────────────
            self._set_state(db, job, "reporting")
            self._run_agent(db, job, "reporting", ReporterAgent())
            db.refresh(job)

            # Done ────────────────────────────────────────────────────────
            self._set_state(db, job, "completed")
            self._log(db, job_id, "orchestrator", "pipeline_complete",
                      f"quality {job.quality_score_before} → {job.quality_score_after}")

        except Exception as exc:
            try:
                db.refresh(job)
                job.error_message = str(exc)[:500]
                self._set_state(db, job, "failed")
                self._log(db, job_id, "orchestrator", "pipeline_failed", str(exc)[:500])
            except Exception:
                pass
        finally:
            db.close()
