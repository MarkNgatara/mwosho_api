"""Agent 1: Classification Agent — identifies dataset type before any cleaning."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import read_sample_rows, detect_schema, profile_dataset
from app.agents.rule_packs import RULE_PACKS

_TOOLS = [
    {"name": "read_sample_rows", "description": "Read sample rows from the file",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "n": {"type": "integer"}}, "required": ["file_path"]}},
    {"name": "detect_schema",    "description": "Get column names and data types",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "profile_dataset",  "description": "Full column-by-column profile",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
]

_SYSTEM = f"""You are a Dataset Classification Agent for Mwosho Data Cleaning App.
Analyze the uploaded file and classify it into one of these types:
{", ".join(RULE_PACKS.keys())}, generic

Use the tools to inspect column names and sample data, then output ONLY valid JSON:
{{"dataset_type": "crm", "display_name": "Customer CRM Dataset", "confidence": 97, "reasoning": "...", "key_columns": ["email", "phone"]}}

Be decisive. Choose "generic" with confidence 40 if unsure."""


class ClassifierAgent(BaseAgent):
    name = "classifier"
    model = "claude-haiku-4-5"

    def run(self, job: Job, db: Session) -> None:
        result = self.run_with_tools(
            system=_SYSTEM,
            prompt=f"Classify this dataset. File: {job.file_path}",
            tool_definitions=_TOOLS,
            tool_handlers={"read_sample_rows": read_sample_rows, "detect_schema": detect_schema, "profile_dataset": profile_dataset},
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            classification = json.loads(m.group()) if m else {}
        except Exception:
            classification = {"dataset_type": "generic", "confidence": 40, "reasoning": result}

        job.dataset_type = classification.get("dataset_type", "generic")
        outputs = job.agent_outputs or {}
        outputs["classification"] = classification
        job.agent_outputs = outputs
        db.commit()
