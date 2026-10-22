import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from app.models.enums import JobStatus


class ExtractedArtifactResponse(BaseModel):
    id: str
    job_id: str
    summary_text: Optional[str] = None
    word_count: int
    metadata_json: Optional[Dict[str, Any]] = None
    thumbnail_path: Optional[str] = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class JobResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    filename: str
    file_size_bytes: int
    mime_type: str
    status: JobStatus
    celery_task_id: Optional[str] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[float] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    artifact: Optional[ExtractedArtifactResponse] = None
    celery_state: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[JobResponse]


class JobCancelResponse(BaseModel):
    job_id: str
    status: str
    message: str


class AnalyticsStatsResponse(BaseModel):
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    pending_jobs: int
    processing_jobs: int
    cancelled_jobs: int
    success_rate_percent: float
    failure_rate_percent: float
    average_processing_time_ms: float
    total_storage_bytes: int
    total_storage_mb: float
    mime_type_distribution: Dict[str, int]
