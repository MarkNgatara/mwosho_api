"""Agent 4: Planning Agent — creates ordered, intelligent cleaning plan. Stores in DB. Nothing runs yet."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import profile_dataset, detect_duplicates, generate_quality_score
from app.agents.rule_packs import get_rule_pack

_SYSTEM = """You are a Data Cleaning Planning Agent.
Given the inspection results, dataset type, and rule pack — create a precise, ordered cleaning plan.

Each step must have:
- step_number (int)
- rule (one of: remove_duplicates, remove_empty_rows, strip_whitespace, normalize_case,
        fill_missing_mean, fill_missing_mode, normalize_dates, mask_pii)
- description (plain English)
- column (optional — which column to apply to, empty = all)
- priority (critical|high|medium|low)

Output ONLY valid JSON:
{
  "plan_version": 1,
  "dataset_type": "crm",
  "estimated_improvement": 25,
  "steps": [
    {"step_number": 1, "rule": "remove_duplicates", "description": "Remove 1,204 duplicate rows", "column": "", "priority": "critical"},
    {"step_number": 2, "rule": "strip_whitespace", "description": "Strip whitespace from all text fields", "column": "", "priority": "high"}
  ]
}"""


class PlannerAgent(BaseAgent):
    name = "planner"
    model = "claude-sonnet-4-5"

    def run(self, job: Job, db: Session) -> None:
        pack = get_rule_pack(job.dataset_type or "generic")
        pack_steps = json.dumps(pack.cleaning_steps, default=str) if pack else "[]"
        inspection = (job.agent_outputs or {}).get("inspection", {})
        governance = job.governance_flags or {}

        result = self.simple_chat(
            system=_SYSTEM,
            prompt=(
                f"Create cleaning plan for this dataset.\n"
                f"File: {job.file_path}\n"
                f"Dataset type: {job.dataset_type}\n"
                f"Quality score before: {job.quality_score_before}\n"
                f"Issues found: {job.issues_found}\n"
                f"Inspection summary: {json.dumps(inspection, default=str)[:1500]}\n"
                f"Governance flags: {json.dumps(governance, default=str)[:500]}\n"
                f"Rule pack suggested steps: {pack_steps}"
            ),
            max_tokens=2048,
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            plan = json.loads(m.group()) if m else {"steps": pack.cleaning_steps if pack else []}
        except Exception:
            plan = {"steps": pack.cleaning_steps if pack else [], "note": result[:500]}

        job.cleaning_plan = plan
        outputs = job.agent_outputs or {}
        outputs["plan"] = plan
        job.agent_outputs = outputs
        db.commit()
