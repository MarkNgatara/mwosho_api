import json

import anthropic
import pandas as pd

from app.config import settings


class AIService:
    def __init__(self):
        self.client = (
            anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            if settings.ANTHROPIC_API_KEY
            else None
        )

    def get_insights(self, df: pd.DataFrame) -> dict:
        if not self.client:
            return {"message": "AI insights disabled — set ANTHROPIC_API_KEY in .env"}

        summary = {
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "missing_per_column": df.isnull().sum().to_dict(),
            "sample_rows": df.head(5).to_dict(),
            "numeric_stats": df.describe().to_dict() if not df.select_dtypes(include="number").empty else {},
        }

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    "Analyze this dataset summary and return ONLY valid JSON with these keys:\n"
                    "- issues: list of data quality issues\n"
                    "- recommendations: list of cleaning recommendations\n"
                    "- quality_score: integer 0–100\n"
                    "- anomalies: list of unusual patterns\n\n"
                    f"{json.dumps(summary, indent=2, default=str)}"
                ),
            }],
        )

        try:
            return json.loads(response.content[0].text)
        except Exception:
            return {"raw": response.content[0].text}
