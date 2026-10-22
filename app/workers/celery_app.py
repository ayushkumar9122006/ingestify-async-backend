import os
from celery import Celery
from kombu import Queue, Exchange
from app.core.config import settings

# Initialize Celery app
celery_app = Celery(
    "ingestify",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

# Dynamic Queue Configuration: High-Priority and Default Queues
default_exchange = Exchange("default", type="direct")
priority_exchange = Exchange("high-priority", type="direct")

celery_app.conf.update(
    task_queues=(
        Queue("default", default_exchange, routing_key="default"),
        Queue("high-priority", priority_exchange, routing_key="high-priority"),
    ),
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    task_routes={
        "app.workers.tasks.process_document_job": {"queue": "default"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)

if __name__ == "__main__":
    celery_app.start()
