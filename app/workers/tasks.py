import time
import logging
from typing import Dict, Any
from celery.exceptions import Ignore
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.job import IngestionJob
from app.models.artifact import ExtractedArtifact
from app.models.enums import JobStatus
from app.services.document_processor import document_processor

from app.core.middleware import correlation_id_ctx

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_document_job",
    max_retries=3,
    default_retry_delay=5,
)
def process_document_job(self, job_id: str, file_path: str, mime_type: str) -> Dict[str, Any]:
    """
    Celery task that processes an ingested file:
    - Extracts text & structured metadata
    - Generates thumbnail artifact
    - Tracks execution duration in milliseconds
    - Updates PostgreSQL status with robust exponential backoff retries
    - Propagates distributed request correlation ID
    """
    start_time = time.perf_counter()
    headers = getattr(self.request, "headers", None) or {}
    cid = headers.get("correlation_id") or getattr(self.request, "correlation_id", None) or "-"
    token = correlation_id_ctx.set(cid)

    db = SessionLocal()

    try:
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            logger.error(f"[{cid}] [Job {job_id}] Job record not found in database.")
            return {"status": "NOT_FOUND", "job_id": job_id}

        # Check if already cancelled before processing
        if job.status == JobStatus.CANCELLED.value:
            logger.info(f"[{cid}] [Job {job_id}] Job was cancelled prior to worker execution.")
            return {"status": "CANCELLED", "job_id": job_id}

        # Update status to PROCESSING
        job.status = JobStatus.PROCESSING.value
        job.celery_task_id = self.request.id
        db.commit()
        logger.info(f"[{cid}] [Job {job_id}] Processing started by worker (task_id: {self.request.id}).")

        # Simulate dynamic processing workload based on file type and size
        time.sleep(1.5)

        # Check cancellation again mid-process
        db.refresh(job)
        if job.status == JobStatus.CANCELLED.value:
            logger.info(f"[Job {job_id}] Job was cancelled during processing.")
            return {"status": "CANCELLED", "job_id": job_id}

        # Perform extraction, metadata parsing, and thumbnail generation
        summary_text, word_count, metadata_json, thumbnail_path = document_processor.process(
            job_id=job_id,
            file_path=file_path,
            mime_type=mime_type,
        )

        # Calculate processing duration
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Remove existing artifact if re-run
        existing_artifact = db.query(ExtractedArtifact).filter(ExtractedArtifact.job_id == job_id).first()
        if existing_artifact:
            db.delete(existing_artifact)
            db.flush()

        artifact = ExtractedArtifact(
            job_id=job.id,
            summary_text=summary_text,
            word_count=word_count,
            metadata_json=metadata_json,
            thumbnail_path=thumbnail_path,
        )
        db.add(artifact)

        job.status = JobStatus.COMPLETED.value
        job.processing_time_ms = duration_ms
        job.error_message = None
        db.commit()

        logger.info(f"[Job {job_id}] Completed successfully in {duration_ms} ms.")

        return {
            "status": "COMPLETED",
            "job_id": job_id,
            "processing_time_ms": duration_ms,
            "word_count": word_count,
            "thumbnail_path": thumbnail_path,
        }

    except Exception as exc:
        db.rollback()
        retry_num = self.request.retries
        backoff_delay = 5 * (2 ** retry_num)  # Exponential backoff: 5s, 10s, 20s
        logger.warning(
            f"[Job {job_id}] Error during processing: {exc}. Retrying in {backoff_delay}s (Attempt {retry_num + 1}/{self.max_retries})."
        )

        if retry_num < self.max_retries:
            try:
                raise self.retry(exc=exc, countdown=backoff_delay)
            except Exception:
                # Let Celery handle retry
                raise
        else:
            # Mark permanently failed
            try:
                failed_job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
                if failed_job:
                    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    failed_job.status = JobStatus.FAILED.value
                    failed_job.error_message = f"Processing failed after {self.max_retries} retries: {str(exc)}"
                    failed_job.processing_time_ms = duration_ms
                    db.commit()
            except Exception as db_err:
                logger.error(f"[Job {job_id}] Failed to persist failure state: {db_err}")

            logger.error(f"[Job {job_id}] Exceeded maximum retries ({self.max_retries}). Marked as FAILED.")
            raise exc

    finally:
        correlation_id_ctx.reset(token)
        db.close()

