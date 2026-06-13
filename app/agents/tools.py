"""
Real data analysis tools that agents call via Claude's tool_use API.
All tools operate on actual files using pandas.
"""
import re
import json
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


# ── File loader ───────────────────────────────────────────────────────────────

def _load(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")


def _save(df: pd.DataFrame, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False)


# ── Tool functions ─────────────────────────────────────────────────────────────

def read_sample_rows(file_path: str, n: int = 50) -> dict:
    try:
        df = _load(file_path)
        sample = df.head(n).where(pd.notna(df.head(n)), None)
        return {
            "columns": list(df.columns),
            "sample_rows": sample.to_dict(orient="records"),
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
        }
    except Exception as e:
        return {"error": str(e)}


def get_column_stats(file_path: str, column: str) -> dict:
    try:
        df = _load(file_path)
        if column not in df.columns:
            return {"error": f"Column '{column}' not found"}
        col = df[column]
        stats: dict[str, Any] = {
            "column": column,
            "dtype": str(col.dtype),
            "null_count": int(col.isna().sum()),
            "null_rate": round(float(col.isna().mean()), 4),
            "unique_count": int(col.nunique()),
            "sample_values": [str(v) for v in col.dropna().head(5).tolist()],
        }
        if pd.api.types.is_numeric_dtype(col):
            num = col.dropna()
            if len(num):
                stats.update({
                    "min": float(num.min()),
                    "max": float(num.max()),
                    "mean": round(float(num.mean()), 4),
                    "std": round(float(num.std()), 4),
                })
        return stats
    except Exception as e:
        return {"error": str(e)}


def profile_dataset(file_path: str) -> dict:
    try:
        df = _load(file_path)
        profile = {}
        for col in df.columns:
            c = df[col]
            profile[col] = {
                "dtype": str(c.dtype),
                "null_rate": round(float(c.isna().mean()), 4),
                "unique_count": int(c.nunique()),
                "sample": [str(v) for v in c.dropna().head(3).tolist()],
            }
        return {
            "profile": profile,
            "shape": [int(df.shape[0]), int(df.shape[1])],
        }
    except Exception as e:
        return {"error": str(e)}


def detect_schema(file_path: str) -> dict:
    try:
        df = _load(file_path)
        return {
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
        }
    except Exception as e:
        return {"error": str(e)}


def detect_pii(file_path: str) -> dict:
    PATTERNS = {
        "email":       r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
        "phone":       r'\b(\+?[\d\s\-\(\)]{7,15})\b',
        "credit_card": r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
        "national_id": r'\b[A-Z]{1,2}\d{6,9}\b',
        "ssn":         r'\b\d{3}-\d{2}-\d{4}\b',
        "passport":    r'\b[A-Z]{1,2}[0-9]{6,9}\b',
        "ip_address":  r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
    }
    try:
        df = _load(file_path)
        findings: dict[str, dict] = {}
        for col in df.columns:
            sample = df[col].dropna().astype(str).head(200)
            col_pii: dict[str, int] = {}
            for pii_type, pattern in PATTERNS.items():
                count = int(sample.str.contains(pattern, regex=True, na=False).sum())
                if count > 0:
                    col_pii[pii_type] = count
            if col_pii:
                findings[col] = col_pii
        return {
            "pii_found": findings,
            "columns_with_pii": list(findings.keys()),
            "has_pii": len(findings) > 0,
        }
    except Exception as e:
        return {"error": str(e)}


def detect_sensitive_fields(file_path: str) -> dict:
    """Identify fields by name that are likely sensitive."""
    SENSITIVE_KEYWORDS = [
        "password", "secret", "token", "key", "card", "account",
        "ssn", "sin", "tax", "salary", "wage", "income",
        "dob", "birth", "gender", "race", "religion", "health",
        "diagnosis", "medication", "medical",
    ]
    try:
        df = _load(file_path)
        flagged = {}
        for col in df.columns:
            col_lower = col.lower().replace("_", " ").replace("-", " ")
            matched = [kw for kw in SENSITIVE_KEYWORDS if kw in col_lower]
            if matched:
                flagged[col] = matched
        return {"sensitive_fields": flagged, "count": len(flagged)}
    except Exception as e:
        return {"error": str(e)}


def detect_duplicates(file_path: str) -> dict:
    try:
        df = _load(file_path)
        total = len(df)
        dupes = int(df.duplicated().sum())
        return {
            "total_rows": total,
            "duplicate_rows": dupes,
            "duplicate_rate": round(dupes / total, 4) if total else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def detect_outliers(file_path: str, column: str) -> dict:
    try:
        df = _load(file_path)
        if column not in df.columns:
            return {"error": f"Column '{column}' not found"}
        col = pd.to_numeric(df[column], errors="coerce").dropna()
        if len(col) == 0:
            return {"outlier_count": 0, "note": "No numeric data"}
        q1 = float(col.quantile(0.25))
        q3 = float(col.quantile(0.75))
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = col[(col < lower) | (col > upper)]
        return {
            "column": column,
            "outlier_count": int(len(outliers)),
            "outlier_rate": round(float(len(outliers) / len(col)), 4),
            "bounds": {"lower": round(lower, 4), "upper": round(upper, 4)},
        }
    except Exception as e:
        return {"error": str(e)}


def generate_quality_score(file_path: str) -> dict:
    try:
        df = _load(file_path)
        if df.empty:
            return {"quality_score": 0}
        null_rate = float(df.isna().mean().mean())
        dupe_rate = float(df.duplicated().mean())
        completeness = (1 - null_rate) * 40
        uniqueness = (1 - dupe_rate) * 30
        consistency = 30
        score = int(min(max(completeness + uniqueness + consistency, 0), 100))
        return {
            "quality_score": score,
            "null_rate": round(null_rate, 4),
            "duplicate_rate": round(dupe_rate, 4),
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
        }
    except Exception as e:
        return {"error": str(e)}


def run_cleaning_rule(file_path: str, rule: str, output_path: str, column: str = "", **kwargs) -> dict:
    """Execute a named cleaning rule on the file. Deterministic — no AI."""
    try:
        df = _load(file_path)
        rows_before = len(df)
        changed = 0

        if rule == "remove_duplicates":
            df2 = df.drop_duplicates()
            changed = rows_before - len(df2)
            df = df2

        elif rule == "remove_empty_rows":
            df2 = df.dropna(how="all")
            changed = rows_before - len(df2)
            df = df2

        elif rule == "strip_whitespace":
            for c in df.select_dtypes(include="object").columns:
                df[c] = df[c].str.strip()
            changed = rows_before

        elif rule == "normalize_case":
            case = kwargs.get("case", "title")
            cols = [column] if column else list(df.select_dtypes(include="object").columns)
            for c in cols:
                if c in df.columns:
                    if case == "lower": df[c] = df[c].str.lower()
                    elif case == "upper": df[c] = df[c].str.upper()
                    else: df[c] = df[c].str.title()
            changed = rows_before

        elif rule == "fill_missing_mean":
            cols = [column] if column else list(df.select_dtypes(include="number").columns)
            for c in cols:
                if c in df.columns:
                    n = int(df[c].isna().sum())
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    df[c] = df[c].fillna(df[c].mean())
                    changed += n

        elif rule == "fill_missing_mode":
            cols = [column] if column else list(df.columns)
            for c in cols:
                if c in df.columns:
                    n = int(df[c].isna().sum())
                    mode = df[c].mode()
                    if len(mode): df[c] = df[c].fillna(mode[0])
                    changed += n

        elif rule == "normalize_dates":
            cols = [column] if column else [
                c for c in df.columns
                if any(k in c.lower() for k in ["date", "time", "dob", "created", "updated"])
            ]
            for c in cols:
                if c in df.columns:
                    try:
                        df[c] = pd.to_datetime(df[c], infer_datetime_format=True, errors="coerce")
                        df[c] = df[c].dt.strftime("%Y-%m-%d")
                        changed += 1
                    except Exception:
                        pass

        elif rule == "mask_pii":
            pii_type = kwargs.get("pii_type", "generic")
            if column and column in df.columns:
                if pii_type == "email":
                    df[column] = df[column].apply(
                        lambda x: re.sub(r"(?<=.{2}).(?=.*@)", "*", str(x)) if pd.notna(x) else x
                    )
                elif pii_type == "credit_card":
                    df[column] = df[column].apply(
                        lambda x: re.sub(r"\d(?=\d{4})", "*", str(x)) if pd.notna(x) else x
                    )
                elif pii_type == "phone":
                    df[column] = df[column].apply(
                        lambda x: re.sub(r"\d(?=\d{2})", "*", str(x)) if pd.notna(x) else x
                    )
                else:
                    df[column] = "***MASKED***"
                changed = rows_before

        else:
            return {"error": f"Unknown rule: {rule}"}

        _save(df, output_path)
        return {
            "rule": rule,
            "rows_before": rows_before,
            "rows_after": int(len(df)),
            "changed": changed,
            "output_path": output_path,
        }
    except Exception as e:
        return {"error": str(e)}


def validate_output(original_path: str, cleaned_path: str) -> dict:
    try:
        orig = _load(original_path)
        cleaned = _load(cleaned_path)
        orig_q = generate_quality_score(original_path).get("quality_score", 0)
        clean_q = generate_quality_score(cleaned_path).get("quality_score", 0)
        return {
            "original_rows": int(len(orig)),
            "cleaned_rows": int(len(cleaned)),
            "rows_removed": int(len(orig) - len(cleaned)),
            "quality_before": orig_q,
            "quality_after": clean_q,
            "improvement": clean_q - orig_q,
            "data_loss_rate": round((len(orig) - len(cleaned)) / max(len(orig), 1), 4),
            "columns_preserved": list(orig.columns) == list(cleaned.columns),
        }
    except Exception as e:
        return {"error": str(e)}


def store_audit_log(job_id: str, agent: str, action: str, detail: str = "") -> dict:
    """Stub — actual DB write done by orchestrator."""
    return {"logged": True}
