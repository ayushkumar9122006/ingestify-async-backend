import uuid
import math
from typing import Optional, Tuple, List, Dict, Any
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.job import IngestionJob
from app.models.enums import JobStatus, TaskPriority
from app.services.file_service import file_service
from app.workers.celery_app import celery_app
from app.core.middleware import get_correlation_id




class JobService:
    @staticmethod
    def determine_queue(file_size_bytes: int, is_urgent: bool = False, requested_priority: Optional[str] = None) -> str:
        """
        Dynamically route jobs:
        - High-priority if explicitly marked urgent or priority='high-priority'
        - High-priority if file size <= 1MB
        - Default queue for larger standard files
        """
        if requested_priority in ["high-priority", "high"]:
            return TaskPriority.HIGH.value
        if is_urgent:
            return TaskPriority.HIGH.value
        if file_size_bytes <= settings.HIGH_PRIORITY_SIZE_THRESHOLD_BYTES:
            return TaskPriority.HIGH.value
        return TaskPriority.DEFAULT.value

    @classmethod
    async def create_job(
        cls,
        db: Session,
        upload_file: UploadFile,
        is_urgent: bool = False,
        priority: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> IngestionJob:
        """Saves file, creates DB job, routes to Celery queue, and returns the pending job."""
        job_id = str(uuid.uuid4())

        # Save file to storage
        file_path, file_size, mime_type = await file_service.save_uploaded_file(job_id, upload_file)

        if file_size > settings.MAX_FILE_SIZE_BYTES:
            file_service.remove_file(file_path)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB",
            )

        # Determine dynamic queue
        target_queue = cls.determine_queue(file_size, is_urgent, priority)

        # Create DB record
        job = IngestionJob(
            id=job_id,
            user_id=user_id,
            filename=upload_file.filename or "uploaded_document",
            file_size_bytes=file_size,
            mime_type=mime_type,
            status=JobStatus.PENDING.value,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Dispatch task to Celery with targeted queue and correlation tracing
        cid = get_correlation_id()
        celery_task = celery_app.send_task(
            "app.workers.tasks.process_document_job",
            args=[job_id, file_path, mime_type],
            headers={"correlation_id": cid},
            queue=target_queue,
            routing_key=target_queue,
        )

        # Record Celery task ID
        job.celery_task_id = celery_task.id
        db.commit()
        db.refresh(job)

        return job

    @staticmethod
    def get_job(db: Session, job_id: str) -> Tuple[Optional[IngestionJob], Optional[str]]:
        """Retrieve job and its real-time Celery execution state."""
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            return None, None

        celery_state = None
        if job.celery_task_id:
            try:
                res = celery_app.AsyncResult(job.celery_task_id)
                celery_state = res.state
            except Exception:
                celery_state = "UNKNOWN"

        return job, celery_state

    @staticmethod
    def list_jobs(
        db: Session,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[JobStatus] = None,
        mime_type_filter: Optional[str] = None,
    ) -> Tuple[List[IngestionJob], int, int]:
        """Paginated listing of ingestion jobs with status and mime_type filters."""
        query = db.query(IngestionJob)

        if status_filter:
            query = query.filter(IngestionJob.status == status_filter.value)
        if mime_type_filter:
            query = query.filter(IngestionJob.mime_type.ilike(f"%{mime_type_filter}%"))

        total = query.count()
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        offset = (page - 1) * page_size

        items = query.order_by(IngestionJob.created_at.desc()).offset(offset).limit(page_size).all()
        return items, total, total_pages

    @staticmethod
    def cancel_job(db: Session, job_id: str) -> IngestionJob:
        """Revokes active or pending Celery task and marks job as CANCELLED."""
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found.")

        if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel job in terminal state: {job.status}",
            )

        if job.status == JobStatus.CANCELLED.value:
            return job

        # Revoke Celery task if ID exists
        if job.celery_task_id:
            try:
                celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        job.status = JobStatus.CANCELLED.value
        job.error_message = "Job execution revoked and cancelled by user."
        db.commit()
        db.refresh(job)

        return job

    @staticmethod
    def get_analytics(db: Session) -> Dict[str, Any]:
        """Calculates system metrics: total jobs, success/failure rates, avg processing time, storage volume."""
        total_jobs = db.query(func.count(IngestionJob.id)).scalar() or 0
        completed_jobs = db.query(func.count(IngestionJob.id)).filter(IngestionJob.status == JobStatus.COMPLETED.value).scalar() or 0
        failed_jobs = db.query(func.count(IngestionJob.id)).filter(IngestionJob.status == JobStatus.FAILED.value).scalar() or 0
        pending_jobs = db.query(func.count(IngestionJob.id)).filter(IngestionJob.status == JobStatus.PENDING.value).scalar() or 0
        processing_jobs = db.query(func.count(IngestionJob.id)).filter(IngestionJob.status == JobStatus.PROCESSING.value).scalar() or 0
        cancelled_jobs = db.query(func.count(IngestionJob.id)).filter(IngestionJob.status == JobStatus.CANCELLED.value).scalar() or 0

        # Success and failure rate
        finished_jobs = completed_jobs + failed_jobs
        if finished_jobs > 0:
            success_rate = round((completed_jobs / finished_jobs) * 100, 2)
            failure_rate = round((failed_jobs / finished_jobs) * 100, 2)
        else:
            success_rate = 0.0
            failure_rate = 0.0

        # Average processing time for completed jobs
        avg_time = (
            db.query(func.avg(IngestionJob.processing_time_ms))
            .filter(IngestionJob.status == JobStatus.COMPLETED.value)
            .scalar()
        )
        avg_processing_time_ms = round(float(avg_time), 2) if avg_time else 0.0

        # Storage volume
        total_bytes = db.query(func.sum(IngestionJob.file_size_bytes)).scalar() or 0
        total_mb = round(total_bytes / (1024 * 1024), 2)

        # MIME type distribution
        mime_results = (
            db.query(IngestionJob.mime_type, func.count(IngestionJob.id))
            .group_by(IngestionJob.mime_type)
            .all()
        )
        mime_distribution = {mime: count for mime, count in mime_results}

        return {
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "pending_jobs": pending_jobs,
            "processing_jobs": processing_jobs,
            "cancelled_jobs": cancelled_jobs,
            "success_rate_percent": success_rate,
            "failure_rate_percent": failure_rate,
            "average_processing_time_ms": avg_processing_time_ms,
            "total_storage_bytes": int(total_bytes),
            "total_storage_mb": total_mb,
            "mime_type_distribution": mime_distribution,
        }


job_service = JobService()
