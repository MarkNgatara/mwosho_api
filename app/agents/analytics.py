"""Agent 7: Analytics Agent — business insights from cleaned data. PRO/ENTERPRISE only."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import read_sample_rows, get_column_stats, profile_dataset
from app.agents.rule_packs import get_rule_pack

_TOOLS = [
    {"name": "read_sample_rows", "description": "Read sample rows from cleaned file",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "n": {"type": "integer"}}, "required": ["file_path"]}},
    {"name": "get_column_stats", "description": "Stats for a specific column",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}}, "required": ["file_path", "column"]}},
    {"name": "profile_dataset",  "description": "Full dataset profile",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
]

_SYSTEM = """You are a Data Analytics Agent. Analyze the cleaned dataset and generate actionable business insights.
Focus on the analytics relevant to the dataset type.

Provide insights like:
- Patterns and anomalies
- Distribution breakdowns
- Outlier groups
- Business-relevant observations
- Recommendations

Output ONLY valid JSON:
{
  "key_insights": [
    "Supplier A costs 12% more than Supplier B for identical SKUs",
    "1,842 customer records show no activity in 12+ months"
  ],
  "anomalies": ["Branch Nairobi has 4x more inventory inconsistencies than Branch Mombasa"],
  "recommendations": ["Review dormant accounts", "Investigate Nairobi branch data entry process"],
  "data_health": "GOOD"
}"""


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    model = "claude-sonnet-4-5"

    def run(self, job: Job, db: Session) -> None:
        cleaned_path = job.result_file_path or job.file_path
        pack = get_rule_pack(job.dataset_type or "generic")
        focus = pack.analytics_focus if pack else ["general patterns", "anomalies", "data quality"]

        result = self.run_with_tools(
            system=_SYSTEM,
            prompt=(
                f"Analyze this cleaned {job.dataset_type} dataset.\n"
                f"File: {cleaned_path}\n"
                f"Analytics focus areas: {focus}\n"
                f"Quality score: {job.quality_score_after}\n"
                f"Row count: {job.cleaned_rows}"
            ),
            tool_definitions=_TOOLS,
            tool_handlers={
                "read_sample_rows": lambda **kw: read_sample_rows(cleaned_path, kw.get("n", 50)),
                "get_column_stats": lambda **kw: get_column_stats(cleaned_path, kw["column"]),
                "profile_dataset":  lambda **kw: profile_dataset(cleaned_path),
            },
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            analytics = json.loads(m.group()) if m else {"key_insights": [], "summary": result}
        except Exception:
            analytics = {"key_insights": [], "summary": result}

        job.analytics_insights = analytics
        outputs = job.agent_outputs or {}
        outputs["analytics"] = analytics
        job.agent_outputs = outputs
        db.commit()
