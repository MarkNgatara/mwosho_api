import json
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from app.config import settings


class FileService:

    @staticmethod
    def split_into_chunks(file_path: str, job_id: str, options: dict) -> Tuple[List[str], int]:
        chunk_dir = Path(settings.CHUNKS_DIR) / job_id
        chunk_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(file_path).suffix.lower()
        chunk_paths: List[str] = []
        total_rows = 0
        idx = 0

        if ext in (".csv", ".tsv"):
            sep = "\t" if ext == ".tsv" else ","
            for chunk in pd.read_csv(file_path, sep=sep, chunksize=settings.CHUNK_SIZE_ROWS, low_memory=False):
                total_rows += len(chunk)
                path = str(chunk_dir / f"chunk_{idx}.csv")
                chunk.to_csv(path, index=False)
                chunk_paths.append(path)
                idx += 1

        elif ext in (".xlsx", ".xls"):
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            df = pd.read_excel(file_path, engine=engine)
            total_rows = len(df)
            for start in range(0, total_rows, settings.CHUNK_SIZE_ROWS):
                path = str(chunk_dir / f"chunk_{idx}.csv")
                df.iloc[start: start + settings.CHUNK_SIZE_ROWS].to_csv(path, index=False)
                chunk_paths.append(path)
                idx += 1

        return chunk_paths, total_rows

    @staticmethod
    def merge_chunks(job_id: str, original_filename: str) -> Tuple[str, dict]:
        chunk_dir = Path(settings.CHUNKS_DIR) / job_id
        processed_dir = Path(settings.PROCESSED_DIR)
        processed_dir.mkdir(parents=True, exist_ok=True)

        # Prefer cleaned chunks; fall back to raw if cleaning produced nothing
        cleaned = sorted(chunk_dir.glob("cleaned_chunk_*.csv"))
        source_files = cleaned if cleaned else sorted(chunk_dir.glob("chunk_*.csv"))

        merged = pd.concat([pd.read_csv(f) for f in source_files], ignore_index=True)

        ext = Path(original_filename).suffix.lower()
        result_path = str(processed_dir / f"cleaned_{job_id}{ext}")

        if ext in (".xlsx", ".xls"):
            merged.to_excel(result_path, index=False, engine="openpyxl")
        else:
            merged.to_csv(result_path, index=False)

        # Aggregate per-chunk stats
        stats = {"cleaned_rows": len(merged), "duplicates_removed": 0, "missing_filled": 0}
        for sf in chunk_dir.glob("stats_*.json"):
            with open(sf) as f:
                s = json.load(f)
                stats["duplicates_removed"] += s.get("duplicates_removed", 0)
                stats["missing_filled"] += s.get("missing_filled", 0)

        return result_path, stats
