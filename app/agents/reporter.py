"""Agent 8: Reporting Agent — synthesizes all outputs into a final plain-English report."""
import json
from sqlalchemy.orm import Session
from app.models.job import Job, JobStatus
from app.agents.base import BaseAgent

_SYSTEM = """You are a Report Writing Agent. Create a clear, professional data quality report.
Write for a non-technical data analyst — plain English, no jargon.

Structure your report exactly as JSON:
{
  "title": "Data Quality Report — Customer CRM Dataset",
  "executive_summary": "...",
  "before_after": {"quality_before": 62, "quality_after": 91, "improvement": 29},
  "cleaning_summary": {"duplicates_removed": 1204, "missing_filled": 340, "rows_cleaned": 15000},
  "key_findings": ["Finding 1", "Finding 2"],
  "governance_alerts": ["Alert if any PII found"],
  "analytics_highlights": ["Insight 1", "Insight 2"],
  "recommendations": ["Recommendation 1"],
  "generated_at": "2026-06-13"
}"""


class ReporterAgent(BaseAgent):
    name = "reporter"
    model = "claude-sonnet-4-5"

    def run(self, job: Job, db: Session) -> None:
        outputs = job.agent_outputs or {}

        report = self.simple_chat(
            system=_SYSTEM,
            prompt=(
                f"Write a data quality report for job {job.job_id}.\n\n"
                f"Dataset type: {job.dataset_type}\n"
                f"Original file: {job.original_filename}\n"
                f"Quality before: {job.quality_score_before}\n"
                f"Quality after: {job.quality_score_after}\n"
                f"Issues found: {job.issues_found}\n"
                f"Duplicates removed: {job.duplicates_removed}\n"
                f"Missing filled: {job.missing_filled}\n"
                f"Cleaned rows: {job.cleaned_rows}\n"
                f"Governance: {json.dumps(job.governance_flags or {}, default=str)[:800]}\n"
                f"Analytics: {json.dumps(job.analytics_insights or {}, default=str)[:800]}\n"
                f"Validation: {json.dumps(outputs.get('validation', {}), default=str)[:600]}\n"
                f"Cleaning plan: {json.dumps(job.cleaning_plan or {}, default=str)[:600]}"
            ),
            max_tokens=2048,
        )
        import re
        try:
            m = re.search(r"\{.*\}", report, re.DOTALL)
            report_data = json.loads(m.group()) if m else {"executive_summary": report}
        except Exception:
            report_data = {"executive_summary": report}

        job.report_data = report_data
        job.status = JobStatus.COMPLETED
        job.progress = 100.0
        outputs["report"] = report_data
        job.agent_outputs = outputs
        db.commit()
