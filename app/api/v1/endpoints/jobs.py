from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limiter import upload_rate_limiter
from app.models.enums import JobStatus
from app.schemas.job import JobResponse, JobListResponse, JobCancelResponse
from app.services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["Ingestion Jobs"])


@router.post(
    "/upload",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(upload_rate_limiter)],
    summary="Upload document for asynchronous ingestion",
    description="Accepts multipart file upload, registers PENDING job in PostgreSQL, dispatches Celery task on dynamic queue (high-priority for <1MB or urgent files, default for others), and returns 202 Accepted. Rate-limited to 5 requests per minute per IP.",
)
async def upload_document(
    file: UploadFile = File(..., description="Document or media file to process"),
    is_urgent: bool = Form(False, description="Mark as urgent to force high-priority queue"),
    priority: Optional[str] = Form(None, description="Explicit queue target: 'default' or 'high-priority'"),
    db: Session = Depends(get_db),
):
    job = await job_service.create_job(
        db=db,
        upload_file=file,
        is_urgent=is_urgent,
        priority=priority,
    )
    return job


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job status and extracted artifacts",
    description="Retrieves real-time processing status from PostgreSQL and Celery broker, including extracted metadata, text summary, and thumbnail path.",
)
def get_job_by_id(
    job_id: str,
    db: Session = Depends(get_db),
):
    job, celery_state = job_service.get_job(db=db, job_id=job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

    # Convert to schema response and augment with live Celery state
    response = JobResponse.model_validate(job)
    response.celery_state = celery_state
    return response


@router.get(
    "/",
    response_model=JobListResponse,
    summary="List ingestion jobs (paginated)",
    description="Returns a paginated list of ingestion jobs with optional status and MIME type filters.",
)
def list_jobs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[JobStatus] = Query(None, description="Filter by status (PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED)"),
    mime_type: Optional[str] = Query(None, description="Filter by MIME type substring"),
    db: Session = Depends(get_db),
):
    items, total, total_pages = job_service.list_jobs(
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status,
        mime_type_filter=mime_type,
    )
    return JobListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[JobResponse.model_validate(item) for item in items],
    )


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    summary="Cancel active or pending ingestion job",
    description="Revokes active/pending Celery worker task via app.control.revoke and marks job status as CANCELLED in PostgreSQL.",
)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = job_service.cancel_job(db=db, job_id=job_id)
    return JobCancelResponse(
        job_id=job.id,
        status=job.status,
        message=f"Job {job.id} was successfully revoked and cancelled.",
    )
