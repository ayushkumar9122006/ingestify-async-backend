# Ingestify — Asynchronous Document & Media Processing Engine

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.3+-37814A.svg)](https://docs.celeryq.dev/)
[![Redis](https://img.shields.io/badge/Redis-7.0+-DC382D.svg)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791.svg)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-v2-2496ED.svg)](https://docs.docker.com/compose/)

**Ingestify** is an enterprise-grade, asynchronous document and media processing engine. Built upon a unified Clean Architecture, it ingests documents and media streams, dynamically routes workloads into dedicated priority queues, performs resilient parsing and artifact extraction with exponential backoff retries, and tracks operational analytics in PostgreSQL.

---

## Architecture Flow Diagram

```text
                               +---------------------------------------------+
                               |              Client Application             |
                               +---------------------------------------------+
                                                      |
                                          HTTP POST /jobs/upload
                                          (Multipart File Stream)
                                                      v
+---------------------------------------------------------------------------------------------------------+
|                                           FASTAPI CORE API                                              |
|                                                                                                         |
|  1. Streams payload into Shared Storage (/app/storage/uploads)                                          |
|  2. Registers IngestionJob record in PostgreSQL with status PENDING                                     |
|  3. Evaluates Routing Policy (Size < 1MB or Urgent Flag -> 'high-priority', else 'default')             |
|  4. Returns HTTP 202 Accepted with Job ID immediately                                                   |
+---------------------------------------------------------------------------------------------------------+
                                 |                                 |
           Pushes Task to Redis  |                                 | Persists Initial Job State
                                 v                                 v
               +----------------------------------+   +------------------------------------+
               |           REDIS BROKER           |   |        POSTGRESQL DATABASE         |
               |                                  |   |                                    |
               |  Queue: [ high-priority ]        |   |  - users                           |
               |  Queue: [ default       ]        |   |  - ingestion_jobs                  |
               +----------------------------------+   |  - extracted_artifacts             |
                         |               |            +------------------------------------+
         high-priority   |               | default                      ^
                         v               v                              |
    +-------------------------+   +-------------------------+           |
    |     WORKER-PRIORITY     |   |     WORKER-DEFAULT      |           |
    |   (High-Priority Q)     |   |      (Default Q)        |           |
    |   Concurrency: 4        |   |   Concurrency: 2        |           |
    +-------------------------+   +-------------------------+           |
                 \                            /                         |
                  \                          /                          |
                   v                        v                           |
        +----------------------------------------------+                |
        |             EXTRACTION PIPELINE              |                |
        |                                              |                |
        |  1. Text Extraction & Word Counting          |----------------+
        |  2. Structural & Cryptographic Metadata      |   Updates Job Status (COMPLETED/FAILED)
        |  3. Vector / SVG Thumbnail Generation        |   Records Processing Duration (ms)
        |  4. Exponential Backoff Retries (max 3)      |   Stores Extracted Artifact Record
        +----------------------------------------------+
                                |
                                v
               +----------------------------------+
               |          FLOWER MONITOR          |
               |    Real-Time Queue Dashboard     |
               |          Port: 5555              |
               +----------------------------------+
```

---

## Core Engineering Highlights

- **Non-Blocking Asynchronous File Ingestion**: Large media and batch files are received in streamed chunks and queued instantly. The API yields an immediate `202 Accepted` response with a UUID tracking token.
- **Dynamic Task Queues & Priority Routing**: Small files ($\le 1\,\text{MB}$) or requests marked with `is_urgent=true` are automatically scheduled on the `high-priority` queue, served by dedicated high-concurrency workers. Standard and heavy documents route to the `default` queue.
- **Active Job Revocation & Task Cancellation**: Ongoing or queued Celery tasks can be terminated on-demand using `app.control.revoke(task_id, terminate=True, signal="SIGTERM")`. The database state immediately flips to `CANCELLED`.
- **Distributed Request Tracing & Correlation IDs**: Every inbound request is stamped with an `X-Request-ID` correlation token (incoming or generated UUID4). This trace ID is injected into HTTP response headers, application loggers, and Celery task headers for end-to-end distributed observability.
- **Redis-Backed Atomic Rate Limiting**: File uploads (`POST /api/v1/jobs/upload`) are shielded by an atomic Redis rate limiter (5 uploads per minute per IP), preventing abuse with standard `429 Too Many Requests` and `Retry-After` response headers.
- **Fault Tolerance & Exponential Backoff**: Processing tasks feature automated exponential retry mechanisms (`max_retries=3`, delays: 5s $\to$ 10s $\to$ 20s) with error diagnostics recorded to PostgreSQL upon permanent failure.
- **Duration Tracking & Rich Artifact Extraction**: Every job measures exact CPU/IO execution duration in milliseconds (`processing_time_ms`), computes document summaries, word counts, SHA-256 checksums, and synthesizes SVG document thumbnails.
- **System Metrics & Ingestion Analytics**: Real-time aggregation endpoints provide platform insights: success/failure ratios, average latency, MIME type distributions, and storage volume parsed.

---

## Unified Codebase Architecture

```text
docker-fastapi-celery-redis-master/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── api.py                    # Root v1 APIRouter
│   │       └── endpoints/
│   │           ├── analytics.py          # /api/v1/analytics/stats
│   │           ├── auth.py               # /api/v1/auth (Register, Login, Me)
│   │           └── jobs.py               # /api/v1/jobs (Upload, Status, List, Cancel)
│   ├── core/
│   │   ├── config.py                     # Pydantic Settings & environment variables
│   │   ├── database.py                   # SQLAlchemy engine, SessionLocal & get_db
│   │   ├── middleware.py                 # CorrelationIdMiddleware & request tracing
│   │   ├── rate_limiter.py               # Redis-backed atomic upload rate limiter
│   │   └── security.py                   # Password hashing (bcrypt) & JWT handling
│   ├── models/
│   │   ├── artifact.py                   # ExtractedArtifact ORM model
│   │   ├── enums.py                      # UserRole, JobStatus, TaskPriority enums
│   │   ├── job.py                        # IngestionJob ORM model
│   │   └── user.py                       # User ORM model
│   ├── schemas/
│   │   ├── job.py                        # IngestionJob, Artifact & Stats Pydantic schemas
│   │   └── user.py                       # User & Token Pydantic schemas
│   ├── services/
│   │   ├── document_processor.py         # Text parsing, metadata & SVG thumbnail synthesis
│   │   ├── file_service.py               # Async chunked file streaming & storage
│   │   └── job_service.py                # Job orchestration, queries & queue assignment
│   ├── workers/
│   │   ├── celery_app.py                 # Celery app, Redis broker & queue definitions
│   │   └── tasks.py                      # process_document_job task with exponential backoff
│   ├── static/                           # Self-hosted clean ReDoc standalone bundle
│   └── main.py                           # FastAPI application entrypoint & lifespan hooks
├── tests/                                # Automated unit and integration test suite
│   ├── conftest.py                       # In-memory SQLite, mock Celery & mock Redis fixtures
│   └── test_jobs.py                      # End-to-end API, rate limiting, and tracing tests
├── storage/                              # Volume mount for uploaded & parsed files
│   ├── uploads/
│   ├── artifacts/
│   └── thumbnails/
├── .dockerignore
├── .env.example
├── docker-compose.yml                    # Multi-container orchestration (5 services + Flower)
├── Dockerfile                            # Optimized Python 3.11 Debian-slim image
├── README.md
└── requirements.txt                      # Locked production dependencies
```

---

## Docker Compose Services

| Service Name | Description | Host Port | Internal Port | Concurrency / Role |
| :--- | :--- | :--- | :--- | :--- |
| **`web`** | FastAPI Application Server (Uvicorn) | `5001`, `8000` | `5001` | API Gateway, Upload handler |
| **`worker-priority`** | Celery Worker (High-Priority Queue) | — | — | 4 worker threads, queues: `high-priority`, `default` |
| **`worker-default`** | Celery Worker (Default Queue) | — | — | 2 worker threads, queue: `default` |
| **`redis`** | Redis Message Broker & Result Store | `6379` | `6379` | In-memory message broker & cache |
| **`db`** | PostgreSQL 15 Relational Store | `5432` | `5432` | Jobs, Artifacts & User credentials |
| **`flower`** | Celery Task Monitoring Dashboard | `5555` | `5555` | Real-time queue & worker visualizer |

---

## Quickstart & Local Deployment

### 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/) (v2.0+)

### 2. Configure Environment (Optional)
Copy the default environment variables template:
```bash
cp .env.example .env
```

### 3. Build & Run Containers
Spin up all services in detached mode:
```bash
docker compose up -d --build
```

Verify that all 6 services are healthy and running:
```bash
docker compose ps
```

### 4. Service Access Endpoints
- **Interactive OpenAPI Documentation**: [http://localhost:5001/docs](http://localhost:5001/docs)
- **Alternative Redoc Documentation**: [http://localhost:5001/redoc](http://localhost:5001/redoc)
- **Flower Monitoring Dashboard**: [http://localhost:5555](http://localhost:5555)
- **FastAPI Health Check**: [http://localhost:5001/health_check](http://localhost:5001/health_check)

---

## Running Automated Tests (`pytest`)

The codebase includes an enterprise-grade automated test suite in `tests/` covering end-to-end endpoints, priority queue assignments, cancellation semantics, correlation ID tracing, and rate limiting using an in-memory SQLite database and isolated Redis/Celery mocks.

### Run Tests Inside Docker Container
```bash
docker compose exec web pytest -v
```

### Run Tests Locally (Host Machine)
```bash
pip install -r requirements.txt
pytest -v
```

**Test Coverage Highlights**:
- `test_health_check_endpoint` & `test_root_endpoint`: Verification of probes and documentation endpoints.
- `test_upload_job_success` & `test_upload_job_urgent_priority_routing`: Validates 202 status and dynamic queue routing (`high-priority` vs `default`).
- `test_get_job_status_and_artifacts`: Validates retrieval of extracted summaries, metadata JSON, and thumbnail paths.
- `test_cancel_pending_job_success` & `test_cancel_completed_job_fails`: Asserts task revocation and terminal state constraints.
- `test_correlation_id_middleware`: Verifies auto-generation and round-trip propagation of `X-Request-ID`.
- `test_rate_limiter_blocks_excessive_uploads`: Verifies that 5 uploads pass and the 6th returns `HTTP 429 Too Many Requests`.

---

## REST API Reference & Examples

### 1. Upload a Document for Ingestion
Uploads a file and automatically routes it to `high-priority` or `default` queue. Includes correlation tracing (`X-Request-ID`) and Redis rate limiting (max 5 uploads/min per IP).

```bash
# Upload with optional custom correlation ID
curl -X POST "http://localhost:5001/api/v1/jobs/upload" \
  -H "X-Request-ID: trace-custom-9988" \
  -F "file=@sample_report.pdf" \
  -F "is_urgent=false"
```

**Response (HTTP 202 Accepted):**
```http
HTTP/1.1 202 Accepted
X-Request-ID: trace-custom-9988
```
```json
{
  "id": "7f8b9a24-2c09-4ce4-8f78-29219b16bbd3",
  "user_id": null,
  "filename": "sample_report.pdf",
  "file_size_bytes": 245760,
  "mime_type": "application/pdf",
  "status": "PENDING",
  "celery_task_id": "b810263f-671c-4b5c-a521-b3b0d2d7c541",
  "error_message": null,
  "processing_time_ms": 0.0,
  "created_at": "2026-10-22T09:30:00Z",
  "updated_at": "2026-10-22T09:30:00Z",
  "artifact": null,
  "celery_state": "PENDING"
}
```

**Rate-Limited Response (HTTP 429 Too Many Requests):**
When exceeding 5 uploads in a 60-second window:
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 54
```
```json
{
  "detail": "Rate limit exceeded: Maximum 5 upload requests allowed per 60 seconds. Please retry in 54 seconds."
}
```


---

### 2. Check Job Processing Status & Retrieve Artifacts
Poll the real-time execution status and extract processed outputs.

```bash
curl -X GET "http://localhost:5001/api/v1/jobs/7f8b9a24-2c09-4ce4-8f78-29219b16bbd3"
```

**Response (HTTP 200 OK — Completed):**
```json
{
  "id": "7f8b9a24-2c09-4ce4-8f78-29219b16bbd3",
  "filename": "sample_report.pdf",
  "file_size_bytes": 245760,
  "mime_type": "application/pdf",
  "status": "COMPLETED",
  "celery_task_id": "b810263f-671c-4b5c-a521-b3b0d2d7c541",
  "error_message": null,
  "processing_time_ms": 1523.45,
  "created_at": "2026-10-22T09:30:00Z",
  "updated_at": "2026-10-22T09:30:02Z",
  "artifact": {
    "id": "c1f73b64-a74e-4f3b-8dc2-482d8c36081e",
    "job_id": "7f8b9a24-2c09-4ce4-8f78-29219b16bbd3",
    "summary_text": "Executive Summary (sample_report.pdf): Ingestify DeepParser v1.0 successfully processed...",
    "word_count": 1000,
    "metadata_json": {
      "engine": "Ingestify-Extraction-Pipeline-v1",
      "filename": "sample_report.pdf",
      "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
      "file_size_bytes": 245760,
      "mime_type": "application/pdf",
      "estimated_pages": 4,
      "character_count": 158,
      "language_detected": "en-US",
      "quality_score": 0.98
    },
    "thumbnail_path": "/app/storage/thumbnails/7f8b9a24-2c09-4ce4-8f78-29219b16bbd3_thumb.svg",
    "created_at": "2026-10-22T09:30:02Z"
  },
  "celery_state": "SUCCESS"
}
```

---

### 3. List Ingestion Jobs (Paginated & Filtered)
Filter by status (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `CANCELLED`) or MIME type substring.

```bash
curl -X GET "http://localhost:5001/api/v1/jobs/?page=1&page_size=10&status=COMPLETED"
```

---

### 4. Cancel / Revoke an Active Job
Revokes the task from Celery workers immediately using `SIGTERM` and records `CANCELLED` status.

```bash
curl -X POST "http://localhost:5001/api/v1/jobs/7f8b9a24-2c09-4ce4-8f78-29219b16bbd3/cancel"
```

**Response (HTTP 200 OK):**
```json
{
  "job_id": "7f8b9a24-2c09-4ce4-8f78-29219b16bbd3",
  "status": "CANCELLED",
  "message": "Job 7f8b9a24-2c09-4ce4-8f78-29219b16bbd3 was successfully revoked and cancelled."
}
```

---

### 5. Platform Analytics & Performance Metrics
Aggregates operational throughput and processing speeds.

```bash
curl -X GET "http://localhost:5001/api/v1/analytics/stats"
```

**Response (HTTP 200 OK):**
```json
{
  "total_jobs": 142,
  "completed_jobs": 136,
  "failed_jobs": 2,
  "pending_jobs": 1,
  "processing_jobs": 1,
  "cancelled_jobs": 2,
  "success_rate_percent": 98.55,
  "failure_rate_percent": 1.45,
  "average_processing_time_ms": 1485.22,
  "total_storage_bytes": 158329600,
  "total_storage_mb": 151.0,
  "mime_type_distribution": {
    "application/pdf": 84,
    "image/png": 32,
    "text/plain": 18,
    "application/json": 8
  }
}
```

---

## Celery Worker Scaling

Scale worker processes dynamically without interrupting running services:

```bash
# Scale default worker instances to 4
docker compose up -d --scale worker-default=4 --no-recreate

# Scale priority worker instances to 6
docker compose up -d --scale worker-priority=6 --no-recreate
```

To gracefully shut down the cluster:
```bash
docker compose down
```

To remove all persistent data volumes (database, message queues, and shared storage):
```bash
docker compose down -v
```

---

## License
MIT License. Open-source enterprise template.
