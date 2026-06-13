"""Agent 5: Cleaning Agent — deterministic execution of the plan. AI suggests, Python executes."""
import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.job import Job, JobStatus
from app.agents.tools import run_cleaning_rule
from app.config import settings


class CleanerAgent:
    """No Claude here — cleaning is deterministic. Plan from Agent 4 drives execution."""
    name = "cleaner"

    def run(self, job: Job, db: Session) -> None:
        plan = job.cleaning_plan or {}
        steps = plan.get("steps", [])

        if not steps:
            # Fall back to user-selected options from upload form
            opts = job.cleaning_options or {}
            steps = []
            if opts.get("remove_duplicates"): steps.append({"rule": "remove_duplicates", "column": ""})
            if opts.get("remove_empty_rows"): steps.append({"rule": "remove_empty_rows", "column": ""})
            if opts.get("fix_formatting"):   steps.append({"rule": "strip_whitespace",   "column": ""})
            if opts.get("fill_missing"):     steps.append({"rule": "fill_missing_mode",  "column": ""})

        src_path = job.file_path
        ext = Path(src_path).suffix

        # Work on a copy so original is preserved
        work_path = str(Path(settings.PROCESSED_DIR) / f"{job.job_id}_work{ext}")
        Path(settings.PROCESSED_DIR).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, work_path)

        total_dupes = 0
        total_missing = 0
        steps_done = []

        for i, step in enumerate(steps):
            rule = step.get("rule", "")
            col = step.get("column", "") or ""
            result = run_cleaning_rule(
                file_path=work_path,
                rule=rule,
                output_path=work_path,
                column=col,
            )
            if "error" not in result:
                if rule == "remove_duplicates":
                    total_dupes += result.get("rows_affected", 0)
                elif "fill_missing" in rule:
                    total_missing += result.get("changed", 0)
                steps_done.append({"step": i + 1, "rule": rule, "result": result})

            # Update progress
            progress = 20.0 + (i + 1) / max(len(steps), 1) * 60.0
            job.progress = round(progress, 1)
            db.commit()

        # Final output path
        result_path = str(Path(settings.PROCESSED_DIR) / f"{job.job_id}_cleaned{ext}")
        shutil.move(work_path, result_path)

        job.result_file_path = result_path
        job.duplicates_removed = total_dupes
        job.missing_filled = total_missing
        job.status = JobStatus.COMPLETED
        job.progress = 80.0

        outputs = job.agent_outputs or {}
        outputs["cleaning"] = {"steps_executed": steps_done}
        job.agent_outputs = outputs
        db.commit()
