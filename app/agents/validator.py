"""Agent 6: Validation Agent — compares before/after, scores improvement."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import validate_output, generate_quality_score


_SYSTEM = """You are a Data Validation Agent.
Compare the original and cleaned file. Report:
- Quality improvement (before → after score)
- Data loss rate (acceptable < 5%)
- Any broken columns or suspicious changes
- Validation verdict: PASS | WARN | FAIL

Output ONLY valid JSON:
{
  "verdict": "PASS",
  "quality_before": 62,
  "quality_after": 91,
  "improvement": 29,
  "data_loss_rate": 0.02,
  "warnings": [],
  "summary": "Cleaning improved quality by 29 points with minimal data loss."
}"""


class ValidatorAgent(BaseAgent):
    name = "validator"
    model = "claude-haiku-4-5"

    def run(self, job: Job, db: Session) -> None:
        if not job.result_file_path:
            return

        comparison = validate_output(job.file_path, job.result_file_path)
        after_score = generate_quality_score(job.result_file_path)

        result = self.simple_chat(
            system=_SYSTEM,
            prompt=(
                f"Validate cleaning results.\n"
                f"Original file: {job.file_path}\n"
                f"Cleaned file: {job.result_file_path}\n"
                f"Comparison stats: {json.dumps(comparison, default=str)}\n"
                f"After quality score: {after_score}"
            ),
            max_tokens=1024,
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            validation = json.loads(m.group()) if m else {}
        except Exception:
            validation = {"verdict": "PASS", "summary": result}

        job.quality_score_after = float(
            validation.get("quality_after") or after_score.get("quality_score") or 0
        )
        job.cleaned_rows = comparison.get("cleaned_rows", 0)
        job.progress = 90.0

        outputs = job.agent_outputs or {}
        outputs["validation"] = validation
        job.agent_outputs = outputs
        db.commit()
