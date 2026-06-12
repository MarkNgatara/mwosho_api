import json

import anthropic
import numpy as np
import pandas as pd

from app.config import settings

_TOOLS = [
    {
        "name": "profile_data",
        "description": (
            "Profile the dataset — shape, dtypes, null counts, unique counts, "
            "and sample values. Call this first before any other tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to profile. Omit to profile all.",
                }
            },
        },
    },
    {
        "name": "detect_issues",
        "description": "Detect a specific category of data quality issue and return counts + examples.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_type": {
                    "type": "string",
                    "enum": [
                        "duplicates",
                        "missing_values",
                        "outliers",
                        "whitespace",
                        "inconsistent_case",
                        "mixed_types",
                    ],
                    "description": "Category of issue to check for.",
                }
            },
            "required": ["issue_type"],
        },
    },
    {
        "name": "apply_operation",
        "description": "Apply a cleaning operation to the working dataset. Returns rows_before/after.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "drop_duplicates",
                        "fill_missing_mean",
                        "fill_missing_median",
                        "fill_missing_mode",
                        "fill_missing_value",
                        "drop_missing_rows",
                        "strip_whitespace",
                        "fix_case_lower",
                        "fix_case_title",
                        "remove_outliers_iqr",
                        "fix_numeric_strings",
                    ],
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target columns. Omit to apply to all applicable columns.",
                },
                "fill_value": {
                    "type": "string",
                    "description": "Literal fill value — only used with fill_missing_value.",
                },
            },
            "required": ["operation"],
        },
    },
    {
        "name": "get_quality_score",
        "description": "Compute a 0–100 quality score for the current dataset state with a dimensional breakdown.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "finalize",
        "description": (
            "End the agent run and emit the final cleaning report. "
            "Call this once you are satisfied with the result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quality_score":      {"type": "integer"},
                "issues_found":       {"type": "array", "items": {"type": "string"}},
                "operations_applied": {"type": "array", "items": {"type": "string"}},
                "recommendations":    {"type": "array", "items": {"type": "string"}},
                "anomalies":          {"type": "array", "items": {"type": "string"}},
            },
            "required": ["quality_score", "issues_found", "operations_applied", "recommendations"],
        },
    },
]

_SYSTEM = """\
You are an autonomous data-cleaning agent. Work through these steps in order:
1. Call profile_data (all columns) to understand the dataset.
2. Call detect_issues for every relevant issue type.
3. Call apply_operation for each justified fix — do not over-clean.
4. Call get_quality_score to verify improvement.
5. Call finalize with your complete report.

Be concise in reasoning. Never skip finalize.\
"""


class AIService:
    def __init__(self):
        self.client = (
            anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            if settings.ANTHROPIC_API_KEY
            else None
        )

    # ── public API ────────────────────────────────────────────────────────

    def run_agent(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
        """
        Agentic cleaning on a representative sample.
        Returns (cleaned_df, report_dict).
        """
        if not self.client:
            return df, {"message": "AI agent disabled — set ANTHROPIC_API_KEY"}
        return self._agent_loop(df.copy())

    # kept for backward compat
    def get_insights(self, df: pd.DataFrame) -> dict:
        _, report = self.run_agent(df)
        return report

    # ── tool implementations ──────────────────────────────────────────────

    @staticmethod
    def _profile_data(df: pd.DataFrame, columns: list[str] | None) -> dict:
        cols = df[columns] if columns else df
        profile: dict = {"shape": {"rows": len(df), "columns": len(df.columns)}, "columns": {}}
        for col in cols.columns:
            s = cols[col]
            info: dict = {
                "dtype":       str(s.dtype),
                "null_count":  int(s.isnull().sum()),
                "null_pct":    round(float(s.isnull().mean() * 100), 1),
                "unique":      int(s.nunique()),
                "sample":      [str(v) for v in s.dropna().head(3).tolist()],
            }
            if pd.api.types.is_numeric_dtype(s) and not s.dropna().empty:
                info["stats"] = {
                    "min":  round(float(s.min()), 4),
                    "max":  round(float(s.max()), 4),
                    "mean": round(float(s.mean()), 4),
                    "std":  round(float(s.std()), 4),
                }
            profile["columns"][col] = info
        return profile

    @staticmethod
    def _detect_issues(df: pd.DataFrame, issue_type: str) -> dict:
        if issue_type == "duplicates":
            n = int(df.duplicated().sum())
            return {"duplicate_rows": n, "pct": round(n / max(len(df), 1) * 100, 1)}

        if issue_type == "missing_values":
            missing = {c: int(v) for c, v in df.isnull().sum().items() if v > 0}
            return {"columns_with_nulls": missing, "total_missing": sum(missing.values())}

        if issue_type == "outliers":
            result: dict = {}
            for col in df.select_dtypes(include="number").columns:
                q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
                iqr = q3 - q1
                n = int(((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum())
                if n:
                    result[col] = n
            return {"columns_with_outliers": result}

        if issue_type == "whitespace":
            result = {}
            for col in df.select_dtypes(include="object").columns:
                n = int(df[col].dropna().apply(lambda x: str(x) != str(x).strip()).sum())
                if n:
                    result[col] = n
            return {"columns_with_whitespace": result}

        if issue_type == "inconsistent_case":
            result = {}
            for col in df.select_dtypes(include="object").columns:
                vals = df[col].dropna()
                if vals.nunique() != vals.str.lower().nunique():
                    result[col] = "case variants detected"
            return {"columns_affected": result}

        if issue_type == "mixed_types":
            result = {}
            for col in df.select_dtypes(include="object").columns:
                sample = df[col].dropna().head(100)
                numeric = int(pd.to_numeric(sample, errors="coerce").notna().sum())
                if 0 < numeric < len(sample):
                    result[col] = f"{numeric}/{len(sample)} values appear numeric"
            return {"columns_with_mixed_types": result}

        return {"error": f"unknown issue_type: {issue_type}"}

    @staticmethod
    def _apply_operation(
        df: pd.DataFrame, operation: str, columns: list[str] | None, fill_value: str | None
    ) -> tuple[pd.DataFrame, dict]:
        before = len(df)

        obj_cols = lambda: (columns or df.select_dtypes(include="object").columns.tolist())
        num_cols = lambda: (columns or df.select_dtypes(include="number").columns.tolist())

        if operation == "drop_duplicates":
            df = df.drop_duplicates()

        elif operation == "fill_missing_mean":
            for c in num_cols():
                if c in df and pd.api.types.is_numeric_dtype(df[c]):
                    df[c] = df[c].fillna(df[c].mean())

        elif operation == "fill_missing_median":
            for c in num_cols():
                if c in df and pd.api.types.is_numeric_dtype(df[c]):
                    df[c] = df[c].fillna(df[c].median())

        elif operation == "fill_missing_mode":
            for c in (columns or df.columns.tolist()):
                if c in df:
                    mode = df[c].mode()
                    if not mode.empty:
                        df[c] = df[c].fillna(mode.iloc[0])

        elif operation == "fill_missing_value":
            val = fill_value or ""
            for c in (columns or df.columns.tolist()):
                if c in df:
                    df[c] = df[c].fillna(val)

        elif operation == "drop_missing_rows":
            df = df.dropna(subset=columns if columns else None)

        elif operation == "strip_whitespace":
            for c in obj_cols():
                if c in df:
                    df[c] = df[c].str.strip()

        elif operation == "fix_case_lower":
            for c in obj_cols():
                if c in df:
                    df[c] = df[c].str.lower()

        elif operation == "fix_case_title":
            for c in obj_cols():
                if c in df:
                    df[c] = df[c].str.title()

        elif operation == "remove_outliers_iqr":
            for c in num_cols():
                if c in df and pd.api.types.is_numeric_dtype(df[c]):
                    q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
                    iqr = q3 - q1
                    df = df[(df[c] >= q1 - 1.5 * iqr) & (df[c] <= q3 + 1.5 * iqr)]

        elif operation == "fix_numeric_strings":
            for c in obj_cols():
                if c in df:
                    converted = pd.to_numeric(df[c], errors="coerce")
                    if converted.notna().sum() > len(df) * 0.5:
                        df[c] = converted

        return df, {
            "operation":       operation,
            "rows_before":     before,
            "rows_after":      len(df),
            "rows_removed":    before - len(df),
            "columns":         columns or "all applicable",
        }

    @staticmethod
    def _quality_score(df: pd.DataFrame) -> dict:
        if df.empty:
            return {"score": 0, "breakdown": {}}

        cells = df.size
        completeness = (1 - df.isnull().sum().sum() / cells) * 100 if cells else 100.0
        uniqueness   = max(0.0, 100.0 - df.duplicated().mean() * 100)

        mixed = sum(
            1 for c in df.select_dtypes(include="object").columns
            if 0 < int(pd.to_numeric(df[c].dropna().head(100), errors="coerce").notna().sum())
               < min(len(df[c].dropna()), 100) * 0.9
        )
        consistency = max(0.0, 100.0 - mixed / max(len(df.columns), 1) * 100)

        ws_issues = sum(
            int(df[c].dropna().apply(lambda x: str(x) != str(x).strip()).sum())
            for c in df.select_dtypes(include="object").columns
        )
        validity = max(0.0, 100.0 - ws_issues / max(cells, 1) * 100)

        score = completeness * 0.35 + uniqueness * 0.25 + consistency * 0.2 + validity * 0.2
        return {
            "score": int(round(score)),
            "breakdown": {
                "completeness": round(completeness, 1),
                "uniqueness":   round(uniqueness, 1),
                "consistency":  round(consistency, 1),
                "validity":     round(validity, 1),
            },
        }

    # ── agent loop ────────────────────────────────────────────────────────

    def _agent_loop(self, df: pd.DataFrame, max_iterations: int = 20) -> tuple[pd.DataFrame, dict]:
        ops_log: list[dict] = []
        final_report: dict = {}

        messages = [{
            "role": "user",
            "content": (
                f"Dataset: {len(df)} rows × {len(df.columns)} columns. "
                f"Columns: {list(df.columns)}. "
                "Profile it, detect issues, clean it, then finalize."
            ),
        }]

        for _ in range(max_iterations):
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "end_turn":
                break
            if resp.stop_reason != "tool_use":
                break

            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue

                name  = block.name
                inp   = block.input
                result: dict = {}

                if name == "profile_data":
                    result = self._profile_data(df, inp.get("columns"))

                elif name == "detect_issues":
                    result = self._detect_issues(df, inp["issue_type"])

                elif name == "apply_operation":
                    df, op = self._apply_operation(
                        df, inp["operation"], inp.get("columns"), inp.get("fill_value")
                    )
                    ops_log.append(op)
                    result = op

                elif name == "get_quality_score":
                    result = self._quality_score(df)

                elif name == "finalize":
                    final_report = {
                        "quality_score":      inp.get("quality_score", 0),
                        "issues_found":       inp.get("issues_found", []),
                        "operations_applied": inp.get("operations_applied", []),
                        "recommendations":    inp.get("recommendations", []),
                        "anomalies":          inp.get("anomalies", []),
                        "rows_before":        len(df) + sum(o.get("rows_removed", 0) for o in ops_log),
                        "rows_after":         len(df),
                        "operations_log":     ops_log,
                        "quality_breakdown":  self._quality_score(df).get("breakdown", {}),
                    }
                    return df, final_report

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result, default=str),
                })

            messages.append({"role": "user", "content": tool_results})

        # agent hit max iterations without calling finalize
        qs = self._quality_score(df)
        return df, {
            "quality_score":      qs["score"],
            "issues_found":       [],
            "operations_applied": [o["operation"] for o in ops_log],
            "recommendations":    ["Agent reached iteration limit — review manually."],
            "anomalies":          [],
            "rows_before":        len(df) + sum(o.get("rows_removed", 0) for o in ops_log),
            "rows_after":         len(df),
            "operations_log":     ops_log,
            "quality_breakdown":  qs.get("breakdown", {}),
        }
