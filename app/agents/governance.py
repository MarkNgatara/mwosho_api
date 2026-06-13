"""Agent 3: Governance Agent — PII detection, GDPR, compliance risks. PRO/ENTERPRISE only."""
import json, re
from sqlalchemy.orm import Session
from app.models.job import Job
from app.agents.base import BaseAgent
from app.agents.tools import detect_pii, detect_sensitive_fields, read_sample_rows
from app.agents.rule_packs import get_rule_pack

_TOOLS = [
    {"name": "detect_pii",             "description": "Scan all columns for PII patterns (email, phone, card, ID, SSN)",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "detect_sensitive_fields","description": "Identify columns with sensitive-sounding names",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "read_sample_rows",       "description": "Read sample rows for manual inspection",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "n": {"type": "integer"}}, "required": ["file_path"]}},
]

_SYSTEM = """You are a Data Governance Agent. Your job is to:
1. Detect PII (Personally Identifiable Information) in the dataset
2. Identify GDPR/compliance risks
3. Suggest masking or redaction actions
4. Flag data retention concerns

Output ONLY valid JSON:
{
  "has_pii": true,
  "pii_columns": {"email": ["email"], "phone": ["contact_number"]},
  "risk_level": "HIGH",
  "gdpr_concerns": ["customer emails without consent flag", "credit card numbers in plain text"],
  "recommended_actions": ["Mask credit_card column before export", "Add consent_date field"],
  "compliance_notes": "..."
}
Risk levels: LOW | MEDIUM | HIGH | CRITICAL"""


class GovernanceAgent(BaseAgent):
    name = "governance"
    model = "claude-sonnet-4-5"   # More careful reasoning for compliance

    def run(self, job: Job, db: Session) -> None:
        pack = get_rule_pack(job.dataset_type or "generic")
        pack_notes = pack.compliance_notes if pack else ""
        dataset_type = job.dataset_type or "unknown"

        result = self.run_with_tools(
            system=_SYSTEM,
            prompt=(
                f"Perform governance review. File: {job.file_path}\n"
                f"Dataset type: {dataset_type}\n"
                f"Industry compliance note: {pack_notes}"
            ),
            tool_definitions=_TOOLS,
            tool_handlers={
                "detect_pii": detect_pii,
                "detect_sensitive_fields": detect_sensitive_fields,
                "read_sample_rows": read_sample_rows,
            },
        )
        try:
            m = re.search(r"\{.*\}", result, re.DOTALL)
            governance = json.loads(m.group()) if m else {"has_pii": False, "risk_level": "LOW"}
        except Exception:
            governance = {"has_pii": False, "risk_level": "LOW", "summary": result}

        job.governance_flags = governance
        outputs = job.agent_outputs or {}
        outputs["governance"] = governance
        job.agent_outputs = outputs
        db.commit()
