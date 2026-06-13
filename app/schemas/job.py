from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.job import JobStatus


class CleaningOptions(BaseModel):
    remove_duplicates: bool = True
    fill_missing: bool = True
    fix_formatting: bool = True
    remove_empty_rows: bool = True
    use_ai_insights: bool = False
    missing_fill_strategy: str = "mean"  # mean | median | mode | drop | fill_value
    missing_fill_value: Optional[str] = None


class JobCreate(BaseModel):
    cleaning_options: Optional[CleaningOptions] = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float
    original_filename: Optional[str]
    file_size_bytes: Optional[int]
    total_rows: int
    cleaned_rows: int
    duplicates_removed: int
    missing_filled: int
    total_chunks: int
    completed_chunks: int
    result_file_path: Optional[str]
    error_message: Optional[str]
    ai_insights: Optional[Dict[str, Any]]
    created_at: datetime
    completed_at: Optional[datetime]
    expires_at: Optional[datetime] = None
    files_deleted: bool = False

    class Config:
        from_attributes = True
