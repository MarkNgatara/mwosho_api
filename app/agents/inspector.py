"""Agent 2: Inspection Agent — data quality scoring + issue detection."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import (
    read_sample_rows, get_column_stats, profile_dataset,
    detect_duplicates, detect_outliers, generate_quality_score,
)

_TOOLS = [
    {"name": "read_sample_rows",      "description": "Read sample rows",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "get_column_stats",      "description": "Stats for one column",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}}, "required": ["file_path", "column"]}},
    {"name": "profile_dataset",       "description": "Full column profile",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "detect_duplicates",     "description": "Count duplicate rows",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "detect_outliers",       "description": "Detect outliers in a numeric column (IQR)",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}}, "required": ["file_path", "column"]}},
    {"name": "generate_quality_score","description": "Compute overall data quality score 0-100",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
]

_SYSTEM = """You are a Data Inspection Agent. Thoroughly analyse the dataset and report:
- Overall quality score (0-100)
- Null rates per column
- Duplicate count
- Outliers in numeric columns
- Format inconsistencies
- Statistical anomalies

Output ONLY valid JSON:
{"quality_score": 62, "issues_found": 14, "null_columns": [...], "duplicate_rows": 120, "outlier_columns": [...], "summary": "..."}"""


class InspectorAgent(BaseAgent):
    name = "inspector"
    model = "claude-haiku-4-5"

    def run(self, job: Job, db: Session) -> None:
        # Pre-compute quality score directly (fast, no Claude needed for numbers)
        qs = generate_quality_score(job.file_path)
        dupes = detect_duplicates(job.file_path)
        profile = profile_dataset(job.file_path)

        result = self.run_with_tools(
            system=_SYSTEM,
            prompt=(
                f"Inspect this dataset. File: {job.file_path}\n"
                f"Pre-computed quality score: {qs}\n"
                f"Duplicate info: {dupes}\n"
                f"Profile: {json.dumps(profile, default=str)[:2000]}"
            ),
            tool_definitions=_TOOLS,
            tool_handlers={
                "read_sample_rows": read_sample_rows,
                "get_column_stats": get_column_stats,
                "profile_dataset": profile_dataset,
                "detect_duplicates": detect_duplicates,
                "detect_outliers": detect_outliers,
                "generate_quality_score": generate_quality_score,
            },
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            inspection = json.loads(m.group()) if m else {}
        except Exception:
            inspection = {"quality_score": qs.get("quality_score", 0), "summary": result}

        job.quality_score_before = float(inspection.get("quality_score", qs.get("quality_score", 0)))
        job.issues_found = int(inspection.get("issues_found", 0))
        outputs = job.agent_outputs or {}
        outputs["inspection"] = inspection
        job.agent_outputs = outputs
        db.commit()
