from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.job import AnalyticsStatsResponse
from app.services.job_service import job_service

router = APIRouter(prefix="/analytics", tags=["Analytics & Metrics"])


@router.get(
    "/stats",
    response_model=AnalyticsStatsResponse,
    summary="Get system-wide ingestion analytics",
    description="Calculates overall platform metrics: total processed jobs, success/failure rates, average processing time in ms, and cumulative storage volume parsed.",
)
def get_analytics_stats(db: Session = Depends(get_db)):
    metrics = job_service.get_analytics(db=db)
    return AnalyticsStatsResponse(**metrics)
