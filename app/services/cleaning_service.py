import json

import numpy as np
import pandas as pd


class CleaningService:
    def __init__(self, options: dict):
        self.remove_duplicates   = options.get("remove_duplicates", True)
        self.fill_missing        = options.get("fill_missing", True)
        self.fix_formatting      = options.get("fix_formatting", True)
        self.remove_empty_rows   = options.get("remove_empty_rows", True)
        self.fill_strategy       = options.get("missing_fill_strategy", "mean")
        self.fill_value          = options.get("missing_fill_value")

    def clean_chunk(self, chunk_path: str) -> dict:
        df = pd.read_csv(chunk_path)
        stats = {"duplicates_removed": 0, "missing_filled": 0}

        if self.remove_empty_rows:
            df = df.dropna(how="all")

        if self.remove_duplicates:
            before = len(df)
            df = df.drop_duplicates()
            stats["duplicates_removed"] = before - len(df)

        if self.fill_missing:
            stats["missing_filled"] = int(df.isnull().sum().sum())
            df = self._fill_missing(df)

        if self.fix_formatting:
            df = self._fix_formatting(df)

        cleaned_path = chunk_path.replace("chunk_", "cleaned_chunk_")
        df.to_csv(cleaned_path, index=False)

        stats_path = chunk_path.replace("chunk_", "stats_").replace(".csv", ".json")
        with open(stats_path, "w") as f:
            json.dump(stats, f)

        return stats

    def _fill_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        if self.fill_strategy == "mean":
            df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].mean())
        elif self.fill_strategy == "median":
            df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
        elif self.fill_strategy == "mode":
            for col in df.columns:
                mode = df[col].mode()
                df[col] = df[col].fillna(mode.iloc[0] if not mode.empty else None)
        elif self.fill_strategy == "fill_value" and self.fill_value is not None:
            df = df.fillna(self.fill_value)
        elif self.fill_strategy == "drop":
            df = df.dropna()

        # Any remaining object/string nulls → "Unknown"
        str_cols = df.select_dtypes(include=["object"]).columns
        df[str_cols] = df[str_cols].fillna("Unknown")

        return df

    def _fix_formatting(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        return df
