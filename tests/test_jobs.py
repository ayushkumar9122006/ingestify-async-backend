import io
import uuid
import pytest
from app.models.job import IngestionJob
from app.models.artifact import ExtractedArtifact
from app.models.enums import JobStatus


def test_health_check_endpoint(client):
    """Test health check probe returns 200 OK."""
    response = client.get("/health_check")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_root_endpoint(client):
    """Test root system endpoint returns documentation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Ingestify"
    assert "/docs" in data["documentation"]


def test_upload_job_success(client, mock_celery):
    """Test POST /api/v1/jobs/upload returns 202 Accepted with job metadata."""
    file_content = b"Contract Agreement: This document describes ingestion terms."
    files = {"file": ("test_contract.txt", io.BytesIO(file_content), "text/plain")}

    response = client.post("/api/v1/jobs/upload", files=files)
    assert response.status_code == 202
    data = response.json()

    assert "id" in data
    assert data["filename"] == "test_contract.txt"
    assert data["file_size_bytes"] == len(file_content)
    assert data["status"] == "PENDING"
    assert data["celery_task_id"] == "mock-celery-task-9999"

    # Verify Celery send_task was dispatched
    assert mock_celery["send_task"].called
    call_args = mock_celery["send_task"].call_args
    assert call_args[0][0] == "app.workers.tasks.process_document_job"


def test_upload_job_urgent_priority_routing(client, mock_celery):
    """Test urgent flag routes task to high-priority queue."""
    file_content = b"Urgent financial invoice payload."
    files = {"file": ("invoice.pdf", io.BytesIO(file_content), "application/pdf")}
    data = {"is_urgent": "true"}

    response = client.post("/api/v1/jobs/upload", files=files, data=data)
    assert response.status_code == 202

    call_kwargs = mock_celery["send_task"].call_args[1]
    assert call_kwargs["queue"] == "high-priority"


def test_get_job_status_and_artifacts(client, db_session):
    """Test retrieving job status and its extracted artifacts."""
    job_id = str(uuid.uuid4())
    job = IngestionJob(
        id=job_id,
        filename="financial_summary.pdf",
        file_size_bytes=10240,
        mime_type="application/pdf",
        status=JobStatus.COMPLETED.value,
        celery_task_id="celery-12345",
        processing_time_ms=1420.5,
    )
    db_session.add(job)

    artifact = ExtractedArtifact(
        job_id=job_id,
        summary_text="Financial summary parsed successfully.",
        word_count=520,
        metadata_json={"pages": 3, "score": 0.99},
        thumbnail_path="/tmp/thumbnails/thumb.svg",
    )
    db_session.add(artifact)
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == job_id
    assert data["status"] == "COMPLETED"
    assert data["processing_time_ms"] == 1420.5
    assert data["artifact"] is not None
    assert data["artifact"]["word_count"] == 520
    assert data["artifact"]["summary_text"] == "Financial summary parsed successfully."


def test_get_job_not_found(client):
    """Test retrieving non-existent job returns 404 Not Found."""
    non_existent_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/jobs/{non_existent_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_list_jobs_pagination_and_filtering(client, db_session):
    """Test paginated job listing with status filter."""
    for i in range(5):
        status = JobStatus.COMPLETED.value if i % 2 == 0 else JobStatus.PENDING.value
        job = IngestionJob(
            id=str(uuid.uuid4()),
            filename=f"doc_{i}.txt",
            file_size_bytes=100 * (i + 1),
            mime_type="text/plain",
            status=status,
        )
        db_session.add(job)
    db_session.commit()

    # Query only COMPLETED jobs
    response = client.get("/api/v1/jobs/?status=COMPLETED&page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 3
    assert len(data["items"]) == 3
    for item in data["items"]:
        assert item["status"] == "COMPLETED"


def test_cancel_pending_job_success(client, db_session, mock_celery):
    """Test cancelling a pending job revokes Celery task and updates status to CANCELLED."""
    job_id = str(uuid.uuid4())
    job = IngestionJob(
        id=job_id,
        filename="long_running_batch.csv",
        file_size_bytes=50000,
        mime_type="text/csv",
        status=JobStatus.PENDING.value,
        celery_task_id="task-to-cancel-777",
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 200
    data = response.json()

    assert data["job_id"] == job_id
    assert data["status"] == "CANCELLED"
    assert "cancelled" in data["message"].lower()

    # Verify revoke was called
    assert mock_celery["revoke"].called


def test_cancel_completed_job_fails(client, db_session):
    """Test attempting to cancel a terminal COMPLETED job returns 400 Bad Request."""
    job_id = str(uuid.uuid4())
    job = IngestionJob(
        id=job_id,
        filename="done.pdf",
        file_size_bytes=2048,
        mime_type="application/pdf",
        status=JobStatus.COMPLETED.value,
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 400
    assert "cannot cancel job in terminal state" in response.json()["detail"].lower()


def test_correlation_id_middleware(client):
    """Test that X-Request-ID header is generated and echoed back in response."""
    # 1. Automatic generation when header is omitted
    response = client.get("/health_check")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    generated_id = response.headers["X-Request-ID"]
    assert len(generated_id) > 10

    # 2. Propagation of custom incoming X-Request-ID
    custom_trace_id = "test-custom-trace-uuid-42"
    response2 = client.get("/health_check", headers={"X-Request-ID": custom_trace_id})
    assert response2.status_code == 200
    assert response2.headers["X-Request-ID"] == custom_trace_id


def test_rate_limiter_blocks_excessive_uploads(client, mock_redis):
    """Test rate limiter allows 5 uploads then returns 429 Too Many Requests on the 6th."""
    file_bytes = b"Sample upload byte content"

    # First 5 upload requests should pass
    for i in range(5):
        files = {"file": (f"test_{i}.txt", io.BytesIO(file_bytes), "text/plain")}
        res = client.post("/api/v1/jobs/upload", files=files)
        assert res.status_code == 202, f"Request {i+1} failed unexpectedly: {res.text}"

    # 6th upload request from the same IP must trigger 429 Too Many Requests
    files = {"file": ("test_limit.txt", io.BytesIO(file_bytes), "text/plain")}
    res_limited = client.post("/api/v1/jobs/upload", files=files)
    assert res_limited.status_code == 429
    assert "Rate limit exceeded" in res_limited.json()["detail"]
    assert "Retry-After" in res_limited.headers


def test_analytics_stats_endpoint(client, db_session):
    """Test analytics aggregation endpoint returns valid metrics."""
    # Insert completed job
    job1 = IngestionJob(
        id=str(uuid.uuid4()),
        filename="report1.pdf",
        file_size_bytes=5000,
        mime_type="application/pdf",
        status=JobStatus.COMPLETED.value,
        processing_time_ms=1000.0,
    )
    # Insert failed job
    job2 = IngestionJob(
        id=str(uuid.uuid4()),
        filename="report2.pdf",
        file_size_bytes=3000,
        mime_type="application/pdf",
        status=JobStatus.FAILED.value,
        processing_time_ms=500.0,
    )
    db_session.add_all([job1, job2])
    db_session.commit()

    response = client.get("/api/v1/analytics/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["total_jobs"] == 2
    assert data["completed_jobs"] == 1
    assert data["failed_jobs"] == 1
    assert data["success_rate_percent"] == 50.0
    assert data["failure_rate_percent"] == 50.0
    assert data["total_storage_bytes"] == 8000
